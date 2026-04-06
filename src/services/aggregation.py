"""
Serviço de agregação de inventário.

Responsabilidades:
1. Iterar sobre todas as lojas e operações configuradas
2. Aplicar lógica de dedup_group (evita double-count de credenciais compartilhadas)
3. Coletar erros parciais sem interromper o fetch das demais operações
4. Construir DataFrames detalhado e consolidado

Dedup_group (caso Loja 0101 B2B = B2C):
  - Operações com mesmo dedup_group compartilham credenciais idênticas e o mesmo estoque físico
  - Uma única chamada API é feita (para a primeira operação do grupo)
  - Os registros são clonados para as demais operações do grupo (visão detalhada)
  - No consolidado, apenas a primeira operação de cada grupo contribui para a soma
  - Isso evita que o estoque de 0101 seja contado duas vezes no total nacional

Regra de saldo consolidado:
  stock_net_consolidated  = stock_available + stock_blocked   ← saldo real disponível no CD
  stock_reserved          é exibido como informativo mas NÃO entra no total consolidado,
                          pois representa pallets já alocados a pedidos em processo de expedição.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from src.models.inventory import InventoryRecord
from src.models.store import StoreConfig
from src.providers.base import InventoryProvider
from src.providers.estoca.client import EstocaAuthError


@dataclass
class OperationError:
    """Detalhes de uma falha em uma operação específica."""

    store_code: str
    operation_type: str
    error_type: str
    message: str


@dataclass
class FetchResult:
    """
    Resultado de um fetch completo de todas as lojas/operações.

    Separa registros bem-sucedidos dos erros parciais,
    permitindo que o dashboard exiba dados parciais mesmo quando
    algumas operações falham.
    """

    records: list[InventoryRecord] = field(default_factory=list)
    errors: list[OperationError] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def total_records(self) -> int:
        return len(self.records)


class InventoryAggregationService:
    """
    Orquestra a coleta e consolidação de estoque de todas as fontes.

    Suporta múltiplos providers (Estoca hoje, outros WMS no futuro).
    Recebe uma instância de InventoryProvider e a lista de StoreConfig
    já resolvida (com api_keys injetadas).
    """

    def __init__(
        self,
        provider: InventoryProvider,
        stores: list[StoreConfig],
    ) -> None:
        self.provider = provider
        self.stores = stores

    # ─── Fetch ────────────────────────────────────────────────────────────────

    def fetch_all(self) -> FetchResult:
        """
        Executa o fetch de inventário para todas as lojas/operações.

        Aplica a lógica de dedup_group para evitar chamadas e double-count
        em operações com credenciais compartilhadas.

        Returns:
            FetchResult com todos os registros e lista de erros ocorridos.
        """
        result = FetchResult()

        # Cache de registros já buscados por dedup_group
        # dedup_group -> list[InventoryRecord] (registros com operation_type primário)
        dedup_cache: dict[str, list[InventoryRecord]] = {}

        total_stores = len(self.stores)
        logger.info(
            f"Iniciando fetch de inventário: {total_stores} loja(s) configurada(s)."
        )

        for store in self.stores:
            for op_idx, operation in enumerate(store.operations):
                label = f"{store.store_code}/{operation.operation_type}"

                # ── Verificação de dedup_group ──────────────────────────────
                if operation.dedup_group is not None:
                    if operation.dedup_group in dedup_cache:
                        # Operação secundária: clona registros do primário
                        primary_records = dedup_cache[operation.dedup_group]
                        cloned = self._clone_records_for_operation(
                            primary_records, operation, store
                        )
                        for rec in cloned:
                            rec.is_dedup_secondary = True
                        result.records.extend(cloned)
                        logger.info(
                            f"[{label}] Dedup group '{operation.dedup_group}': "
                            f"{len(cloned)} registros clonados do primário "
                            f"(nenhuma chamada API adicional)."
                        )
                        continue  # pula chamada API

                # ── Fetch via provider ──────────────────────────────────────
                try:
                    logger.info(f"[{label}] Iniciando fetch de inventário...")
                    records = self.provider.get_full_inventory(store, op_idx)
                    result.records.extend(records)

                    # Armazena no cache de dedup se aplicável
                    if operation.dedup_group is not None:
                        dedup_cache[operation.dedup_group] = records

                    logger.info(
                        f"[{label}] Concluído: {len(records)} registros obtidos."
                    )

                except EstocaAuthError as exc:
                    msg = str(exc)
                    logger.error(f"[{label}] Erro de autenticação: {msg}")
                    result.errors.append(
                        OperationError(
                            store_code=store.store_code,
                            operation_type=operation.operation_type,
                            error_type="AuthenticationError",
                            message=msg,
                        )
                    )

                except Exception as exc:
                    msg = str(exc)
                    logger.error(f"[{label}] Erro inesperado: {msg}")
                    result.errors.append(
                        OperationError(
                            store_code=store.store_code,
                            operation_type=operation.operation_type,
                            error_type=type(exc).__name__,
                            message=msg,
                        )
                    )

        logger.info(
            f"Fetch concluído: {result.total_records} registros, "
            f"{len(result.errors)} erros."
        )
        return result

    def _clone_records_for_operation(
        self,
        source_records: list[InventoryRecord],
        target_operation,
        store: StoreConfig,
    ) -> list[InventoryRecord]:
        """
        Clona registros substituindo os campos da operação de destino.

        Usado para operações em dedup_group: os saldos são idênticos,
        mas cada operação aparece como linha separada na visão detalhada.
        """
        cloned: list[InventoryRecord] = []
        for rec in source_records:
            new_rec = rec.model_copy(
                update={
                    "operation_type": target_operation.operation_type,
                    "estoca_store_id": target_operation.store_id,
                }
            )
            cloned.append(new_rec)
        return cloned

    # ─── DataFrames ───────────────────────────────────────────────────────────

    def get_detailed_dataframe(self, records: list[InventoryRecord]) -> pd.DataFrame:
        """
        Constrói o DataFrame detalhado: uma linha por (store_code, operation_type, sku).

        Inclui todos os campos do modelo canônico.

        Args:
            records: Lista de InventoryRecord (pode ser filtrada).

        Returns:
            DataFrame com colunas do modelo canônico, ordenado por store_code, operation_type, sku.
        """
        if not records:
            return pd.DataFrame(
                columns=[
                    "source_system", "country", "business_unit", "store_code",
                    "operation_type", "estoca_store_id", "estoca_warehouse_id",
                    "sku", "product_name", "stock_total", "stock_available", "stock_reserved",
                    "stock_blocked", "updated_at",
                ]
            )

        rows = [
            {
                "source_system": r.source_system,
                "country": r.country,
                "business_unit": r.business_unit,
                "store_code": r.store_code,
                "operation_type": r.operation_type,
                "estoca_store_id": r.estoca_store_id,
                "estoca_warehouse_id": r.estoca_warehouse_id,
                "sku": r.sku,
                "product_name": r.product_name,
                "stock_total": r.stock_total,
                "stock_available": r.stock_available,
                "stock_reserved": r.stock_reserved,
                "stock_blocked": r.stock_blocked,
                "updated_at": r.updated_at,
            }
            for r in records
        ]

        df = pd.DataFrame(rows)
        df = df.sort_values(["store_code", "operation_type", "sku"]).reset_index(drop=True)
        return df

    def get_consolidated_dataframe(
        self,
        records: list[InventoryRecord],
        include_dedup_secondary: bool = False,
    ) -> pd.DataFrame:
        """
        Constrói o DataFrame consolidado: uma linha por SKU com somas de todos os registros.

        Regra de dedup:
        Por padrão (include_dedup_secondary=False), registros marcados como is_dedup_secondary
        são EXCLUÍDOS da soma. Isso evita que o estoque de lojas com credenciais compartilhadas
        (ex: 0101 B2B = B2C) seja contado duas vezes no total nacional.

        Regra de saldo:
        stock_net_consolidated = stock_available_consolidated + stock_blocked_consolidated
        O stock_reserved (holded) representa pallets já alocados a pedidos em expedição —
        é exibido como informativo mas NÃO compõe o total consolidado.

        Campos do DataFrame:
          sku, product_name, source_count, operations_list,
          stock_net_consolidated, stock_available_consolidated,
          stock_blocked_consolidated, stock_reserved_consolidated (informativo),
          updated_at (mais recente entre os registros)

        Args:
            records:                 Lista de InventoryRecord (pode ser filtrada).
            include_dedup_secondary: Se True, inclui todos os registros na soma
                                     (pode causar double-count em lojas com dedup_group).

        Returns:
            DataFrame consolidado por SKU.
        """
        _empty_columns = [
            "sku", "product_name", "source_count", "operations_list",
            "stock_net_consolidated", "stock_available_consolidated",
            "stock_blocked_consolidated", "stock_reserved_consolidated",
            "updated_at",
        ]

        if not records:
            return pd.DataFrame(columns=_empty_columns)

        # Filtra registros excluídos do consolidado:
        # 1. Registros secundários de dedup_group (evita double-count)
        # 2. Registros de lojas auxiliares marcadas com exclude_from_consolidation
        if not include_dedup_secondary:
            records_for_sum = [
                r for r in records
                if not r.is_dedup_secondary and not r.exclude_from_consolidation
            ]
        else:
            records_for_sum = [r for r in records if not r.exclude_from_consolidation]

        if not records_for_sum:
            return pd.DataFrame(columns=_empty_columns)

        rows = [
            {
                "sku": r.sku,
                "product_name": r.product_name,
                "store_code": r.store_code,
                "operation_type": r.operation_type,
                "stock_available": r.stock_available,
                "stock_reserved": r.stock_reserved,
                "stock_blocked": r.stock_blocked,
                "updated_at": r.updated_at,
            }
            for r in records_for_sum
        ]

        df = pd.DataFrame(rows)

        agg = df.groupby("sku").agg(
            product_name=("product_name", lambda x: next((v for v in x if v), None)),
            source_count=("store_code", "count"),
            operations_list=("operation_type", lambda x: ", ".join(sorted(set(x)))),
            stock_available_consolidated=("stock_available", "sum"),
            stock_reserved_consolidated=("stock_reserved", "sum"),
            stock_blocked_consolidated=("stock_blocked", "sum"),
            updated_at=("updated_at", "max"),
        ).reset_index()

        # Total consolidado = disponível + bloqueado (reservado é saída pendente, não compõe saldo)
        agg["stock_net_consolidated"] = (
            agg["stock_available_consolidated"] + agg["stock_blocked_consolidated"]
        )

        agg = agg[_empty_columns].sort_values("sku").reset_index(drop=True)
        return agg

    def get_unified_consolidated_dataframe(
        self,
        records: list[InventoryRecord],
        sku_mapping: dict[str, str],
        include_dedup_secondary: bool = False,
    ) -> pd.DataFrame:
        """
        Consolidado com de/para de SKUs aplicado.

        SKUs listados em sku_mapping como 'sku_de' são tratados como 'sku_para'
        antes da agregação, somando seus saldos ao SKU de destino.

        Colunas adicionais em relação ao consolidado padrão:
          skus_origem    — SKUs originais que compõem este total (inclui o próprio sku_para)
          tem_migracao   — True se ao menos um sku_de foi unificado neste registro

        Args:
            records:                 Lista de InventoryRecord (pode ser filtrada).
            sku_mapping:             Dict {sku_de: sku_para} carregado do CSV.
            include_dedup_secondary: Repassa para a mesma regra de dedup do consolidado padrão.

        Returns:
            DataFrame consolidado por SKU unificado.
        """
        _empty_columns = [
            "sku_unificado", "product_name", "skus_origem", "tem_migracao",
            "source_count", "operations_list",
            "stock_net_consolidated", "stock_available_consolidated",
            "stock_blocked_consolidated", "stock_reserved_consolidated",
            "updated_at",
        ]

        if not records:
            return pd.DataFrame(columns=_empty_columns)

        if not include_dedup_secondary:
            records_for_sum = [
                r for r in records
                if not r.is_dedup_secondary and not r.exclude_from_consolidation
            ]
        else:
            records_for_sum = [r for r in records if not r.exclude_from_consolidation]

        if not records_for_sum:
            return pd.DataFrame(columns=_empty_columns)

        rows = []
        for r in records_for_sum:
            sku_unificado = sku_mapping.get(r.sku, r.sku)
            rows.append({
                "sku_unificado": sku_unificado,
                "sku_original": r.sku,
                "product_name": r.product_name,
                "store_code": r.store_code,
                "operation_type": r.operation_type,
                "stock_available": r.stock_available,
                "stock_reserved": r.stock_reserved,
                "stock_blocked": r.stock_blocked,
                "updated_at": r.updated_at,
            })

        df = pd.DataFrame(rows)

        agg = df.groupby("sku_unificado").agg(
            product_name=("product_name", lambda x: next((v for v in x if v), None)),
            skus_origem=("sku_original", lambda x: ", ".join(sorted(set(x)))),
            source_count=("store_code", "count"),
            operations_list=("operation_type", lambda x: ", ".join(sorted(set(x)))),
            stock_available_consolidated=("stock_available", "sum"),
            stock_reserved_consolidated=("stock_reserved", "sum"),
            stock_blocked_consolidated=("stock_blocked", "sum"),
            updated_at=("updated_at", "max"),
        ).reset_index()

        agg["stock_net_consolidated"] = (
            agg["stock_available_consolidated"] + agg["stock_blocked_consolidated"]
        )
        # tem_migracao = True quando o sku_unificado (novo) recebeu ao menos um sku_de diferente dele
        agg["tem_migracao"] = agg.apply(
            lambda row: any(
                s.strip() != row["sku_unificado"]
                for s in row["skus_origem"].split(",")
            ),
            axis=1,
        )

        agg = agg[_empty_columns].sort_values("sku_unificado").reset_index(drop=True)
        return agg

"""
Provider de inventário para a Estoca.

Implementa InventoryProvider usando a API REST da Estoca:
1. get_all_skus(): pagina o endpoint /products para descobrir todos os SKUs
2. get_inventory(): divide os SKUs em batches de 50 e consulta /inventories
3. Mapeia respostas brutas para o modelo canônico InventoryRecord
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.models.inventory import InventoryRecord
from src.models.store import OperationConfig, StoreConfig
from src.providers.base import InventoryProvider
from src.providers.estoca.client import (
    EstocaAuthError,
    EstocaHttpClient,
    EstocaNotFoundError,
)
from src.providers.estoca.schemas import (
    EstocaInventoryItem,
    EstocaInventoryResponse,
    EstocaProductsPage,
)


class EstocaInventoryProvider(InventoryProvider):
    """
    Provider concreto para o WMS Estoca (Brasil).

    Uma única instância pode ser usada para todas as lojas/operações,
    pois cria clientes HTTP individuais (com api_key correto) por chamada.
    """

    def __init__(self, base_url: str = "https://api.estoca.com.br") -> None:
        self.base_url = base_url

    def _get_client(self, api_key: str) -> EstocaHttpClient:
        """Cria um cliente HTTP com a api_key da operação."""
        return EstocaHttpClient(api_key=api_key, base_url=self.base_url)

    def _get_operation(self, store_config: StoreConfig, operation_index: int) -> OperationConfig:
        """Retorna a OperationConfig com validação de índice."""
        try:
            return store_config.operations[operation_index]
        except IndexError:
            raise ValueError(
                f"operation_index={operation_index} inválido para "
                f"store {store_config.store_code} "
                f"({len(store_config.operations)} operações disponíveis)"
            )

    # ─── SKU Discovery ────────────────────────────────────────────────────────

    def get_all_skus(self, store_config: StoreConfig, operation_index: int) -> list[str]:
        """
        Pagina o endpoint /products para descobrir todos os SKUs da operação.

        Args:
            store_config:    Configuração da loja.
            operation_index: Índice da operação.

        Returns:
            Lista de SKUs únicos. Lista vazia se nenhum produto for encontrado
            ou em caso de erro de autenticação/não-encontrado.
        """
        operation = self._get_operation(store_config, operation_index)
        client = self._get_client(operation.api_key)
        label = f"{store_config.store_code}/{operation.operation_type}"

        logger.info(f"[{label}] Iniciando discovery de SKUs via /products...")

        all_skus: list[str] = []
        page = 1
        total_pages: Optional[int] = None

        try:
            while True:
                raw = client.get_products_page(page=page, per_page=100)
                parsed = EstocaProductsPage.model_validate(raw)

                page_skus = [p.sku for p in parsed.data if p.sku]
                all_skus.extend(page_skus)

                # Descobre total de páginas na primeira resposta
                if total_pages is None:
                    total_pages = parsed.get_total_pages()
                    if total_pages:
                        logger.debug(
                            f"[{label}] Total de páginas: {total_pages} "
                            f"| SKUs na pág 1: {len(page_skus)}"
                        )

                # Condições de parada
                if not page_skus:
                    logger.debug(f"[{label}] Página {page} vazia. Encerrando paginação.")
                    break

                if total_pages is not None and page >= total_pages:
                    break

                page += 1

        except EstocaAuthError as exc:
            logger.error(f"[{label}] Falha de autenticação em /products: {exc}")
            return []
        except EstocaNotFoundError as exc:
            logger.warning(f"[{label}] /products retornou 404: {exc}")
            return []
        except Exception as exc:
            logger.error(f"[{label}] Erro inesperado em /products: {exc}")
            return []

        # Deduplica preservando ordem
        seen: set[str] = set()
        unique_skus = [s for s in all_skus if not (s in seen or seen.add(s))]  # type: ignore[func-returns-value]

        logger.info(f"[{label}] {len(unique_skus)} SKUs descobertos.")
        return unique_skus

    # ─── Inventory Fetch ──────────────────────────────────────────────────────

    def get_inventory(
        self,
        store_config: StoreConfig,
        operation_index: int,
        skus: list[str],
    ) -> list[InventoryRecord]:
        """
        Busca saldos de inventário para uma lista de SKUs.

        Divide automaticamente em batches de 50 (limite da API Estoca).

        Args:
            store_config:    Configuração da loja.
            operation_index: Índice da operação.
            skus:            Lista de SKUs a consultar.

        Returns:
            Lista de InventoryRecord canônicos.
        """
        if not skus:
            return []

        operation = self._get_operation(store_config, operation_index)
        client = self._get_client(operation.api_key)
        label = f"{store_config.store_code}/{operation.operation_type}"
        batch_size = EstocaHttpClient.INVENTORY_BATCH_SIZE

        # Divide em batches
        batches = [skus[i : i + batch_size] for i in range(0, len(skus), batch_size)]
        logger.info(
            f"[{label}] Consultando {len(skus)} SKUs em {len(batches)} batch(es) "
            f"de até {batch_size} SKUs..."
        )

        all_records: list[InventoryRecord] = []
        fetched_at = datetime.now(tz=timezone.utc)

        for batch_idx, batch in enumerate(batches, start=1):
            logger.debug(
                f"[{label}] Batch {batch_idx}/{len(batches)} — {len(batch)} SKUs"
            )
            try:
                raw = client.get_inventory_batch(
                    warehouse_id=store_config.warehouse_id,
                    skus=batch,
                )
                parsed = EstocaInventoryResponse.model_validate(raw)

                for item in parsed.data:
                    record = self._map_to_canonical(
                        item=item,
                        store_config=store_config,
                        operation=operation,
                        fetched_at=fetched_at,
                    )
                    all_records.append(record)

            except EstocaAuthError as exc:
                logger.error(f"[{label}] Autenticação falhou em batch {batch_idx}: {exc}")
                raise  # propaga para o service coletar o erro

            except EstocaNotFoundError as exc:
                logger.warning(
                    f"[{label}] Warehouse ou SKU não encontrado em batch {batch_idx}: {exc}. "
                    "Batch ignorado."
                )
                continue  # continua os outros batches

            except Exception as exc:
                logger.error(
                    f"[{label}] Erro em batch {batch_idx}/{len(batches)}: {exc}. "
                    "Batch ignorado."
                )
                continue

        logger.info(f"[{label}] {len(all_records)} registros de inventário obtidos.")
        return all_records

    # ─── Mapeamento para Modelo Canônico ──────────────────────────────────────

    def _map_to_canonical(
        self,
        item: EstocaInventoryItem,
        store_config: StoreConfig,
        operation: OperationConfig,
        fetched_at: datetime,
    ) -> InventoryRecord:
        """
        Mapeia um EstocaInventoryItem para o modelo canônico InventoryRecord.

        Mapeamento de campos:
          in_stock  → stock_total
          available → stock_available
          holded    → stock_reserved
          blocked   → stock_blocked
        """
        return InventoryRecord(
            source_system=store_config.source_system,
            country=store_config.country,
            business_unit=store_config.business_unit,
            store_code=store_config.store_code,
            operation_type=operation.operation_type,
            estoca_store_id=operation.store_id,
            estoca_warehouse_id=store_config.warehouse_id,
            sku=item.product_sku,
            product_name=item.product_name,
            stock_total=item.in_stock,
            stock_available=item.available,
            stock_reserved=item.holded,
            stock_blocked=item.blocked,
            updated_at=fetched_at,
            exclude_from_consolidation=store_config.exclude_from_consolidation,
        )

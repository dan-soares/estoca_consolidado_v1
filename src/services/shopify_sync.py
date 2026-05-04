"""
Sincronização de saldos consolidados com o inventário da Shopify.

Fluxo:
1. Extrai {sku: stock_available_consolidated} do DataFrame consolidado
2. Busca inventory_item_id na Shopify para cada SKU (batch GraphQL)
3. Envia atualizações em lotes de 100 via inventorySetQuantities
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from src.providers.shopify.client import ShopifyClient


@dataclass
class ShopifySyncResult:
    synced_count: int
    skus_not_found: list[str]    # SKUs sem inventory_item_id na Shopify
    failed_skus: list[str]       # SKUs com erro durante o push
    synced_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


def sync_consolidated_to_shopify(
    consolidated_df: pd.DataFrame,
    client: ShopifyClient,
    location_id: str,
    active_only: bool = True,
) -> ShopifySyncResult:
    """
    Sincroniza stock_available_consolidated → Shopify inventory (available).

    Args:
        consolidated_df: DataFrame com colunas "sku" e "stock_available_consolidated".
                         Aceita tanto o output de get_consolidated_dataframe() quanto
                         o unified renomeado (sku_unificado → sku).
        client:          ShopifyClient configurado com store_domain e access_token.
        location_id:     GID da localização Shopify (ex: "gid://shopify/Location/123").
        active_only:     Se True (padrão), sincroniza apenas SKUs de produtos ativos.
                         Se False, tenta sincronizar todos os SKUs do DataFrame,
                         incluindo variantes de produtos em rascunho ou arquivados.

    Returns:
        ShopifySyncResult com contagens e listas de SKUs com problema.
    """
    if consolidated_df.empty:
        return ShopifySyncResult(synced_count=0, skus_not_found=[], failed_skus=[])

    sku_qty: dict[str, int] = (
        consolidated_df.set_index("sku")["stock_available_consolidated"]
        .astype(int)
        .to_dict()
    )
    skus = list(sku_qty.keys())
    logger.info(
        f"Shopify sync: {len(skus)} SKUs para processar "
        f"({'apenas ativos' if active_only else 'todos — incluindo inativos'})."
    )

    # ── Lookup inventory_item_id ─────────────────────────────────────────────
    if active_only:
        logger.info("Buscando variantes ativas na Shopify (status:active)...")
        all_active = client.get_active_variants()
        sku_to_item_id = {s: all_active[s] for s in skus if s in all_active}
    else:
        logger.info("Buscando inventory_item_id na Shopify (todos os status)...")
        sku_to_item_id = client.batch_get_inventory_item_ids(skus)

    skus_not_found = [s for s in skus if s not in sku_to_item_id]
    if skus_not_found:
        logger.warning(
            f"{len(skus_not_found)} SKUs não encontrados nos produtos "
            f"{'ativos ' if active_only else ''}da Shopify "
            f"(primeiros: {skus_not_found[:5]})"
        )

    # ── Prepara payload ──────────────────────────────────────────────────────
    items_to_update = [
        {"inventory_item_id": sku_to_item_id[s], "quantity": sku_qty[s]}
        for s in skus
        if s in sku_to_item_id
    ]
    logger.info(
        f"Enviando {len(items_to_update)} atualização(ões) para Shopify "
        f"em lotes de 100..."
    )

    # Mapa inverso para recuperar SKU a partir do inventory_item_id nos erros
    item_id_to_sku = {v: k for k, v in sku_to_item_id.items()}

    synced_count = 0
    failed_skus: list[str] = []
    batch_size = 100

    for i in range(0, len(items_to_update), batch_size):
        batch = items_to_update[i : i + batch_size]
        batch_num = i // batch_size + 1
        try:
            resp = client.set_inventory_quantities(batch, location_id)
            user_errors = (
                resp.get("data", {})
                .get("inventorySetQuantities", {})
                .get("userErrors", [])
            )
            if user_errors:
                for err in user_errors:
                    logger.error(f"Shopify userError: {err}")
                failed_skus.extend(
                    item_id_to_sku.get(item["inventory_item_id"], "?")
                    for item in batch
                )
            else:
                synced_count += len(batch)
                logger.info(
                    f"Lote {batch_num}: {len(batch)} SKUs sincronizados com sucesso."
                )
        except Exception as exc:
            logger.error(f"Erro ao sincronizar lote {batch_num}: {exc}")
            failed_skus.extend(
                item_id_to_sku.get(item["inventory_item_id"], "?")
                for item in batch
            )

    logger.info(
        f"Sync concluído: {synced_count} sincronizados, "
        f"{len(skus_not_found)} não encontrados, {len(failed_skus)} com falha."
    )
    return ShopifySyncResult(
        synced_count=synced_count,
        skus_not_found=skus_not_found,
        failed_skus=failed_skus,
    )

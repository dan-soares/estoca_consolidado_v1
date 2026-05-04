"""
Cliente HTTP para a API Shopify Admin (GraphQL).

Responsabilidades:
- Lookup de inventory_item_id por SKU via GraphQL
- Atualização de quantidades via inventorySetQuantities mutation
"""

import time

import requests
from loguru import logger


class ShopifyAuthError(Exception):
    pass


class ShopifyAPIError(Exception):
    pass


class ShopifyClient:
    """
    Cliente para a Shopify Admin API.

    Usa GraphQL para lookup de variantes por SKU e para atualização
    em batch de quantidades de inventário.

    Args:
        store_domain: Ex: "minha-loja.myshopify.com"
        access_token: Token de acesso com scope write_inventory
    """

    _API_VERSION = "2024-10"

    def __init__(self, store_domain: str, access_token: str) -> None:
        domain = store_domain.strip().rstrip("/")
        self._graphql_url = (
            f"https://{domain}/admin/api/{self._API_VERSION}/graphql.json"
        )
        self._headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

    # ─── GraphQL transport ───────────────────────────────────────────────────

    def _post(self, query: str, variables: dict) -> dict:
        resp = requests.post(
            self._graphql_url,
            headers=self._headers,
            json={"query": query, "variables": variables},
            timeout=30,
        )
        if resp.status_code == 401:
            raise ShopifyAuthError(
                "Token inválido ou sem permissão de escrita de inventário."
            )
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "2"))
            logger.warning(f"Shopify rate limit — aguardando {retry_after}s")
            time.sleep(retry_after)
            return self._post(query, variables)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise ShopifyAPIError(f"GraphQL errors: {data['errors']}")
        return data

    # ─── Lookup ──────────────────────────────────────────────────────────────

    _ACTIVE_VARIANTS_QUERY = """
    query GetActiveVariants($cursor: String) {
      products(first: 50, after: $cursor, query: "status:active") {
        nodes {
          variants(first: 100) {
            nodes {
              sku
              inventoryItem { id }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """

    def get_active_variants(self) -> dict[str, str]:
        """
        Retorna {sku: inventory_item_id_gid} para todos os produtos ATIVOS na Shopify.

        Pagina automaticamente por todos os produtos com status:active.
        SKUs sem inventoryItem ou com sku vazio são ignorados.
        """
        result: dict[str, str] = {}
        cursor = None
        page = 0

        while True:
            page += 1
            data = self._post(self._ACTIVE_VARIANTS_QUERY, {"cursor": cursor})
            products_data = data.get("data", {}).get("products", {})

            for product in products_data.get("nodes", []):
                for variant in product.get("variants", {}).get("nodes", []):
                    sku = variant.get("sku")
                    item_id = variant.get("inventoryItem", {}).get("id")
                    if sku and item_id:
                        result[sku] = item_id

            page_info = products_data.get("pageInfo", {})
            logger.debug(f"Shopify active variants — página {page}: {len(result)} variantes acumuladas.")

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        logger.info(f"Shopify active variants: {len(result)} SKUs ativos encontrados.")
        return result

    _LOOKUP_QUERY = """
    query lookupVariants($q: String!) {
      productVariants(first: 100, query: $q) {
        nodes {
          sku
          inventoryItem {
            id
          }
        }
      }
    }
    """

    def batch_get_inventory_item_ids(self, skus: list[str]) -> dict[str, str]:
        """
        Retorna {sku: inventory_item_id_gid} para os SKUs encontrados na Shopify.

        Faz lookup em batches de 50 SKUs por query GraphQL.
        SKUs não encontrados são omitidos do resultado.
        """
        result: dict[str, str] = {}
        batch_size = 50
        for i in range(0, len(skus), batch_size):
            batch = skus[i : i + batch_size]
            q = " OR ".join(f"sku:{s}" for s in batch)
            data = self._post(self._LOOKUP_QUERY, {"q": q})
            nodes = (
                data.get("data", {})
                .get("productVariants", {})
                .get("nodes", [])
            )
            for node in nodes:
                sku = node.get("sku")
                item_id = node.get("inventoryItem", {}).get("id")
                if sku and item_id:
                    result[sku] = item_id
            logger.debug(
                f"Shopify lookup lote {i // batch_size + 1}: "
                f"{len(nodes)} variante(s) encontrada(s)."
            )
        return result

    # ─── Inventory update ────────────────────────────────────────────────────

    _SET_MUTATION = """
    mutation setQuantities($input: InventorySetQuantitiesInput!) {
      inventorySetQuantities(input: $input) {
        inventoryAdjustmentGroup {
          reason
          changes {
            name
            delta
            quantityAfterChange
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """

    def set_inventory_quantities(
        self,
        items: list[dict],
        location_id: str,
        reason: str = "correction",
    ) -> dict:
        """
        Define quantidades absolutas de inventário (available).

        Args:
            items:       [{"inventory_item_id": "gid://...", "quantity": int}]
            location_id: GID da localização Shopify
            reason:      Motivo para o audit trail da Shopify

        Returns:
            Resposta GraphQL completa (inclui userErrors se houver).
        """
        quantities = [
            {
                "inventoryItemId": item["inventory_item_id"],
                "locationId": location_id,
                "quantity": item["quantity"],
            }
            for item in items
        ]
        variables = {
            "input": {
                "name": "available",
                "reason": reason,
                "ignoreCompareQuantity": True,
                "quantities": quantities,
            }
        }
        return self._post(self._SET_MUTATION, variables)

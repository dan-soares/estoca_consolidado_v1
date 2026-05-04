"""
Diagnostico da API 0103 - por que /inventories retorna 0?

Execute a partir da raiz do projeto:
    python scripts/debug_0103.py
"""

import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests
from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")

SKU_TESTE = "BR01PM000100"
BASE_URL = os.getenv("ESTOCA_BASE_URL", "https://api.estoca.com.br").rstrip("/") + "/ollie"

# IDs do stores.yaml
WAREHOUSE_0103 = "699dfe96-e547-4fff-aba5-c4e0805fc3f6"
WAREHOUSE_0102 = "e2a5f9b6-af20-4009-8984-726a2be546ea"

API_KEYS = {
    "0103/B2B": os.getenv("ESTOCA_0103_B2B_API_KEY", ""),
    "0103/B2C": os.getenv("ESTOCA_0103_B2C_API_KEY", ""),
    "0103/MKT": os.getenv("ESTOCA_0103_MKT_API_KEY", ""),
    "0102/B2B": os.getenv("ESTOCA_0102_B2B_API_KEY", ""),
}


def get(api_key: str, path: str, params: dict = None) -> tuple:
    headers = {"X-Api-Key": api_key, "X-Api-Version": "v1", "Accept": "application/json"}
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text[:400]}
    except Exception as e:
        return 0, {"error": str(e)}


def inv_item(body: dict, label: str) -> str:
    data = body.get("data")
    if data is None:
        msg = body.get("status", body.get("raw", json.dumps(body, ensure_ascii=True)[:100]))
        return f"  {label}: ERRO -> {msg}"
    if isinstance(data, dict):
        data = [data]
    if not data:
        return f"  {label}: lista vazia"
    item = data[0]
    return (
        f"  {label}: "
        f"in_stock={item.get('in_stock',0)}  "
        f"available={item.get('available',0)}  "
        f"holded={item.get('holded',0)}  "
        f"blocked={item.get('blocked',0)}"
    )


print(f"\nSKU: {SKU_TESTE} | Base URL: {BASE_URL}\n")

# ── Bloco 1: cada credencial 0103 consultada contra os 2 warehouses ───────────
print("="*70)
print("BLOCO 1 - Credenciais 0103 vs warehouse configurado vs warehouse 0102")
print("="*70)

for op, key in API_KEYS.items():
    if not key:
        print(f"\n[{op}] api_key nao encontrada no .env")
        continue
    print(f"\n[{op}]")
    st, body = get(key, "inventories", {"warehouse": WAREHOUSE_0103, "sku": SKU_TESTE})
    print(f"  HTTP {st} | warehouse_0103 | " + inv_item(body, ""))
    st, body = get(key, "inventories", {"warehouse": WAREHOUSE_0102, "sku": SKU_TESTE})
    print(f"  HTTP {st} | warehouse_0102 | " + inv_item(body, ""))

# ── Bloco 2: /products da 0103/B2B - pega 3 SKUs do catalogo proprio ──────────
print(f"\n{'='*70}")
print("BLOCO 2 - /products da 0103/B2B: primeiros 5 SKUs do catalogo proprio")
print("="*70)

key_b2b = API_KEYS.get("0103/B2B", "")
if key_b2b:
    st, body = get(key_b2b, "products", {"page": 1, "per_page": 5})
    print(f"HTTP {st}")
    products_data = body.get("data", [])
    catalog_skus = []
    if isinstance(products_data, list):
        for p in products_data[:5]:
            sku = p.get("sku", "?")
            catalog_skus.append(sku)
            print(f"  SKU do catalogo: {sku}")
    if not products_data:
        print("  -> catalogo vazio ou endpoint retornou erro")
        print(f"  -> raw: {json.dumps(body, ensure_ascii=True)[:200]}")

    # Consulta inventario para esses SKUs com warehouse_0103
    if catalog_skus:
        print(f"\n  Consultando inventario para esses SKUs (warehouse_0103):")
        for sku in catalog_skus[:3]:
            st, body = get(key_b2b, "inventories", {"warehouse": WAREHOUSE_0103, "sku": sku})
            print(f"  " + inv_item(body, f"SKU={sku}  HTTP {st}"))

# ── Bloco 3: resumo ────────────────────────────────────────────────────────────
print(f"\n{'='*70}")
print("RESUMO - O QUE ESPERAR:")
print("  Se todos os SKUs do catalogo retornam 0 -> warehouse_id errado para 0103")
print("  Se SKUs proprios retornam valores mas BR01PM000100=0 -> SKU nao esta neste warehouse")
print("  Se warehouse_0102 retorna dados com a key 0103 -> credencial com escopo cruzado")
print(f"{'='*70}\n")

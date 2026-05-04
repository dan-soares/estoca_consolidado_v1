"""
Persistência do SKU Registry em config/sku_registry.json.

O registry é a lista acumulada de todos os SKUs já vistos em qualquer
operação ou warehouse. Ele serve como semente do pool global em cada fetch,
garantindo que SKUs conhecidos nunca sejam omitidos — mesmo que saiam
temporariamente de algum catálogo /products.

O arquivo cresce de forma monotônica: nunca perde SKUs automaticamente.
Remoção manual pode ser feita diretamente no JSON quando necessário.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


def _find_registry_path() -> Path:
    """
    Localiza ou resolve o caminho para config/sku_registry.json.

    Usa a mesma estratégia de busca dos demais módulos de configuração.
    Retorna o caminho canônico mesmo se o arquivo ainda não existir.
    """
    candidates = [
        Path("config/sku_registry.json"),
        Path("../config/sku_registry.json"),
        Path(__file__).parent.parent.parent / "config" / "sku_registry.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    # Arquivo ainda não existe — retorna o caminho canônico para criação
    return Path(__file__).parent.parent.parent / "config" / "sku_registry.json"


def load_registry() -> set[str]:
    """
    Carrega o SKU registry do JSON.

    Returns:
        Set de SKUs conhecidos. Set vazio se o arquivo não existir.
    """
    path = _find_registry_path()
    if not path.exists():
        logger.info("SKU registry não encontrado — iniciando com pool vazio.")
        return set()

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        skus = set(data.get("skus", []))
        logger.info(f"SKU registry carregado: {len(skus)} SKUs de '{path.name}'.")
        return skus
    except Exception as exc:
        logger.warning(f"Falha ao carregar SKU registry ({path}): {exc}. Usando pool vazio.")
        return set()


def save_registry(skus: set[str]) -> None:
    """
    Salva o SKU registry em config/sku_registry.json.

    A persistência é best-effort: erros são logados mas não propagados
    para não interromper o fluxo do fetch.

    Args:
        skus: Set completo de SKUs a persistir.
    """
    path = _find_registry_path()
    payload = {
        "updated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(skus),
        "skus": sorted(skus),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"SKU registry salvo: {len(skus)} SKUs em '{path.name}'.")
    except Exception as exc:
        logger.error(f"Falha ao salvar SKU registry ({path}): {exc}.")

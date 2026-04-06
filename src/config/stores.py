"""
Carregamento e validação da configuração de lojas a partir de config/stores.yaml.

Responsabilidades:
1. Ler config/stores.yaml
2. Para cada operação, resolver a API key a partir de os.environ[env_key]
3. Validar a estrutura com os modelos Pydantic
4. Retornar lista de StoreConfig prontos para uso

Separação de responsabilidades:
- stores.yaml contém APENAS dados estruturais (IDs, mapeamentos) — pode ser commitado
- .env contém APENAS segredos (api_keys) — NUNCA deve ser commitado
"""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Carrega o .env no os.environ antes de qualquer leitura de variável
load_dotenv(override=False)

from src.models.store import OperationConfig, StoreConfig


class ConfigurationError(Exception):
    """Erro de configuração — variável de ambiente ausente ou YAML inválido."""
    pass


def _find_stores_yaml() -> Path:
    """
    Localiza o arquivo config/stores.yaml, buscando a partir do diretório
    de trabalho atual e até 3 níveis acima (para flexibilidade de execução).
    """
    candidates = [
        Path("config/stores.yaml"),
        Path("../config/stores.yaml"),
        Path(__file__).parent.parent.parent / "config" / "stores.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise ConfigurationError(
        "Arquivo config/stores.yaml não encontrado. "
        "Execute a aplicação a partir do diretório raiz do projeto."
    )


def load_stores() -> list[StoreConfig]:
    """
    Carrega e valida a configuração completa de lojas.

    Processo:
    1. Lê config/stores.yaml
    2. Para cada operação, busca a api_key em os.environ[env_key]
    3. Valida a estrutura com Pydantic
    4. Retorna lista de StoreConfig

    Raises:
        ConfigurationError: Se stores.yaml não for encontrado, se o YAML for inválido
                            ou se alguma variável de ambiente estiver faltando.
    """
    stores_path = _find_stores_yaml()

    try:
        with open(stores_path, encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Erro ao parsear {stores_path}: {exc}") from exc

    if "estoca" not in raw:
        raise ConfigurationError(f"Chave 'estoca' não encontrada em {stores_path}")

    estoca_config = raw["estoca"]
    source_system: str = estoca_config.get("source_system", "ESTOCA")
    country: str = estoca_config.get("country", "BR")
    raw_stores: list[dict] = estoca_config.get("stores", [])

    # Coleta todas as variáveis ausentes antes de lançar exceção (melhor UX)
    missing_vars: list[str] = []
    stores: list[StoreConfig] = []

    for store_raw in raw_stores:
        operations: list[OperationConfig] = []

        for op_raw in store_raw.get("operations", []):
            env_key: str = op_raw["env_key"]
            api_key: str = os.environ.get(env_key, "")

            if not api_key:
                missing_vars.append(env_key)
                api_key = ""  # continua para coletar todos os erros

            operations.append(
                OperationConfig(
                    operation_type=op_raw["operation_type"],
                    store_id=op_raw["store_id"],
                    env_key=env_key,
                    api_key=api_key,
                    dedup_group=op_raw.get("dedup_group"),
                )
            )

        stores.append(
            StoreConfig(
                store_code=store_raw["store_code"],
                business_unit=store_raw["business_unit"],
                warehouse_id=store_raw["warehouse_id"],
                country=country,
                source_system=source_system,
                operations=operations,
                exclude_from_consolidation=store_raw.get("exclude_from_consolidation", False),
            )
        )

    if missing_vars:
        raise ConfigurationError(
            "As seguintes variáveis de ambiente estão ausentes no arquivo .env:\n"
            + "\n".join(f"  - {v}" for v in missing_vars)
            + "\n\nCopie .env.example para .env e preencha as credenciais."
        )

    return stores

"""
Configurações globais da aplicação carregadas do arquivo .env.

Usa pydantic-settings para leitura e validação automática das variáveis
de ambiente. Apenas configurações globais ficam aqui — as API keys
por operação são injetadas em src/config/stores.py.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GlobalSettings(BaseSettings):
    """Configurações globais lidas do .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # ignora variáveis extras no .env (ex: as api_keys por operação)
    )

    # Estoca
    estoca_base_url: str = Field(
        default="https://api.estoca.com.br",
        validation_alias="ESTOCA_BASE_URL",
        description="URL base da API Estoca",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Nível de log: DEBUG, INFO, WARNING, ERROR",
    )


@lru_cache(maxsize=1)
def get_settings() -> GlobalSettings:
    """
    Retorna instância singleton das configurações globais.

    O cache (lru_cache) garante que o .env é lido apenas uma vez
    durante o ciclo de vida da aplicação.
    """
    return GlobalSettings()

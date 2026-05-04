"""
Configurações globais da aplicação carregadas do arquivo .env.

Usa pydantic-settings para leitura e validação automática das variáveis
de ambiente. Apenas configurações globais ficam aqui — as API keys
por operação são injetadas em src/config/stores.py.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, computed_field
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

    # Shopify (opcional — sync desabilitado se não configurado)
    shopify_store_domain: Optional[str] = Field(
        default=None,
        validation_alias="SHOPIFY_STORE_DOMAIN",
        description="Ex: minha-loja.myshopify.com",
    )
    shopify_access_token: Optional[str] = Field(
        default=None,
        validation_alias="SHOPIFY_ACCESS_TOKEN",
        description="Token de acesso com scope write_inventory",
    )
    shopify_location_id: Optional[str] = Field(
        default=None,
        validation_alias="SHOPIFY_LOCATION_ID",
        description="GID da localização: gid://shopify/Location/123456",
    )

    @computed_field
    @property
    def shopify_enabled(self) -> bool:
        return bool(
            self.shopify_store_domain
            and self.shopify_access_token
            and self.shopify_location_id
        )


@lru_cache(maxsize=1)
def get_settings() -> GlobalSettings:
    """
    Retorna instância singleton das configurações globais.

    O cache (lru_cache) garante que o .env é lido apenas uma vez
    durante o ciclo de vida da aplicação.
    """
    return GlobalSettings()

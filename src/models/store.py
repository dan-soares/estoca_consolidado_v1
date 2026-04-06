"""
Modelos de configuração de lojas e operações.

StoreConfig e OperationConfig representam a estrutura carregada de
config/stores.yaml após injeção das API keys do .env.
"""

from typing import Optional

from pydantic import BaseModel, Field


class OperationConfig(BaseModel):
    """Configuração de uma operação (B2B, B2C, MKT, CROSS) dentro de uma loja."""

    operation_type: str = Field(description="Tipo da operação: B2B, B2C, MKT, CROSS")
    store_id: str = Field(description="UUID do store na Estoca (não é segredo)")
    env_key: str = Field(description="Nome da variável de ambiente que contém a api_key")
    api_key: str = Field(default="", description="API key injetada em runtime do .env")
    dedup_group: Optional[str] = Field(
        default=None,
        description="Identificador de deduplicação. Operações com mesmo grupo "
                    "compartilham credenciais idênticas e o mesmo estoque físico.",
    )


class StoreConfig(BaseModel):
    """Configuração de uma loja (store_code) com seu warehouse e operações."""

    store_code: str = Field(description="Código interno da loja, ex: 0101")
    business_unit: str = Field(description="Nome legível da unidade de negócio")
    warehouse_id: str = Field(description="UUID do warehouse na Estoca")
    country: str = Field(description="País do warehouse")
    source_system: str = Field(description="Sistema WMS de origem")
    operations: list[OperationConfig] = Field(description="Lista de operações configuradas")
    exclude_from_consolidation: bool = Field(
        default=False,
        description="Se True, os registros desta loja aparecem na visão detalhada "
                    "mas são excluídos da soma no consolidado. Usado para lojas de "
                    "avarias, devoluções e outras operações auxiliares.",
    )

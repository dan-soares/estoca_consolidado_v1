"""
Modelo canônico de inventário.

Este modelo é o contrato central da aplicação. Todos os providers (Estoca,
futuros WMS internacionais) devem mapear suas respostas brutas para este
modelo, garantindo uma interface uniforme na camada de serviços e dashboard.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InventoryRecord(BaseModel):
    """
    Registro canônico de saldo de estoque.

    Campos de saldo mapeados da API Estoca:
      stock_total     ← in_stock  (estoque físico total no armazém)
      stock_available ← available (disponível para alocação em novos pedidos)
      stock_reserved  ← holded    (alocado em pedidos existentes, ainda não expedido)
      stock_blocked   ← blocked   (bloqueado por divergência, avaria ou ajuste)
    """

    # Identificação da origem
    source_system: str = Field(description="Sistema WMS de origem, ex: ESTOCA, SAP, MAGENTO")
    country: str = Field(description="País do warehouse, ex: BR, AR, MX")
    business_unit: str = Field(description="Nome da unidade de negócio, ex: LOJA 0101")

    # Identificação da operação
    store_code: str = Field(description="Código interno da loja, ex: 0101")
    operation_type: str = Field(description="Tipo de operação: B2B, B2C, MKT, CROSS")

    # Identificadores Estoca (preenchidos apenas para source_system=ESTOCA)
    estoca_store_id: Optional[str] = Field(default=None, description="UUID do store na Estoca")
    estoca_warehouse_id: Optional[str] = Field(default=None, description="UUID do warehouse na Estoca")

    # Produto
    sku: str = Field(description="SKU do produto")
    product_name: Optional[str] = Field(default=None, description="Descrição/nome do produto")

    # Saldos
    stock_total: int = Field(default=0, description="Estoque físico total (in_stock)")
    stock_available: int = Field(default=0, description="Disponível para novos pedidos (available)")
    stock_reserved: int = Field(default=0, description="Reservado em pedidos em andamento (holded)")
    stock_blocked: int = Field(default=0, description="Bloqueado/indisponível (blocked)")

    # Controle
    updated_at: datetime = Field(description="Momento da consulta à API")

    # Flags internas de controle (não expostas no dashboard / exportações)
    is_dedup_secondary: bool = Field(
        default=False,
        description="True quando este registro é cópia de outro no mesmo dedup_group. "
                    "Excluído da soma no consolidado para evitar double-count.",
        exclude=True,
    )
    exclude_from_consolidation: bool = Field(
        default=False,
        description="True para lojas auxiliares (avarias, devoluções). "
                    "Aparece na visão detalhada mas não entra no consolidado nacional.",
        exclude=True,
    )

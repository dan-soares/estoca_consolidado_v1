"""
Schemas Pydantic para respostas brutas da API Estoca.

Estes modelos representam a estrutura REAL retornada pela API, antes
do mapeamento para o modelo canônico InventoryRecord.

Notas sobre a API Estoca:
- Campo SKU na resposta de inventário: "product_sku" (não "sku")
- Campo SKU na resposta de produtos: "sku"
- Resposta de inventário para SKU único: data é dict (não list)
- Resposta de inventário para múltiplos SKUs: data é list
- Saldos podem ser negativos em casos de ajuste/divergência

Referência: https://developers.estoca.com.br/api-docs/v1
"""

from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


class EstocaInventoryItem(BaseModel):
    """Um item de saldo retornado pelo endpoint GET /inventories."""

    product_id: Optional[str] = None
    product_sku: str = Field(alias="product_sku")
    product_name: Optional[str] = None
    in_stock: int = 0
    available: int = 0
    holded: int = 0
    blocked: int = 0

    model_config = {"populate_by_name": True}

    @field_validator("in_stock", "available", "holded", "blocked", mode="before")
    @classmethod
    def coerce_to_int(cls, v: Any) -> int:
        """Garante que valores nulos ou None sejam tratados como 0."""
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0


class EstocaInventoryResponse(BaseModel):
    """
    Resposta do endpoint GET /inventories.

    A API retorna data como dict (SKU único) ou list (múltiplos SKUs).
    O field_validator normaliza ambos para list.
    """

    status: Optional[str] = None
    data: list[EstocaInventoryItem] = Field(default_factory=list)

    @field_validator("data", mode="before")
    @classmethod
    def normalize_data(cls, v: Any) -> list[dict]:
        """Normaliza data para sempre ser lista, independente do formato da resposta."""
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]  # resposta de SKU único
        if isinstance(v, list):
            return v
        return []


class EstocaProduct(BaseModel):
    """Produto retornado pelo endpoint GET /products."""

    sku: Optional[str] = None
    # Outros campos existem (id, name, barcode, etc.) mas não são necessários aqui
    model_config = {"extra": "ignore"}


class EstocaProductsPage(BaseModel):
    """
    Uma página de resposta do endpoint GET /products.

    Nota: a estrutura de paginação da Estoca usa campos como
    "page", "per_page", "total" na raiz ou em um objeto "pagination".
    Esta classe tenta cobrir ambos os formatos.
    """

    status: Optional[str] = None
    data: list[EstocaProduct] = Field(default_factory=list)

    # Campos de paginação — podem estar na raiz ou aninhados
    page: Optional[int] = None
    per_page: Optional[int] = None
    total: Optional[int] = None
    total_pages: Optional[int] = None

    model_config = {"extra": "ignore"}

    @field_validator("data", mode="before")
    @classmethod
    def normalize_data(cls, v: Any) -> list[dict]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    def get_total_pages(self) -> Optional[int]:
        """Retorna total de páginas, calculando se necessário."""
        if self.total_pages is not None:
            return self.total_pages
        if self.total is not None and self.per_page:
            import math
            return math.ceil(self.total / self.per_page)
        return None

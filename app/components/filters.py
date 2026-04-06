"""
Componente de filtros da sidebar do dashboard.

Renderiza os widgets de filtro no painel lateral do Streamlit e
retorna um FilterState com as seleções do usuário.

Filtros disponíveis:
- SKU (texto livre, busca por substring)
- Loja (multiselect por store_code)
- Operação (multiselect por operation_type: B2B, B2C, MKT, CROSS)
- Warehouse (multiselect por estoca_warehouse_id)
"""

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st


@dataclass
class FilterState:
    """Estado dos filtros aplicados pelo usuário."""

    sku_filter: str = ""
    store_codes: list[str] = field(default_factory=list)
    operation_types: list[str] = field(default_factory=list)
    warehouse_ids: list[str] = field(default_factory=list)
    hide_zero_stock: bool = True

    @property
    def is_empty(self) -> bool:
        """True se nenhum filtro estiver ativo."""
        return (
            not self.sku_filter
            and not self.store_codes
            and not self.operation_types
            and not self.warehouse_ids
            and not self.hide_zero_stock
        )


def render_filters(detailed_df: pd.DataFrame) -> FilterState:
    """
    Renderiza os filtros na sidebar e retorna o FilterState com as seleções.

    Args:
        detailed_df: DataFrame detalhado para extrair valores disponíveis
                     nos multiselects.

    Returns:
        FilterState com os valores selecionados pelo usuário.
    """
    st.sidebar.header("Filtros")

    # ── SKU ────────────────────────────────────────────────────────────────
    sku_filter = st.sidebar.text_input(
        "SKU",
        placeholder="Buscar por SKU...",
        help="Filtra por SKU (busca por substring, não diferencia maiúsculas).",
    ).strip()

    # ── Loja ───────────────────────────────────────────────────────────────
    available_stores = sorted(detailed_df["store_code"].dropna().unique().tolist()) if len(detailed_df) > 0 else []
    store_codes = st.sidebar.multiselect(
        "Loja",
        options=available_stores,
        default=[],
        help="Filtra por código de loja (0101, 0102, 0103).",
    )

    # ── Operação ───────────────────────────────────────────────────────────
    available_ops = sorted(detailed_df["operation_type"].dropna().unique().tolist()) if len(detailed_df) > 0 else []
    operation_types = st.sidebar.multiselect(
        "Operação",
        options=available_ops,
        default=[],
        help="Filtra por tipo de operação: B2B, B2C, MKT, CROSS.",
    )

    # ── Warehouse ──────────────────────────────────────────────────────────
    available_warehouses = (
        sorted(detailed_df["estoca_warehouse_id"].dropna().unique().tolist())
        if len(detailed_df) > 0
        else []
    )
    warehouse_ids = st.sidebar.multiselect(
        "Warehouse ID",
        options=available_warehouses,
        default=[],
        help="Filtra por warehouse UUID da Estoca.",
    )

    # ── Ocultar saldo zerado ───────────────────────────────────────────────
    hide_zero_stock = st.sidebar.checkbox(
        "Ocultar SKUs sem estoque",
        value=True,
        help=(
            "Remove da visualização SKUs com saldo total zerado "
            "(provavelmente descontinuados). Afeta as abas Detalhada, "
            "Consolidada e SKU Unificado."
        ),
    )

    # Separador e info
    st.sidebar.markdown("---")
    if len(detailed_df) > 0:
        st.sidebar.caption(f"{len(detailed_df)} registros no dataset atual.")

    return FilterState(
        sku_filter=sku_filter,
        store_codes=store_codes,
        operation_types=operation_types,
        warehouse_ids=warehouse_ids,
        hide_zero_stock=hide_zero_stock,
    )


def apply_filters(df: pd.DataFrame, filters: FilterState) -> pd.DataFrame:
    """
    Aplica os filtros do FilterState a um DataFrame.

    Args:
        df:      DataFrame a filtrar.
        filters: Estado dos filtros.

    Returns:
        DataFrame filtrado.
    """
    if filters.is_empty:
        return df

    result = df.copy()

    if filters.sku_filter:
        mask = result["sku"].str.contains(
            filters.sku_filter, case=False, na=False, regex=False
        )
        result = result[mask]

    if filters.store_codes:
        result = result[result["store_code"].isin(filters.store_codes)]

    if filters.operation_types:
        result = result[result["operation_type"].isin(filters.operation_types)]

    if filters.warehouse_ids and "estoca_warehouse_id" in result.columns:
        result = result[result["estoca_warehouse_id"].isin(filters.warehouse_ids)]

    if filters.hide_zero_stock:
        stock_cols = [c for c in ("stock_total", "stock_available", "stock_blocked", "stock_reserved") if c in result.columns]
        if stock_cols:
            total = sum(result[c].fillna(0) for c in stock_cols)
            result = result[total != 0]

    return result.reset_index(drop=True)

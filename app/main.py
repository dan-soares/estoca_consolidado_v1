"""
Dashboard de Consolidação de Estoque — Estoca WMS
==================================================

Entry point do Streamlit. Execute com:
    streamlit run app/main.py

Fluxo:
1. Carrega configurações globais (.env) e lojas (stores.yaml)
2. Inicializa o provider Estoca e o serviço de agregação
3. Renderiza sidebar com filtros
4. Botão "Atualizar Dados" dispara fetch_all() e armazena em session_state
5. Filtros são aplicados em memória — não re-disparam chamadas à API
6. Exibe tabelas detalhada e consolidada com opções de exportação
"""

import sys
from pathlib import Path
from typing import cast

# Garante que o diretório raiz do projeto esteja no PYTHONPATH
# independentemente de onde o streamlit é executado
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st

from src.config.settings import get_settings
from src.config.stores import ConfigurationError, load_stores
from src.providers.estoca.provider import EstocaInventoryProvider
from src.services.aggregation import FetchResult, InventoryAggregationService
from src.utils.logging import setup_logging

from src.config.sku_mapping import load_sku_mapping
from src.models.inventory import InventoryRecord

from app.components.export import render_export_buttons
from app.components.filters import FilterState, apply_filters, render_filters
from app.components.tables import (
    render_consolidated_table,
    render_detailed_table,
    render_unified_consolidated_table,
)

# ─── Configuração da Página ───────────────────────────────────────────────────

st.set_page_config(
    page_title="Estoque Estoca — Consolidação",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Inicialização (roda uma vez por sessão) ──────────────────────────────────

@st.cache_resource
def _init_service() -> (
    tuple[InventoryAggregationService, None]
    | tuple[None, str]
):
    """
    Inicializa o serviço de agregação de inventário.

    Usa st.cache_resource para criar a instância apenas uma vez por
    instância do servidor Streamlit.

    Returns:
        (agg_service, None) em caso de sucesso.
        (None, error_message) em caso de falha de configuração.
    """
    setup_logging()

    try:
        settings = get_settings()
        stores = load_stores()
        provider = EstocaInventoryProvider(base_url=settings.estoca_base_url)
        agg_service = InventoryAggregationService(provider=provider, stores=stores)
        return agg_service, None
    except ConfigurationError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"Erro inesperado na inicialização: {exc}"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    st.title("📦 Consolidação de Estoque — Estoca WMS")
    st.caption(
        "Visão consolidada de saldos de inventário de todas as lojas e operações."
    )

    # ── Inicialização dos serviços ─────────────────────────────────────────
    service, config_error = _init_service()

    if config_error:
        st.error("**Erro de Configuração**")
        st.code(config_error, language="text")
        st.info(
            "Verifique se o arquivo `.env` existe e contém todas as variáveis necessárias. "
            "Consulte `.env.example` como referência."
        )
        st.stop()

    assert service is not None

    # ── Session State ──────────────────────────────────────────────────────
    if "fetch_result" not in st.session_state:
        st.session_state["fetch_result"] = None

    # ── Sidebar: Botão de atualização e filtros ────────────────────────────
    with st.sidebar:
        st.header("Controles")
        refresh_clicked = st.button(
            "🔄 Atualizar Dados",
            use_container_width=True,
            type="primary",
            help="Consulta a API Estoca e atualiza todos os saldos.",
        )

        st.markdown("---")

    # ── Fetch de dados ─────────────────────────────────────────────────────
    if refresh_clicked:
        with st.spinner("Consultando a API Estoca... Isso pode levar alguns segundos."):
            fetch_result: FetchResult = service.fetch_all()
            st.session_state["fetch_result"] = fetch_result

        if fetch_result.has_errors:
            st.warning(
                f"Fetch concluído com {len(fetch_result.errors)} erro(s). "
                "Veja detalhes abaixo."
            )
        else:
            st.success(
                f"Dados atualizados com sucesso! "
                f"{fetch_result.total_records} registros obtidos."
            )

    fetch_result: FetchResult | None = st.session_state.get("fetch_result")

    # ── Estado inicial (sem dados) ─────────────────────────────────────────
    if fetch_result is None:
        st.info(
            "Clique em **🔄 Atualizar Dados** na barra lateral para consultar "
            "o estoque da Estoca."
        )
        _render_config_summary(service)
        return

    # ── Banner de erros parciais ───────────────────────────────────────────
    if fetch_result.has_errors:
        with st.expander(
            f"⚠️ {len(fetch_result.errors)} operação(ões) com falha — clique para ver detalhes",
            expanded=False,
        ):
            for err in fetch_result.errors:
                st.error(
                    f"**{err.store_code} / {err.operation_type}** "
                    f"[{err.error_type}]: {err.message}"
                )

    # ── Mapeamento de SKUs (de/para) ───────────────────────────────────────
    sku_mapping = st.session_state.get("sku_mapping")
    if sku_mapping is None:
        try:
            sku_mapping = load_sku_mapping()
        except ValueError as exc:
            st.warning(f"⚠️ Erro ao carregar sku_mapping.csv: {exc}")
            sku_mapping = {}
        st.session_state["sku_mapping"] = sku_mapping

    # ── Constrói DataFrames completos ──────────────────────────────────────
    detailed_df_full = service.get_detailed_dataframe(fetch_result.records)

    # ── Filtros ────────────────────────────────────────────────────────────
    filters: FilterState = render_filters(detailed_df_full)

    # Aplica filtros em memória
    detailed_df = apply_filters(detailed_df_full, filters)

    # Consolidado e Unificado: re-agrega a partir dos registros filtrados
    _fr = cast(FetchResult, fetch_result)
    filtered_records = [r for r in _fr.records if _record_matches_filters(r, filters)]
    consolidated_df = service.get_consolidated_dataframe(filtered_records)
    unified_df = service.get_unified_consolidated_dataframe(filtered_records, sku_mapping)

    # ── Métricas resumidas ─────────────────────────────────────────────────
    _render_metrics(consolidated_df)

    st.markdown("---")

    # ── Tabelas ────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "📋 Detalhada",
        "📊 Consolidada",
        "🔄 Consolidado SKU Unificado",
    ])

    with tab1:
        render_detailed_table(detailed_df)

    with tab2:
        render_consolidated_table(consolidated_df)

    with tab3:
        render_unified_consolidated_table(unified_df, mapping_count=len(sku_mapping))

    st.markdown("---")

    # ── Exportação ─────────────────────────────────────────────────────────
    render_export_buttons(detailed_df, consolidated_df, unified_df)

    # ── Timestamp ──────────────────────────────────────────────────────────
    if fetch_result.fetched_at:
        st.caption(
            f"Última atualização: "
            f"{fetch_result.fetched_at.strftime('%d/%m/%Y %H:%M:%S')} UTC"
        )


def _record_matches_filters(record: InventoryRecord, filters: FilterState) -> bool:
    """Verifica se um InventoryRecord passa pelos filtros ativos."""
    if filters.sku_filter and filters.sku_filter.lower() not in record.sku.lower():
        return False
    if filters.store_codes and record.store_code not in filters.store_codes:
        return False
    if filters.operation_types and record.operation_type not in filters.operation_types:
        return False
    if filters.warehouse_ids and record.estoca_warehouse_id not in filters.warehouse_ids:
        return False
    if filters.hide_zero_stock:
        total = (
            (record.stock_total or 0)
            + (record.stock_available or 0)
            + (record.stock_blocked or 0)
            + (record.stock_reserved or 0)
        )
        if total == 0:
            return False
    return True


def _render_metrics(consolidated_df: pd.DataFrame) -> None:
    """Renderiza cards de métricas resumidas no topo do dashboard."""
    col1, col2, col3, col4, col5 = st.columns(5)

    total_skus = len(consolidated_df)

    def _sum(col: str) -> int:
        return int(consolidated_df[col].sum()) if not consolidated_df.empty else 0

    total_net = _sum("stock_net_consolidated")
    total_disponivel = _sum("stock_available_consolidated")
    total_bloqueado = _sum("stock_blocked_consolidated")
    total_reservado = _sum("stock_reserved_consolidated")

    col1.metric("SKUs Únicos", f"{total_skus:,}")
    col2.metric("Total Consolidado", f"{total_net:,}", help="Disponível + Bloqueado")
    col3.metric("Disponível", f"{total_disponivel:,}")
    col4.metric("Bloqueado", f"{total_bloqueado:,}")
    col5.metric("Reservado ⓘ", f"{total_reservado:,}")
    st.caption(
        "**Reservado:** pallets já alocados a pedidos em processo de expedição — "
        "não compõem o Total Consolidado."
    )


def _render_config_summary(service: InventoryAggregationService) -> None:
    """Renderiza um resumo das lojas e operações configuradas."""
    with st.expander("📋 Configuração Carregada", expanded=True):
        st.markdown("**Lojas e operações configuradas:**")
        for store in service.stores:
            ops = ", ".join(op.operation_type for op in store.operations)
            dedup_ops = [
                op.operation_type
                for op in store.operations
                if op.dedup_group is not None
            ]
            dedup_note = (
                f" _(⚠️ {', '.join(dedup_ops)} compartilham credenciais)_"
                if dedup_ops
                else ""
            )
            st.markdown(
                f"- **{store.business_unit}** ({store.store_code}) — "
                f"Operações: {ops}{dedup_note}"
            )


if __name__ == "__main__":
    main()

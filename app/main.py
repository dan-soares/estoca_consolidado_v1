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
from src.config.sku_registry import load_registry, save_registry
from src.models.inventory import InventoryRecord

from app.components.export import render_export_buttons
from app.components.filters import FilterState, apply_filters, render_filters
from app.components.tables import (
    render_consolidated_table,
    render_detailed_table,
    render_unified_consolidated_table,
)

from src.services.validation import ValidationReport, validate_fetch
from src.services.migration_alerts import MigrationStatus, compute_migration_alerts
from src.providers.shopify.client import ShopifyAuthError, ShopifyClient
from src.services.shopify_sync import ShopifySyncResult, sync_consolidated_to_shopify

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
    if "registry_stats" not in st.session_state:
        st.session_state["registry_stats"] = None
    if "validation_report" not in st.session_state:
        st.session_state["validation_report"] = None
    if "shopify_sync_result" not in st.session_state:
        st.session_state["shopify_sync_result"] = None

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

        registry_stats = st.session_state.get("registry_stats")
        if registry_stats:
            if registry_stats["new_count"] > 0:
                st.info(f"🆕 {registry_stats['new_count']} novos SKUs detectados")
            st.caption(f"Pool: {registry_stats['total']} SKUs conhecidos")

    # ── Fetch de dados ─────────────────────────────────────────────────────
    if refresh_clicked:
        with st.spinner("Consultando a API Estoca... Isso pode levar alguns segundos."):
            registry_skus = load_registry()
            fetch_result: FetchResult = service.fetch_all(seed_skus=registry_skus)
            st.session_state["fetch_result"] = fetch_result

            # Atualiza registry com todos os SKUs encontrados no inventário
            inventory_skus = {r.sku for r in fetch_result.records}
            new_skus = inventory_skus - registry_skus
            save_registry(registry_skus | inventory_skus)
            st.session_state["registry_stats"] = {
                "new_count": len(new_skus),
                "total": len(registry_skus | inventory_skus),
            }
            st.session_state["validation_report"] = validate_fetch(
                fetch_result, registry_skus
            )

        if fetch_result.has_errors:
            st.warning(
                f"Fetch concluído com {len(fetch_result.errors)} aviso(s). "
                "Veja detalhes abaixo."
            )
        else:
            new_count = len(new_skus)
            registry_total = len(registry_skus | inventory_skus)
            new_info = f" | 🆕 {new_count} SKU(s) novo(s)" if new_count > 0 else ""
            st.success(
                f"✅ Dados atualizados! "
                f"{fetch_result.total_records} registros obtidos. "
                f"Pool: {registry_total} SKUs conhecidos{new_info}."
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
        failed_ops = ", ".join(
            f"{e.store_code}/{e.operation_type}" for e in fetch_result.errors
        )
        st.error(
            f"**⚠️ ATENÇÃO — Dados incompletos!** "
            f"{len(fetch_result.errors)} operação(ões) falharam durante o fetch: **{failed_ops}**. "
            "Os saldos exibidos **não refletem o estoque total**. "
            "Evite tomar decisões com base nesses números. Clique em 🔄 Atualizar Dados para tentar novamente."
        )
        with st.expander("Ver detalhes dos erros", expanded=True):
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

    # Para o Unificado, o filtro de SKU é aplicado APÓS a unificação (no sku_unificado
    # e nos skus_origem), para que a busca por qualquer componente mostre o total combinado.
    records_for_unified = [r for r in _fr.records if _record_matches_filters(r, filters, ignore_sku=True)]
    unified_df_full = service.get_unified_consolidated_dataframe(records_for_unified, sku_mapping)
    if filters.sku_filter:
        sku_low = filters.sku_filter.lower()
        mask = (
            unified_df_full["sku_unificado"].str.lower().str.contains(sku_low, na=False)
            | unified_df_full["skus_origem"].str.lower().str.contains(sku_low, na=False)
        )
        unified_df = unified_df_full[mask].reset_index(drop=True)
    else:
        unified_df = unified_df_full

    # ── Sidebar: alertas de migração e Shopify sync ───────────────────────
    # Alertas de migração usam o consolidated SEM filtros do usuário:
    # filtros ativos (ex: busca por SKU) excluiriam o sku_antigo do df
    # e fariam stock_antigo = 0, classificando como "Concluída" erroneamente.
    consolidated_df_all = service.get_consolidated_dataframe(list(_fr.records))

    with st.sidebar:
        if sku_mapping:
            _render_migration_sidebar(consolidated_df_all, sku_mapping)

        settings = get_settings()
        if settings.shopify_enabled:
            _render_shopify_sidebar(
                unified_df=unified_df,
                settings=settings,
            )

    # ── Métricas resumidas ─────────────────────────────────────────────────
    _render_metrics(consolidated_df)

    st.markdown("---")

    # ── Tabelas ────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Detalhada",
        "📊 Consolidada",
        "🔄 Consolidado SKU Unificado",
        "🔍 Validação",
    ])

    with tab1:
        render_detailed_table(detailed_df)

    with tab2:
        render_consolidated_table(consolidated_df)

    with tab3:
        render_unified_consolidated_table(unified_df, mapping_count=len(sku_mapping))

    with tab4:
        _render_validation_tab(st.session_state.get("validation_report"))

    st.markdown("---")

    # ── Exportação ─────────────────────────────────────────────────────────
    render_export_buttons(detailed_df, consolidated_df, unified_df)

    # ── Timestamp ──────────────────────────────────────────────────────────
    if fetch_result.fetched_at:
        st.caption(
            f"Última atualização: "
            f"{fetch_result.fetched_at.strftime('%d/%m/%Y %H:%M:%S')} UTC"
        )


def _record_matches_filters(
    record: InventoryRecord, filters: FilterState, ignore_sku: bool = False
) -> bool:
    """Verifica se um InventoryRecord passa pelos filtros ativos.

    ignore_sku=True pula o filtro de SKU — usado no Consolidado Unificado, onde
    o SKU é filtrado depois da agregação para incluir todos os componentes do grupo.
    """
    if not ignore_sku and filters.sku_filter and filters.sku_filter.lower() not in record.sku.lower():
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


def _render_validation_tab(report: ValidationReport | None) -> None:
    """Renderiza a aba de validação de cobertura do fetch."""
    if report is None:
        st.info(
            "Execute um fetch clicando em **🔄 Atualizar Dados** para "
            "ver o relatório de validação."
        )
        return

    st.subheader("Cobertura por Operação")
    st.caption(
        "Cobertura = % de SKUs do pool que retornaram saldo > 0 para esta operação. "
        "Cobertura < 1% pode indicar warehouse_id incorreto."
    )

    _status_icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌"}
    rows = [
        {
            "Status": f"{_status_icon.get(c.status, '')} {c.status}",
            "Loja": c.store_code,
            "Operação": c.operation_type,
            "SKUs c/ Saldo": c.skus_with_stock,
            "SKUs Consultados": c.skus_queried,
            "Cobertura %": f"{c.coverage_pct:.1f}%",
        }
        for c in report.operation_coverage
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.metric("SKUs distintos no fetch", f"{report.total_skus_distinct:,}")
    col2.metric("Total de records", f"{report.total_records:,}")
    col3.metric(
        "SKUs do registry sem saldo",
        len(report.registry_skus_zero_everywhere),
        help="SKUs conhecidos que retornaram saldo 0 em todas as operações",
    )

    if report.partial_inventory_ops:
        with st.expander(
            f"⚠️ Operações com falha parcial de batch ({len(report.partial_inventory_ops)})",
            expanded=True,
        ):
            for store_code, op_type in report.partial_inventory_ops:
                st.error(
                    f"**{store_code}/{op_type}** — fetch parcial: "
                    "alguns SKUs podem estar ausentes dos saldos."
                )

    if report.registry_skus_zero_everywhere:
        with st.expander(
            f"SKUs do registry sem saldo em nenhuma operação "
            f"({len(report.registry_skus_zero_everywhere)})",
            expanded=False,
        ):
            st.caption(
                "Estes SKUs estão no registro histórico mas não retornaram saldo "
                "em nenhuma operação neste fetch. Podem estar descontinuados ou "
                "ainda não cadastrados nos warehouses ativos."
            )
            st.write(report.registry_skus_zero_everywhere)

    if not report.partial_inventory_ops and not report.registry_skus_zero_everywhere:
        st.success("✅ Nenhuma anomalia detectada — fetch com cobertura completa.")

    st.caption(
        f"Validação gerada em: "
        f"{report.generated_at.strftime('%d/%m/%Y %H:%M:%S')} UTC"
    )


def _render_migration_sidebar(
    consolidated_df: pd.DataFrame,
    sku_mapping: dict[str, str],
) -> None:
    """Renderiza a seção de alertas de migração de SKU no sidebar."""
    alerts = compute_migration_alerts(consolidated_df, sku_mapping)
    if not alerts:
        return

    urgent = [a for a in alerts if a.status == MigrationStatus.URGENT]
    monitor = [a for a in alerts if a.status == MigrationStatus.MONITOR]

    st.markdown("---")
    st.markdown("**🔄 Status de Migração**")

    badge = ""
    if urgent:
        badge = f" 🔴 {len(urgent)} urgente(s)"
    elif monitor:
        badge = f" 🟡 {len(monitor)} monitorando"

    with st.expander(f"Ver {len(alerts)} mapeamentos{badge}", expanded=bool(urgent)):
        _icon = {
            MigrationStatus.DONE: "✅",
            MigrationStatus.URGENT: "⚠️",
            MigrationStatus.MONITOR: "📉",
            MigrationStatus.NORMAL: "ℹ️",
        }
        _label = {
            MigrationStatus.DONE: "Concluída",
            MigrationStatus.URGENT: "Urgente",
            MigrationStatus.MONITOR: "Monitorar",
            MigrationStatus.NORMAL: "Normal",
        }
        for alert in alerts:
            icon = _icon[alert.status]
            label = _label[alert.status]
            pct = f"{alert.pct_migrado:.0f}%"
            if alert.status == MigrationStatus.DONE:
                detail = "zerado"
            else:
                detail = f"{alert.stock_antigo:,} unid."
            st.markdown(
                f"{icon} `{alert.sku_antigo}` → `{alert.sku_novo}`  \n"
                f"&nbsp;&nbsp;&nbsp;&nbsp;{label} — {detail} ({pct} migrado)"
            )


def _render_shopify_sidebar(
    unified_df: pd.DataFrame,
    settings,
) -> None:
    """Renderiza a seção de sync Shopify no sidebar."""
    st.markdown("---")
    st.markdown("**📤 Shopify Sync**")
    st.caption(f"Loja: `{settings.shopify_store_domain}`")

    active_only = st.toggle(
        "Apenas SKUs ativos",
        value=True,
        key="shopify_active_only",
        help="Sincroniza somente variantes de produtos com status Ativo na Shopify.",
    )

    # Confirmação quando o usuário desativa o filtro de ativos
    sync_enabled = True
    if not active_only:
        st.warning(
            "⚠️ Você está prestes a sincronizar **todos** os SKUs, "
            "incluindo produtos em **rascunho** e **arquivados**."
        )
        confirmed = st.checkbox(
            "Confirmo — incluir produtos inativos no sync",
            value=False,
            key="shopify_inactive_confirmed",
        )
        sync_enabled = confirmed
        if not confirmed:
            st.caption("Marque a confirmação acima para habilitar o botão.")

    sync_clicked = st.button(
        "📤 Sincronizar → Shopify",
        use_container_width=True,
        disabled=not sync_enabled,
        help=(
            "Envia stock_available_consolidated (SKU Unificado) "
            "para o inventário da Shopify."
        ),
    )

    if sync_clicked and sync_enabled:
        if unified_df.empty:
            st.warning("Sem dados para sincronizar.")
        else:
            sync_df = (
                unified_df[["sku_unificado", "stock_available_consolidated"]]
                .rename(columns={"sku_unificado": "sku"})
            )
            try:
                client = ShopifyClient(
                    store_domain=settings.shopify_store_domain,
                    access_token=settings.shopify_access_token,
                )
                spinner_msg = (
                    "Buscando produtos ativos e sincronizando..."
                    if active_only
                    else "Sincronizando todos os SKUs com Shopify..."
                )
                with st.spinner(spinner_msg):
                    result = sync_consolidated_to_shopify(
                        sync_df, client, settings.shopify_location_id,
                        active_only=active_only,
                    )
                st.session_state["shopify_sync_result"] = result
            except ShopifyAuthError as exc:
                st.error(f"❌ Erro de autenticação Shopify: {exc}")
            except Exception as exc:
                st.error(f"❌ Erro inesperado no sync: {exc}")

    sync_result: ShopifySyncResult | None = st.session_state.get("shopify_sync_result")
    if sync_result:
        st.caption(
            f"Último sync: "
            f"{sync_result.synced_at.strftime('%d/%m/%Y %H:%M')} UTC"
        )
        if sync_result.synced_count > 0:
            st.success(f"✅ {sync_result.synced_count} SKUs sincronizados")
        if sync_result.skus_not_found:
            st.warning(
                f"⚠️ {len(sync_result.skus_not_found)} SKUs não encontrados "
                f"nos produtos {'ativos ' if st.session_state.get('shopify_active_only', True) else ''}da Shopify"
            )
        if sync_result.failed_skus:
            st.error(f"❌ {len(sync_result.failed_skus)} SKUs com falha no push")


if __name__ == "__main__":
    main()

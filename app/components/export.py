"""
Componente de exportação do dashboard.

Renderiza os botões de download para CSV e Excel.
Os arquivos são gerados em memória (sem escrita em disco).
"""

import pandas as pd
import streamlit as st

from src.utils.export import (
    filename_consolidated_csv,
    filename_detailed_csv,
    filename_excel,
    filename_excel_unified,
    filename_unified_csv,
    to_csv_bytes,
    to_excel_bytes,
    to_excel_bytes_unified,
)


def render_export_buttons(
    detailed_df: pd.DataFrame,
    consolidated_df: pd.DataFrame,
    unified_df: pd.DataFrame | None = None,
) -> None:
    """
    Renderiza botões de exportação para as três visões.

    Args:
        detailed_df:     DataFrame detalhado.
        consolidated_df: DataFrame consolidado padrão.
        unified_df:      DataFrame consolidado SKU Unificado (opcional).
    """
    st.subheader("Exportar Dados")

    has_data = not detailed_df.empty or not consolidated_df.empty
    has_unified = unified_df is not None and not unified_df.empty

    if not has_data and not has_unified:
        st.info("Nenhum dado para exportar.")
        return

    # ── Linha 1: CSVs individuais ──────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if not detailed_df.empty:
            st.download_button(
                label="Detalhada (CSV)",
                data=to_csv_bytes(detailed_df),
                file_name=filename_detailed_csv(),
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.button("Detalhada (CSV)", disabled=True, use_container_width=True)

    with col2:
        if not consolidated_df.empty:
            st.download_button(
                label="Consolidada (CSV)",
                data=to_csv_bytes(consolidated_df),
                file_name=filename_consolidated_csv(),
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.button("Consolidada (CSV)", disabled=True, use_container_width=True)

    with col3:
        if has_unified:
            st.download_button(
                label="SKU Unificado (CSV)",
                data=to_csv_bytes(unified_df),
                file_name=filename_unified_csv(),
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.button("SKU Unificado (CSV)", disabled=True, use_container_width=True)

    with col4:
        if has_data or has_unified:
            excel_bytes = to_excel_bytes_unified(
                detailed_df=detailed_df if not detailed_df.empty else pd.DataFrame(),
                consolidated_df=consolidated_df if not consolidated_df.empty else pd.DataFrame(),
                unified_df=unified_df if has_unified else pd.DataFrame(),
            )
            st.download_button(
                label="Excel Completo",
                data=excel_bytes,
                file_name=filename_excel_unified(),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                help="Excel com abas: Detalhado, Consolidado e SKU Unificado.",
            )
        else:
            st.button("Excel Completo", disabled=True, use_container_width=True)

    st.caption(
        f"Detalhada: {len(detailed_df):,} linhas · "
        f"Consolidada: {len(consolidated_df):,} SKUs · "
        f"SKU Unificado: {len(unified_df) if has_unified else 0:,} SKUs"
    )

"""
Utilitários de exportação de dados para CSV e Excel.

Gera arquivos em memória (BytesIO/StringIO) para uso direto com
st.download_button do Streamlit, sem escrita em disco.
"""

import io
from datetime import datetime

import pandas as pd


def _timestamp() -> str:
    """Retorna timestamp formatado para uso em nomes de arquivo."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Converte um DataFrame para bytes CSV (UTF-8 com BOM para compatibilidade Excel).

    Args:
        df: DataFrame a exportar.

    Returns:
        Conteúdo CSV como bytes.
    """
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def to_excel_bytes(detailed_df: pd.DataFrame, consolidated_df: pd.DataFrame) -> bytes:
    """
    Gera um arquivo Excel com dois sheets em memória.

    Sheet 1 — "Detalhado":   uma linha por (store_code, operation_type, sku)
    Sheet 2 — "Consolidado": uma linha por SKU com totais agregados

    Args:
        detailed_df:     DataFrame detalhado.
        consolidated_df: DataFrame consolidado.

    Returns:
        Conteúdo do arquivo .xlsx como bytes.
    """
    def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
        """Remove timezone de colunas datetime para compatibilidade com openpyxl."""
        df = df.copy()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]) and df[col].dt.tz is not None:
                df[col] = df[col].dt.tz_convert(None)
        return df

    detailed_df = _strip_tz(detailed_df)
    consolidated_df = _strip_tz(consolidated_df)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        detailed_df.to_excel(writer, sheet_name="Detalhado", index=False)
        consolidated_df.to_excel(writer, sheet_name="Consolidado", index=False)

        # Auto-ajusta largura das colunas em ambas as sheets
        for sheet_name, df in [("Detalhado", detailed_df), ("Consolidado", consolidated_df)]:
            worksheet = writer.sheets[sheet_name]
            for col_idx, column in enumerate(df.columns, 1):
                max_len = max(
                    len(str(column)),
                    df[column].astype(str).str.len().max() if len(df) > 0 else 0,
                )
                # Limita a 50 caracteres para evitar colunas gigantescas
                worksheet.column_dimensions[
                    worksheet.cell(row=1, column=col_idx).column_letter
                ].width = min(max_len + 2, 50)

    return buffer.getvalue()


def to_excel_bytes_unified(
    detailed_df: pd.DataFrame,
    consolidated_df: pd.DataFrame,
    unified_df: pd.DataFrame,
) -> bytes:
    """
    Gera Excel com três sheets: Detalhado, Consolidado e SKU Unificado.

    Args:
        detailed_df:     DataFrame detalhado.
        consolidated_df: DataFrame consolidado padrão.
        unified_df:      DataFrame consolidado com SKUs unificados.

    Returns:
        Conteúdo do arquivo .xlsx como bytes.
    """
    def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]) and df[col].dt.tz is not None:
                df[col] = df[col].dt.tz_convert(None)
        return df

    detailed_df = _strip_tz(detailed_df)
    consolidated_df = _strip_tz(consolidated_df)
    unified_df = _strip_tz(unified_df)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sheets = [
            ("Detalhado", detailed_df),
            ("Consolidado", consolidated_df),
            ("SKU Unificado", unified_df),
        ]
        for sheet_name, df in sheets:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            for col_idx, column in enumerate(df.columns, 1):
                max_len = max(
                    len(str(column)),
                    df[column].astype(str).str.len().max() if len(df) > 0 else 0,
                )
                worksheet.column_dimensions[
                    worksheet.cell(row=1, column=col_idx).column_letter
                ].width = min(max_len + 2, 50)

    return buffer.getvalue()


def filename_detailed_csv() -> str:
    return f"estoca_detalhado_{_timestamp()}.csv"


def filename_consolidated_csv() -> str:
    return f"estoca_consolidado_{_timestamp()}.csv"


def filename_unified_csv() -> str:
    return f"estoca_sku_unificado_{_timestamp()}.csv"


def filename_excel() -> str:
    return f"estoca_inventario_{_timestamp()}.xlsx"


def filename_excel_unified() -> str:
    return f"estoca_inventario_completo_{_timestamp()}.xlsx"

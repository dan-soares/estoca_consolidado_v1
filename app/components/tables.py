"""
Componentes de renderização de tabelas do dashboard.

Renderiza as tabelas detalhada e consolidada com formatação
adequada para visualização no Streamlit.
"""

import pandas as pd
import streamlit as st


def _format_stock_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Garante que colunas de saldo sejam inteiros (sem decimais)."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
    return df


def render_detailed_table(df: pd.DataFrame) -> None:
    """
    Renderiza a tabela detalhada de inventário.

    Uma linha por (store_code, operation_type, sku).
    Exibe todos os campos do modelo canônico.

    Args:
        df: DataFrame detalhado (já filtrado).
    """
    st.subheader("Visão Detalhada")
    st.caption(
        "Uma linha por combinação de loja + operação + SKU. "
        "Reflete exatamente o que foi retornado por cada credencial da API."
    )

    if df.empty:
        st.info("Nenhum registro encontrado com os filtros aplicados.")
        return

    # Formata colunas de saldo
    stock_cols = ["stock_total", "stock_available", "stock_reserved", "stock_blocked"]
    df_display = _format_stock_columns(df.copy(), stock_cols)

    # Formata coluna de data
    if "updated_at" in df_display.columns:
        df_display["updated_at"] = pd.to_datetime(df_display["updated_at"]).dt.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

    # Colunas a exibir (ordem amigável)
    display_cols = [
        "store_code",
        "business_unit",
        "operation_type",
        "sku",
        "product_name",
        "stock_total",
        "stock_available",
        "stock_reserved",
        "stock_blocked",
        "estoca_warehouse_id",
        "estoca_store_id",
        "country",
        "source_system",
        "updated_at",
    ]
    available_cols = [c for c in display_cols if c in df_display.columns]

    st.dataframe(
        df_display[available_cols],
        use_container_width=True,
        height=400,
        column_config={
            "store_code": st.column_config.TextColumn("Loja", width="small"),
            "business_unit": st.column_config.TextColumn("Unid. Negócio"),
            "operation_type": st.column_config.TextColumn("Operação", width="small"),
            "sku": st.column_config.TextColumn("SKU"),
            "product_name": st.column_config.TextColumn("Descrição"),
            "stock_total": st.column_config.NumberColumn("Total", format="%d"),
            "stock_available": st.column_config.NumberColumn("Disponível", format="%d"),
            "stock_reserved": st.column_config.NumberColumn("Reservado", format="%d"),
            "stock_blocked": st.column_config.NumberColumn("Bloqueado", format="%d"),
            "estoca_warehouse_id": st.column_config.TextColumn("Warehouse ID"),
            "estoca_store_id": st.column_config.TextColumn("Store ID"),
            "country": st.column_config.TextColumn("País", width="small"),
            "source_system": st.column_config.TextColumn("Sistema", width="small"),
            "updated_at": st.column_config.TextColumn("Atualizado em"),
        },
    )
    st.caption(f"{len(df_display):,} registros exibidos.")


def render_consolidated_table(df: pd.DataFrame) -> None:
    """
    Renderiza a tabela consolidada de inventário.

    Uma linha por SKU com saldos somados de todas as origens.
    Registros de operações com dedup_group são contados apenas uma vez.

    Total Consolidado = Disponível + Bloqueado.
    Reservado é exibido como coluna informativa (pallets em processo de expedição).

    Args:
        df: DataFrame consolidado (já filtrado via SKU).
    """
    st.subheader("Visão Consolidada (por SKU)")
    st.caption(
        "Saldo nacional consolidado por SKU. "
        "**Total = Disponível + Bloqueado.** "
        "Reservado é informativo — pallets já alocados a pedidos em expedição, não compõem o saldo. "
        "Operações com credenciais compartilhadas (ex: 0101 B2B = B2C) são contadas **uma única vez**."
    )

    if df.empty:
        st.info("Nenhum registro consolidado encontrado com os filtros aplicados.")
        return

    stock_cols = [
        "stock_net_consolidated",
        "stock_available_consolidated",
        "stock_blocked_consolidated",
        "stock_reserved_consolidated",
    ]
    df_display = _format_stock_columns(df.copy(), stock_cols)

    if "updated_at" in df_display.columns:
        df_display["updated_at"] = pd.to_datetime(df_display["updated_at"]).dt.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

    display_cols = [
        "sku",
        "product_name",
        "stock_net_consolidated",
        "stock_available_consolidated",
        "stock_blocked_consolidated",
        "stock_reserved_consolidated",
        "source_count",
        "operations_list",
        "updated_at",
    ]
    available_cols = [c for c in display_cols if c in df_display.columns]

    st.dataframe(
        df_display[available_cols],
        use_container_width=True,
        height=400,
        column_config={
            "sku": st.column_config.TextColumn("SKU"),
            "product_name": st.column_config.TextColumn("Descrição"),
            "stock_net_consolidated": st.column_config.NumberColumn(
                "Total Consolidado",
                format="%d",
                help="Disponível + Bloqueado. Saldo real que o CD possui ou pode movimentar.",
            ),
            "stock_available_consolidated": st.column_config.NumberColumn(
                "Disponível", format="%d",
                help="Pronto para alocação em novos pedidos.",
            ),
            "stock_blocked_consolidated": st.column_config.NumberColumn(
                "Bloqueado", format="%d",
                help="Pallet em posição elevada — requer empilhadeira para movimentação.",
            ),
            "stock_reserved_consolidated": st.column_config.NumberColumn(
                "Reservado ⓘ", format="%d",
                help="Informativo — alocado em pedidos existentes, aguardando despacho. Não compõe o Total Consolidado.",
            ),
            "source_count": st.column_config.NumberColumn(
                "Origens", format="%d",
                help="Número de operações que contribuíram para este SKU.",
            ),
            "operations_list": st.column_config.TextColumn(
                "Operações",
                help="Operações que compõem o saldo consolidado.",
            ),
            "updated_at": st.column_config.TextColumn("Atualizado em"),
        },
    )
    st.caption(f"{len(df_display):,} SKUs únicos consolidados.")


def render_unified_consolidated_table(df: pd.DataFrame, mapping_count: int) -> None:
    """
    Renderiza a tabela do consolidado com SKUs unificados (de/para).

    Idêntica à consolidada padrão, com colunas adicionais:
      skus_origem  — SKUs originais que foram somados neste registro
      tem_migracao — destaca visualmente linhas com unificação ativa

    Args:
        df:            DataFrame do consolidado unificado (já filtrado).
        mapping_count: Número de mapeamentos de/para carregados do CSV.
    """
    st.subheader("Consolidado SKU Unificado")

    if mapping_count == 0:
        st.info(
            "Nenhum mapeamento de/para configurado em `config/sku_mapping.csv`. "
            "Adicione linhas no formato `sku_de,sku_para` para ver SKUs unificados."
        )
    else:
        st.caption(
            f"{mapping_count} mapeamento(s) de/para ativos. "
            "**Total = Disponível + Bloqueado.** "
            "Linhas com '↔' na coluna **Migração** indicam SKUs unificados. "
            "Reservado é informativo — não compõe o Total Consolidado."
        )

    if df.empty:
        st.info("Nenhum registro encontrado com os filtros aplicados.")
        return

    stock_cols = [
        "stock_net_consolidated",
        "stock_available_consolidated",
        "stock_blocked_consolidated",
        "stock_reserved_consolidated",
    ]
    df_display = _format_stock_columns(df.copy(), stock_cols)

    if "updated_at" in df_display.columns:
        df_display["updated_at"] = pd.to_datetime(df_display["updated_at"]).dt.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

    # Converte bool para ícone legível
    if "tem_migracao" in df_display.columns:
        df_display["tem_migracao"] = df_display["tem_migracao"].map(
            {True: "↔ Sim", False: "—"}
        )

    display_cols = [
        "sku_unificado",
        "product_name",
        "tem_migracao",
        "skus_origem",
        "stock_net_consolidated",
        "stock_available_consolidated",
        "stock_blocked_consolidated",
        "stock_reserved_consolidated",
        "source_count",
        "operations_list",
        "updated_at",
    ]
    available_cols = [c for c in display_cols if c in df_display.columns]

    st.dataframe(
        df_display[available_cols],
        use_container_width=True,
        height=400,
        column_config={
            "sku_unificado": st.column_config.TextColumn("SKU Unificado"),
            "product_name": st.column_config.TextColumn("Descrição"),
            "tem_migracao": st.column_config.TextColumn(
                "Migração",
                help="'↔ Sim' indica que este total soma SKUs antigos e novos.",
                width="small",
            ),
            "skus_origem": st.column_config.TextColumn(
                "SKUs de Origem",
                help="Todos os SKUs (antigos e novos) que compõem este total.",
            ),
            "stock_net_consolidated": st.column_config.NumberColumn(
                "Total Consolidado",
                format="%d",
                help="Disponível + Bloqueado. Saldo real somando todos os SKUs de origem.",
            ),
            "stock_available_consolidated": st.column_config.NumberColumn(
                "Disponível", format="%d",
            ),
            "stock_blocked_consolidated": st.column_config.NumberColumn(
                "Bloqueado", format="%d",
                help="Pallet em posição elevada — requer empilhadeira.",
            ),
            "stock_reserved_consolidated": st.column_config.NumberColumn(
                "Reservado ⓘ", format="%d",
                help="Informativo — alocado em pedidos existentes, não compõe o Total.",
            ),
            "source_count": st.column_config.NumberColumn(
                "Origens", format="%d",
                help="Número de linhas de operação que contribuíram.",
            ),
            "operations_list": st.column_config.TextColumn("Operações"),
            "updated_at": st.column_config.TextColumn("Atualizado em"),
        },
    )

    migrated = int(df_display["tem_migracao"].eq("↔ Sim").sum()) if "tem_migracao" in df_display.columns else 0
    st.caption(
        f"{len(df_display):,} SKUs únicos consolidados"
        + (f" — {migrated} com migração ativa." if migrated else ".")
    )

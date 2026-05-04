"""
Alertas de migração de SKU.

Para cada par (sku_antigo → sku_novo) no sku_mapping, classifica o status
de migração com base no estoque disponível consolidado do SKU antigo.
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class MigrationStatus(Enum):
    DONE    = "done"     # sku_antigo = 0 → migração concluída
    URGENT  = "urgent"   # sku_antigo ≤ threshold_low
    MONITOR = "monitor"  # sku_antigo ≤ threshold_high
    NORMAL  = "normal"   # sku_antigo > threshold_high


@dataclass
class MigrationAlert:
    sku_antigo: str
    sku_novo: str
    stock_antigo: int    # stock_net_consolidated (disponível + bloqueado) do sku_antigo
    stock_novo: int      # stock_net_consolidated do sku_novo
    status: MigrationStatus
    pct_migrado: float   # stock_novo / (stock_antigo + stock_novo) * 100


def compute_migration_alerts(
    consolidated_df: pd.DataFrame,
    sku_mapping: dict[str, str],
    threshold_low: int = 50,
    threshold_high: int = 500,
) -> list[MigrationAlert]:
    """
    Classifica o progresso de migração para cada par em sku_mapping.

    Usa stock_net_consolidated (disponível + bloqueado) para que SKUs com
    saldo bloqueado não apareçam erroneamente como "concluídos".

    Args:
        consolidated_df: Output COMPLETO (não filtrado) de get_consolidated_dataframe().
        sku_mapping:     {sku_de: sku_para} do sku_mapping.csv.
        threshold_low:   Unidades do sku_antigo que disparam URGENT.
        threshold_high:  Unidades do sku_antigo que disparam MONITOR.

    Returns:
        Lista ordenada: URGENT → MONITOR → DONE → NORMAL.
    """
    if consolidated_df.empty or "stock_net_consolidated" not in consolidated_df.columns:
        stock_lookup: dict[str, int] = {}
    else:
        stock_lookup = (
            consolidated_df.set_index("sku")["stock_net_consolidated"]
            .astype(int)
            .to_dict()
        )

    _order = {
        MigrationStatus.URGENT: 0,
        MigrationStatus.MONITOR: 1,
        MigrationStatus.DONE: 2,
        MigrationStatus.NORMAL: 3,
    }

    alerts: list[MigrationAlert] = []
    for sku_de, sku_para in sku_mapping.items():
        stock_antigo = stock_lookup.get(sku_de, 0)
        stock_novo = stock_lookup.get(sku_para, 0)
        total = stock_antigo + stock_novo
        pct_migrado = (stock_novo / total * 100) if total > 0 else 100.0

        if stock_antigo == 0:
            status = MigrationStatus.DONE
        elif stock_antigo <= threshold_low:
            status = MigrationStatus.URGENT
        elif stock_antigo <= threshold_high:
            status = MigrationStatus.MONITOR
        else:
            status = MigrationStatus.NORMAL

        alerts.append(MigrationAlert(
            sku_antigo=sku_de,
            sku_novo=sku_para,
            stock_antigo=stock_antigo,
            stock_novo=stock_novo,
            status=status,
            pct_migrado=pct_migrado,
        ))

    return sorted(alerts, key=lambda a: (_order[a.status], a.sku_antigo))

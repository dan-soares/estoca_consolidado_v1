"""
Validação de cobertura do fetch de inventário.

Detecta anomalias após um fetch:
- Operações com cobertura baixa (possível warehouse_id errado)
- SKUs do registry que não retornaram saldo em nenhuma operação
- Operações com falha parcial de batch
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.services.aggregation import FetchResult


@dataclass
class OperationCoverage:
    store_code: str
    operation_type: str
    skus_with_stock: int    # SKUs distintos com qualquer saldo > 0
    skus_queried: int       # SKUs distintos retornados pela API para esta op
    coverage_pct: float     # skus_with_stock / skus_queried * 100
    status: str             # "OK" | "WARN" | "ERROR"


@dataclass
class ValidationReport:
    operation_coverage: list[OperationCoverage]
    registry_skus_zero_everywhere: list[str]     # No seed_skus mas saldo 0 em todas as ops
    partial_inventory_ops: list[tuple[str, str]] # (store_code, op_type) com PartialInventoryError
    total_skus_distinct: int
    total_records: int
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


def validate_fetch(result: FetchResult, seed_skus: set[str]) -> ValidationReport:
    """
    Valida cobertura e integridade de um FetchResult.

    Args:
        result:    Produzido por InventoryAggregationService.fetch_all().
        seed_skus: SKUs do registry usados como semente (antes do fetch).
    """
    # ── Agrupa records por (store_code, operation_type) ──────────────────────
    op_records: dict[tuple[str, str], list] = defaultdict(list)
    for rec in result.records:
        op_records[(rec.store_code, rec.operation_type)].append(rec)

    # ── Cobertura por operação ────────────────────────────────────────────────
    coverage_list: list[OperationCoverage] = []
    for (store_code, op_type), records in sorted(op_records.items()):
        distinct_skus = {r.sku for r in records}
        skus_queried = len(distinct_skus)
        skus_with_stock = len({
            r.sku for r in records
            if (r.stock_total or 0) + (r.stock_available or 0)
            + (r.stock_blocked or 0) + (r.stock_reserved or 0) > 0
        })
        coverage_pct = (
            (skus_with_stock / skus_queried * 100) if skus_queried > 0 else 0.0
        )
        if skus_queried == 0 or coverage_pct == 0.0:
            status = "ERROR"
        elif coverage_pct < 1.0:
            status = "WARN"
        else:
            status = "OK"

        coverage_list.append(OperationCoverage(
            store_code=store_code,
            operation_type=op_type,
            skus_with_stock=skus_with_stock,
            skus_queried=skus_queried,
            coverage_pct=coverage_pct,
            status=status,
        ))

    # Operações que falharam completamente (sem records) aparecem como ERROR
    ops_no_records = {
        (e.store_code, e.operation_type)
        for e in result.errors
        if e.error_type not in ("PartialInventoryError",)
    }
    for store_code, op_type in sorted(ops_no_records):
        if (store_code, op_type) not in op_records:
            coverage_list.append(OperationCoverage(
                store_code=store_code,
                operation_type=op_type,
                skus_with_stock=0,
                skus_queried=0,
                coverage_pct=0.0,
                status="ERROR",
            ))

    # ── SKUs do registry com saldo 0 em todas as operações ───────────────────
    all_skus_with_any_stock = {
        r.sku for r in result.records
        if (r.stock_total or 0) + (r.stock_available or 0)
        + (r.stock_blocked or 0) + (r.stock_reserved or 0) > 0
    }
    registry_zero = sorted(seed_skus - all_skus_with_any_stock) if seed_skus else []

    # ── Operações com PartialInventoryError ──────────────────────────────────
    partial_ops = [
        (e.store_code, e.operation_type)
        for e in result.errors
        if e.error_type == "PartialInventoryError"
    ]

    return ValidationReport(
        operation_coverage=sorted(
            coverage_list, key=lambda x: (x.store_code, x.operation_type)
        ),
        registry_skus_zero_everywhere=registry_zero,
        partial_inventory_ops=partial_ops,
        total_skus_distinct=len({r.sku for r in result.records}),
        total_records=result.total_records,
    )

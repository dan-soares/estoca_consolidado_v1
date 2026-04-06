"""
Carregamento do mapeamento de SKUs (de/para) a partir de config/sku_mapping.csv.

O arquivo CSV deve ter duas colunas obrigatórias:
  sku_de  — SKU antigo (a ser substituído)
  sku_para — SKU novo (SKU unificado de destino)

Linhas em branco e comentários (iniciados com #) são ignorados.
O arquivo é opcional: se não existir, retorna mapeamento vazio
e a visão unificada será idêntica à consolidada padrão.
"""

import csv
from pathlib import Path


def _find_sku_mapping_csv() -> Path | None:
    """Localiza config/sku_mapping.csv a partir do diretório de trabalho."""
    candidates = [
        Path("config/sku_mapping.csv"),
        Path("../config/sku_mapping.csv"),
        Path(__file__).parent.parent.parent / "config" / "sku_mapping.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_sku_mapping() -> dict[str, str]:
    """
    Carrega o mapeamento de SKUs do CSV.

    Returns:
        Dicionário {sku_de: sku_para}. Vazio se o arquivo não existir.

    Raises:
        ValueError: Se o CSV estiver malformado (colunas ausentes, linhas inválidas).
    """
    csv_path = _find_sku_mapping_csv()
    if csv_path is None:
        return {}

    mapping: dict[str, str] = {}

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {"sku_de", "sku_para"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"config/sku_mapping.csv deve ter as colunas: {', '.join(sorted(required))}. "
                f"Colunas encontradas: {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):
            sku_de = (row["sku_de"] or "").strip()

            # Ignora linhas em branco ou comentários antes de tocar em sku_para
            if not sku_de or sku_de.startswith("#"):
                continue

            sku_para = (row["sku_para"] or "").strip()

            if not sku_para:
                raise ValueError(
                    f"config/sku_mapping.csv linha {line_num}: "
                    f"'sku_para' está vazio para sku_de='{sku_de}'."
                )

            if sku_de in mapping and mapping[sku_de] != sku_para:
                raise ValueError(
                    f"config/sku_mapping.csv: sku_de='{sku_de}' mapeado para "
                    f"'{mapping[sku_de]}' e '{sku_para}' — mapeamento ambíguo."
                )

            mapping[sku_de] = sku_para

    return mapping

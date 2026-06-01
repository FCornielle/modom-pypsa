"""Construcción de la tabla canónica inicial de snapshots para MODOM."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .xlsm import XlsmReader, matrix_to_structured_rows


INTEGER_RANGE_RE = re.compile(r"^\s*(\d+)\s*\*\s*(\d+)\s*$")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean(value: str) -> str:
    return str(value or "").strip()


def parse_integer_range(spec: str) -> tuple[int, int] | None:
    """Parsea expresiones GAMS simples del tipo `1*48`."""
    match = INTEGER_RANGE_RE.fullmatch(clean(spec))
    if not match:
        return None
    start, end = (int(match.group(1)), int(match.group(2)))
    if start > end:
        return None
    return (start, end)


def find_horizon_row(reader: XlsmReader) -> dict[str, str]:
    """Busca en `e_sets` la fila que define el horizonte `N`."""
    matrix = reader.read_sheet_matrix("e_sets")
    _, rows = matrix_to_structured_rows(matrix, 3)

    for row in rows:
        if clean(row.get("PD", "")) != "N":
            continue
        description = clean(row.get("periodos", ""))
        range_spec = clean(row.get("pd001pd007", ""))
        if description and range_spec:
            return {
                "set_name": "N",
                "description": description,
                "range_spec": range_spec,
            }
    raise ValueError("No se encontró la fila de horizonte `N` en `e_sets`.")


def extract_load_block_labels(reader: XlsmReader) -> list[str]:
    """Extrae el eje horario 24h disponible en `PDemanda`."""
    matrix = reader.read_sheet_matrix("PDemanda")
    if not matrix:
        return []

    header = matrix[0]
    labels = [clean(value) for value in header[1:] if clean(value)]
    return labels


def build_snapshots(reader: XlsmReader) -> dict[str, object]:
    """Construye la primera versión v1 de `snapshots` sobre eje horario 24h."""
    horizon = find_horizon_row(reader)
    parsed_range = parse_integer_range(horizon["range_spec"])
    if parsed_range is None:
        raise ValueError(
            f"No se pudo interpretar el horizonte de `e_sets`: {horizon['range_spec']!r}"
        )

    start, end = parsed_range
    period_count = end - start + 1
    load_blocks = extract_load_block_labels(reader)

    snapshots: list[dict[str, object]] = []
    for snapshot_order, block_label in enumerate(load_blocks, start=1):
        snapshots.append(
            {
                "snapshot_id": f"h_{int(block_label):02d}",
                "snapshot_order": snapshot_order,
                "snapshot_label_modom": str(block_label),
                "time_block_group": "canonical_hours_24h",
                "source_sheet": "PDemanda",
                "horizon_count": len(load_blocks),
                "time_resolution_minutes": 60,
                "hour_block_start_label": f"{int(block_label) - 1:02d}:00",
                "notes": (
                    "Snapshot canónico v1 derivado del eje horario `PDemanda`."
                ),
            }
        )

    horizon_summary = {
        "source_sheets": ["e_sets", "PDemanda"],
        "canonical_horizon_v1": {
            "source_sheet": "PDemanda",
            "block_count": len(load_blocks),
            "snapshot_ids": [item["snapshot_id"] for item in snapshots],
            "time_block_group": "canonical_hours_24h",
        },
        "dispatch_horizon": {
            "set_name": horizon["set_name"],
            "description": horizon["description"],
            "range_spec": horizon["range_spec"],
            "period_count": period_count,
            "snapshot_ids": [f"pd{period_index:03d}" for period_index in range(start, min(end, start + 5) + 1)]
            + (["..."] if period_count > 6 else []),
        },
        "load_profile_horizon": {
            "sheet_name": "PDemanda",
            "block_labels": load_blocks,
            "block_count": len(load_blocks),
            "hour_block_convention": {
                "h_1": "00:00-00:59",
                "h_24": "23:00-23:59",
            },
        },
        "consistency_flags": {
            "dispatch_vs_load_period_count_match": period_count == len(load_blocks),
            "canonical_v1_uses_24h_load_blocks": True,
            "requires_operational_48_to_24_translation": period_count != len(load_blocks),
        },
    }

    return {
        "snapshots": snapshots,
        "horizon_summary": horizon_summary,
    }


def export_snapshots(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    """Exporta `snapshots.csv` y un resumen de horizontes del caso MODOM."""
    reader = XlsmReader(xlsm_path)
    payload = build_snapshots(reader)

    write_csv(
        outdir / "snapshots.csv",
        payload["snapshots"],
        fieldnames=[
            "snapshot_id",
            "snapshot_order",
            "snapshot_label_modom",
            "time_block_group",
            "source_sheet",
            "horizon_count",
            "time_resolution_minutes",
            "hour_block_start_label",
            "notes",
        ],
    )
    write_json(outdir / "snapshot_horizon_summary.json", payload["horizon_summary"])
    return payload

"""Inventario reproducible de hojas clave del workbook MODOM."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .xlsm import XlsmReader, matrix_to_structured_rows


@dataclass(frozen=True)
class FocusSheetConfig:
    """Configuración de hojas que interesa inspeccionar primero."""

    sheet_name: str
    header_row: int


FOCUS_SHEETS: tuple[FocusSheetConfig, ...] = (
    FocusSheetConfig("e_sets", 3),
    FocusSheetConfig("e_datred", 3),
    FocusSheetConfig("e_datgen", 4),
    FocusSheetConfig("e_datdem", 5),
    FocusSheetConfig("PDemanda", 1),
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def detect_header_row(
    matrix: list[list[str]],
    max_scan_rows: int = 10,
) -> tuple[int | None, list[dict[str, object]]]:
    """Detecta la fila de encabezado más probable dentro del tramo inicial."""
    if not matrix:
        return (None, [])

    candidates: list[dict[str, object]] = []
    scan_limit = min(max_scan_rows, len(matrix))

    for row_idx in range(scan_limit):
        row = matrix[row_idx]
        non_empty_cells = [
            str(value).strip()
            for value in row
            if str(value).strip()
        ]
        if not non_empty_cells:
            continue

        unique_cells = len(set(non_empty_cells))
        next_rows = matrix[row_idx + 1 : row_idx + 4]
        supported_columns = 0
        for col_idx, value in enumerate(row):
            if not str(value).strip():
                continue
            if any(
                col_idx < len(next_row) and str(next_row[col_idx]).strip()
                for next_row in next_rows
            ):
                supported_columns += 1

        score = (len(non_empty_cells) * 4) + (unique_cells * 2) + (supported_columns * 3)
        candidates.append(
            {
                "row_1_based": row_idx + 1,
                "non_empty_cell_count": len(non_empty_cells),
                "unique_value_count": unique_cells,
                "supported_column_count": supported_columns,
                "score": score,
            }
        )

    if not candidates:
        return (None, [])

    best = max(
        candidates,
        key=lambda item: (
            item["score"],
            item["supported_column_count"],
            item["non_empty_cell_count"],
        ),
    )
    return (int(best["row_1_based"]), candidates)


def first_useful_columns(
    headers: list[str],
    rows: list[dict[str, str]],
    preview_scope_rows: int = 25,
) -> list[str]:
    """Devuelve las primeras columnas con evidencia de uso en el tramo inicial."""
    scope = rows[:preview_scope_rows]
    return [
        header
        for header in headers
        if any(str(row.get(header, "")).strip() for row in scope)
    ]


def build_focus_sheet_summary(
    reader: XlsmReader,
    config: FocusSheetConfig,
    preview_rows: int = 5,
    header_scan_rows: int = 10,
) -> dict[str, object]:
    """Resume una hoja clave con tamaño, columnas y muestra estructurada."""
    matrix = reader.read_sheet_matrix(config.sheet_name)
    detected_header_row, header_candidates = detect_header_row(
        matrix,
        max_scan_rows=header_scan_rows,
    )
    resolved_header_row = (
        config.header_row if len(matrix) >= config.header_row else detected_header_row or 1
    )
    headers, rows = matrix_to_structured_rows(matrix, resolved_header_row)

    preview = rows[:preview_rows]
    useful_columns = first_useful_columns(
        headers,
        rows,
        preview_scope_rows=max(preview_rows, 25),
    )

    return {
        "sheet_name": config.sheet_name,
        "configured_header_row_trimmed_1_based": config.header_row,
        "detected_header_row_trimmed_1_based": detected_header_row,
        "resolved_header_row_trimmed_1_based": resolved_header_row,
        "header_row_detection_matches_configured": detected_header_row == config.header_row,
        "header_detection_candidates": header_candidates,
        "row_count_trimmed": len(matrix),
        "col_count_trimmed": max((len(row) for row in matrix), default=0),
        "structured_column_count": len(headers),
        "structured_columns": headers,
        "first_useful_columns": useful_columns,
        "preview_rows": preview,
    }


def export_workbook_inventory(
    xlsm_path: Path,
    outdir: Path,
    preview_rows: int = 5,
    header_scan_rows: int = 10,
) -> dict[str, object]:
    """Exporta inventario general y foco inicial de hojas clave."""
    outdir.mkdir(parents=True, exist_ok=True)
    reader = XlsmReader(xlsm_path)

    sheet_inventory = [asdict(item) for item in reader.build_sheet_inventory()]
    focus_sheets = [
        build_focus_sheet_summary(
            reader,
            config,
            preview_rows=preview_rows,
            header_scan_rows=header_scan_rows,
        )
        for config in FOCUS_SHEETS
    ]

    payload = {
        "source_xlsm": str(xlsm_path),
        "sheet_count": len(sheet_inventory),
        "focus_sheet_names": [config.sheet_name for config in FOCUS_SHEETS],
        "notes": {
            "hour_block_convention": (
                "`h_1` representa el intervalo 00:00-00:59 y `h_24` el "
                "intervalo 23:00-23:59."
            )
        },
        "sheet_inventory": sheet_inventory,
        "focus_sheets": focus_sheets,
    }

    write_csv(
        outdir / "sheet_inventory.csv",
        sheet_inventory,
        fieldnames=[
            "sheet_index",
            "sheet_name",
            "dimension_ref",
            "row_count_trimmed",
            "col_count_trimmed",
        ],
    )
    for focus_sheet in focus_sheets:
        sheet_name = str(focus_sheet["sheet_name"])
        slug = sheet_name.lower().replace(" ", "_")
        write_json(outdir / "focus_sheets" / f"{slug}.json", focus_sheet)
        preview_rows_payload = list(focus_sheet["preview_rows"])
        if preview_rows_payload:
            preview_fieldnames = list(preview_rows_payload[0].keys())
            write_csv(
                outdir / "focus_sheets" / f"{slug}_preview.csv",
                preview_rows_payload,
                fieldnames=preview_fieldnames,
            )

    write_json(outdir / "workbook_inventory.json", payload)
    return payload

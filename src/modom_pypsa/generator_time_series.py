"""Series temporales canónicas de generación para MODOM."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .generators import build_generators
from .snapshots import build_snapshots
from .xlsm import XlsmReader


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


def to_float(value: str) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_wide_generator_sheet(
    reader: XlsmReader,
    sheet_name: str,
    *,
    header_row_idx: int,
    data_start_row_idx: int,
    generator_id_col: int,
    generator_name_col: int,
    first_period_col: int,
) -> dict[str, object]:
    matrix = reader.read_sheet_matrix(sheet_name)
    if len(matrix) <= header_row_idx:
        raise ValueError(f"La hoja {sheet_name!r} no contiene fila de encabezado suficiente.")

    header = matrix[header_row_idx]
    period_labels: list[str] = []
    col_idx = first_period_col
    while col_idx < len(header):
        label = clean(header[col_idx])
        if not label.isdigit():
            break
        period_labels.append(label)
        col_idx += 1

    rows: list[dict[str, object]] = []
    seen_ids: list[str] = []
    for row in matrix[data_start_row_idx:]:
        if len(row) <= generator_id_col:
            continue
        generator_id = clean(row[generator_id_col])
        if not generator_id.startswith("G"):
            continue
        generator_name = clean(row[generator_name_col]) if len(row) > generator_name_col else ""
        values: list[float] = []
        for offset in range(len(period_labels)):
            value_idx = first_period_col + offset
            value = to_float(row[value_idx]) if len(row) > value_idx else None
            values.append(value if value is not None else 0.0)
        rows.append(
            {
                "generator_id": generator_id,
                "generator_name_sheet": generator_name,
                "values_mw": values,
            }
        )
        seen_ids.append(generator_id)

    return {
        "sheet_name": sheet_name,
        "period_labels": period_labels,
        "rows": rows,
        "unique_ids": sorted(set(seen_ids)),
    }


def align_generator_rows_to_snapshots(
    parsed: dict[str, object],
    snapshot_ids: list[str],
) -> dict[str, object]:
    period_labels = list(parsed["period_labels"])
    rows = list(parsed["rows"])

    if len(period_labels) == len(snapshot_ids):
        return {
            "period_labels": period_labels,
            "rows": rows,
            "time_alignment_method": "direct_match",
        }

    if len(period_labels) == 2 * len(snapshot_ids):
        # Los 48 períodos de MODOM son DOS días de 24 h (horizonte de 48 h, e_sets
        # N=1*48), NO medias-horas: cada bloque de 24 trae su propia campana solar.
        # La demanda es de 1 día (24 bloques), así que se toma el DÍA 1 (primeros 24
        # períodos) para alinear con el reloj y con la demanda.
        n = len(snapshot_ids)
        sliced_rows = [
            {
                "generator_id": item["generator_id"],
                "generator_name_sheet": item["generator_name_sheet"],
                "values_mw": list(item["values_mw"])[:n],
            }
            for item in rows
        ]
        return {
            "period_labels": period_labels[:n],
            "rows": sliced_rows,
            "time_alignment_method": "first_day_24_of_48",
        }

    raise ValueError("El eje temporal de la hoja de generación no coincide con `snapshots`.")


def build_generator_availability(reader: XlsmReader) -> dict[str, object]:
    generator_payload = build_generators(reader)
    snapshots_payload = build_snapshots(reader)
    parsed = parse_wide_generator_sheet(
        reader,
        "Reporte de Disponibilidad",
        header_row_idx=0,
        data_start_row_idx=1,
        generator_id_col=0,
        generator_name_col=1,
        first_period_col=2,
    )

    generators = {
        str(row["generator_id"]): row for row in generator_payload["generators"]
    }
    snapshot_ids = [str(row["snapshot_id"]) for row in snapshots_payload["snapshots"]]
    aligned = align_generator_rows_to_snapshots(parsed, snapshot_ids)
    period_labels = aligned["period_labels"]
    parsed_rows = aligned["rows"]

    availability_rows: list[dict[str, object]] = []
    matched_ids: set[str] = set()
    sheet_ids = set(parsed["unique_ids"])

    for item in parsed_rows:
        generator_id = str(item["generator_id"])
        if generator_id not in generators:
            continue
        matched_ids.add(generator_id)
        generator = generators[generator_id]
        pmax_mw = to_float(str(generator.get("pmax_mw", "")))
        for period_order, (period_label, snapshot_id, available_mw) in enumerate(
            zip(period_labels, snapshot_ids, item["values_mw"]),
            start=1,
        ):
            availability_rows.append(
                {
                    "generator_id": generator_id,
                    "generator_name": generator.get("generator_name", ""),
                    "snapshot_id": snapshot_id,
                    "snapshot_order": period_order,
                    "snapshot_label_modom": period_label,
                    "time_block_group": "canonical_hours_24h",
                    "available_mw": available_mw,
                    "static_pmax_mw": pmax_mw if pmax_mw is not None else "",
                    "available_pu": (
                        available_mw / pmax_mw
                        if pmax_mw not in (None, 0.0)
                        else ""
                    ),
                    "source_sheet": "Reporte de Disponibilidad",
                }
            )

    availability_rows.sort(key=lambda item: (str(item["generator_id"]), int(item["snapshot_order"])))
    summary = {
        "source_sheets": ["Reporte de Disponibilidad", "e_datgen", "e_sets"],
        "counts": {
            "generator_availability_row_count": len(availability_rows),
            "sheet_generator_count": len(sheet_ids),
            "matched_generator_count": len(matched_ids),
            "sheet_only_generator_count": len(sheet_ids - set(generators)),
            "catalog_only_generator_count": len(set(generators) - sheet_ids),
            "snapshot_count": len(snapshot_ids),
        },
        "consistency_flags": {
            "sheet_period_count_matches_snapshots": len(period_labels) == len(snapshot_ids),
            "all_catalog_generators_present_in_sheet": len(set(generators) - sheet_ids) == 0,
        },
        "time_alignment": {
            "source_period_count": len(parsed["period_labels"]),
            "canonical_snapshot_count": len(snapshot_ids),
            "method": aligned["time_alignment_method"],
        },
        "reconciliation": {
            "sheet_only_generator_sample": sorted(sheet_ids - set(generators))[:20],
            "catalog_only_generator_sample": sorted(set(generators) - sheet_ids)[:20],
        },
    }
    return {"rows": availability_rows, "summary": summary}


def build_renewable_profiles(reader: XlsmReader) -> dict[str, object]:
    generator_payload = build_generators(reader)
    snapshots_payload = build_snapshots(reader)
    parsed = parse_wide_generator_sheet(
        reader,
        "Pronostico Renovable",
        header_row_idx=0,
        data_start_row_idx=1,
        generator_id_col=0,
        generator_name_col=1,
        first_period_col=2,
    )
    total_renewable = parse_wide_generator_sheet(
        reader,
        "Total Renovable",
        header_row_idx=0,
        data_start_row_idx=1,
        generator_id_col=4,
        generator_name_col=5,
        first_period_col=6,
    )

    generators = {
        str(row["generator_id"]): row for row in generator_payload["generators"]
    }
    snapshot_ids = [str(row["snapshot_id"]) for row in snapshots_payload["snapshots"]]
    aligned = align_generator_rows_to_snapshots(parsed, snapshot_ids)
    period_labels = aligned["period_labels"]
    parsed_rows = aligned["rows"]

    profile_rows: list[dict[str, object]] = []
    matched_ids: set[str] = set()
    forecast_ids = set(parsed["unique_ids"])
    total_ids = set(total_renewable["unique_ids"])

    for item in parsed_rows:
        generator_id = str(item["generator_id"])
        if generator_id not in generators:
            continue
        matched_ids.add(generator_id)
        generator = generators[generator_id]
        pmax_mw = to_float(str(generator.get("pmax_mw", "")))
        for period_order, (period_label, snapshot_id, forecast_mw) in enumerate(
            zip(period_labels, snapshot_ids, item["values_mw"]),
            start=1,
        ):
            profile_rows.append(
                {
                    "generator_id": generator_id,
                    "generator_name": generator.get("generator_name", ""),
                    "snapshot_id": snapshot_id,
                    "snapshot_order": period_order,
                    "snapshot_label_modom": period_label,
                    "time_block_group": "canonical_hours_24h",
                    "forecast_mw": forecast_mw,
                    "static_pmax_mw": pmax_mw if pmax_mw is not None else "",
                    "forecast_pu": (
                        forecast_mw / pmax_mw
                        if pmax_mw not in (None, 0.0)
                        else ""
                    ),
                    "source_sheet": "Pronostico Renovable",
                }
            )

    profile_rows.sort(key=lambda item: (str(item["generator_id"]), int(item["snapshot_order"])))
    summary = {
        "source_sheets": [
            "Pronostico Renovable",
            "Total Renovable",
            "e_datgen",
            "e_sets",
        ],
        "counts": {
            "renewable_profiles_row_count": len(profile_rows),
            "forecast_generator_count": len(forecast_ids),
            "matched_generator_count": len(matched_ids),
            "forecast_only_generator_count": len(forecast_ids - set(generators)),
            "catalog_only_generator_count": len(set(generators) - forecast_ids),
            "total_renovable_generator_count": len(total_ids),
            "total_renovable_only_generator_count": len(total_ids - forecast_ids),
            "snapshot_count": len(snapshot_ids),
        },
        "consistency_flags": {
            "sheet_period_count_matches_snapshots": len(period_labels) == len(snapshot_ids),
            "all_forecast_ids_exist_in_generators": len(forecast_ids - set(generators)) == 0,
        },
        "time_alignment": {
            "source_period_count": len(parsed["period_labels"]),
            "canonical_snapshot_count": len(snapshot_ids),
            "method": aligned["time_alignment_method"],
        },
        "reconciliation": {
            "forecast_only_generator_sample": sorted(forecast_ids - set(generators))[:20],
            "catalog_only_generator_sample": sorted(set(generators) - forecast_ids)[:20],
            "total_renovable_only_generator_sample": sorted(total_ids - forecast_ids)[:20],
        },
    }
    return {"rows": profile_rows, "summary": summary}


def export_generator_time_series(xlsm_path: Path, outroot: Path) -> dict[str, object]:
    reader = XlsmReader(xlsm_path)
    availability_payload = build_generator_availability(reader)
    renewable_payload = build_renewable_profiles(reader)

    availability_dir = outroot / "generator_availability"
    renewable_dir = outroot / "renewable_profiles"

    write_csv(
        availability_dir / "generator_availability.csv",
        availability_payload["rows"],
        fieldnames=[
            "generator_id",
            "generator_name",
            "snapshot_id",
            "snapshot_order",
            "snapshot_label_modom",
            "time_block_group",
            "available_mw",
            "static_pmax_mw",
            "available_pu",
            "source_sheet",
        ],
    )
    write_json(
        availability_dir / "generator_availability_summary.json",
        availability_payload["summary"],
    )

    write_csv(
        renewable_dir / "renewable_profiles.csv",
        renewable_payload["rows"],
        fieldnames=[
            "generator_id",
            "generator_name",
            "snapshot_id",
            "snapshot_order",
            "snapshot_label_modom",
            "time_block_group",
            "forecast_mw",
            "static_pmax_mw",
            "forecast_pu",
            "source_sheet",
        ],
    )
    write_json(
        renewable_dir / "renewable_profiles_summary.json",
        renewable_payload["summary"],
    )

    return {
        "generator_availability": availability_payload,
        "renewable_profiles": renewable_payload,
    }

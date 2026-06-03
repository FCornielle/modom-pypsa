from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.generator_time_series import export_generator_time_series


def _worksheet_xml(rows: list[list[str]]) -> str:
    max_col = max((len(row) for row in rows), default=1)
    max_row = len(rows) if rows else 1

    def col_letter(index: int) -> str:
        out = []
        while index > 0:
            index, rem = divmod(index - 1, 26)
            out.append(chr(65 + rem))
        return "".join(reversed(out))

    def cell_ref(row_idx: int, col_idx: int) -> str:
        return f"{col_letter(col_idx)}{row_idx}"

    xml_rows: list[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            if not value:
                continue
            cells.append(
                f'<c r="{cell_ref(row_idx, col_idx)}" t="inlineStr"><is><t>{value}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    dim_ref = f"A1:{col_letter(max_col)}{max_row}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dim_ref}"/>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )


def _build_test_workbook(path: Path) -> None:
    sheet_names = [
        "e_sets",
        "MAPEO TODAS LAS BARRAS",
        "e_datred",
        "e_datgen",
        "MAPEO CENTRALES DE GENERACION",
        "Factores de Nodo (Inyección)",
        "Centrales (Zonas)",
        "Reporte de Disponibilidad",
        "Pronostico Renovable",
        "Total Renovable",
        "PDemanda",
    ]
    rows_by_sheet = {
        "e_sets": [
            ["SETS"],
            [""],
            ["PD", "", "", "periodos", "/", "pd001*pd007", "/", ""],
            ["N", "", "", "horizonte de estudio", "/", "1*8", "/", ""],
        ],
        "MAPEO TODAS LAS BARRAS": [
            ["ORG", "", "", "", ""],
            ["MAPEO", "", "", "", ""],
            [""],
            ["CODIGO VIEJO", "NOMBRE VIEJO", "CODIGO NUEVO", "NOMBRE NUEVO", "CAMBIO EL CODIGO?"],
            ["WOLD1", "BUS OLD 1", "WGEN1E", "BUS GEN 1", "NO"],
            ["WOLD2", "BUS OLD 2", "WREN1E", "BUS REN 1", "NO"],
        ],
        "e_datred": [
            ["22", "12", "12"],
            ["TABLE", "", "DATRED"],
            ["", "", "", "", "", "", "r", "x", "flmx", "status", "csl"],
            ["WGEN1E", ".", "WREN1E", ".", "L1", "", "0", "0.1", "10", "1", "1"],
        ],
        "e_datgen": [
            ["22", "12", "12"],
            ["TABLE", "DATGEN", ""],
            [""],
            ["", "YN", "PMX", "PMN", "CVP", "TCG", "SSAA", "MRPF", "MRSF", "FACTORA", "H_P", "PGN"],
            ["G3THERM", "1", "100", "20", "100", "1", "0.02", "1", "2", "3", "4", "5"],
            ["G3REN01", "1", "50", "0", "0", "4", "0.02", "", "", "", "", ""],
            ["+", "", "", "", "", "", "", "", "", "", "", ""],
        ],
        "MAPEO CENTRALES DE GENERACION": [
            ["ORG", "", "", ""],
            ["MAPEO", "", "", ""],
            [""],
            ["CODIGO VIEJO", "CODIGO NUEVO", "NOMBRE CENTRAL O MODALIDAD", "CAMBIO EL CODIGO?"],
            ["G3THERM", "G3THERM", "TERMICA TEST", "NO"],
            ["G3REN01", "G3REN01", "RENOVABLE TEST", "NO"],
        ],
        "Factores de Nodo (Inyección)": [
            ["FACTORES", "", "", ""],
            ["CÓDIGO", "CENTRAL", "BARRA TRANSACCIONAL", "ID SMC"],
            ["G3THERM", "TERMICA TEST", "WGEN1E", "1000-THERM-01"],
            ["G3REN01", "RENOVABLE TEST", "WREN1E", "1000-REN-01"],
        ],
        "Centrales (Zonas)": [
            ["Name", "Grid", "Type", "Terminal", "Terminal"],
            ["", "", "", "", ""],
        ],
        "Reporte de Disponibilidad": [
            ["Siglas", "Central", "1", "2", "3", "4", "5", "6", "7", "8"],
            ["G3THERM", "TERMICA TEST", "80", "100", "100", "80", "60", "40", "20", "0"],
            ["G3REN01", "RENOVABLE TEST", "10", "20", "30", "40", "50", "60", "70", "80"],
            ["G9EXTRA", "EXTRA", "1", "1", "1", "1", "1", "1", "1", "1"],
        ],
        "Pronostico Renovable": [
            ["Siglas", "Central", "1", "2", "3", "4", "5", "6", "7", "8"],
            ["G3REN01", "RENOVABLE TEST", "5", "15", "10", "20", "15", "25", "20", "30"],
        ],
        "Total Renovable": [
            ["Disponibilidad", "Incluir en limitación", "Factor de planta", "PRON Agente", "Siglas", "Central", "1", "2", "3", "4", "5", "6", "7", "8"],
            ["1", "1", "0", "0", "G3REN01", "RENOVABLE TEST", "5", "15", "10", "20", "15", "25", "20", "30"],
            ["1", "1", "0", "0", "G3BIO01", "BIOMASA TEST", "7", "7", "7", "7", "7", "7", "7", "7"],
        ],
        "PDemanda": [
            ["load_id", "1", "2", "3", "4"],
            ["ZLOAD1-D1", "1", "1", "1", "1"],
        ],
    }

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        + "".join(
            f'<sheet name="{name}" sheetId="{idx}" r:id="rId{idx}"/>'
            for idx, name in enumerate(sheet_names, start=1)
        )
        + "</sheets></workbook>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
            for idx in range(1, len(sheet_names) + 1)
        )
        + "</Relationships>"
    )

    with ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        for idx, name in enumerate(sheet_names, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", _worksheet_xml(rows_by_sheet[name]))


def test_export_generator_time_series(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outroot = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_generator_time_series(xlsm_path, outroot)

    availability_counts = payload["generator_availability"]["summary"]["counts"]
    assert availability_counts["generator_availability_row_count"] == 8
    assert availability_counts["matched_generator_count"] == 2
    assert availability_counts["sheet_only_generator_count"] == 1

    renewable_counts = payload["renewable_profiles"]["summary"]["counts"]
    assert renewable_counts["renewable_profiles_row_count"] == 4
    assert renewable_counts["matched_generator_count"] == 1
    assert renewable_counts["total_renovable_only_generator_count"] == 1

    # Eje 8->4: se toma el DÍA 1 (primeros 4 períodos), no el promedio de parejas.
    therm_h1 = next(
        row
        for row in payload["generator_availability"]["rows"]
        if row["generator_id"] == "G3THERM" and row["snapshot_id"] == "h_01"
    )
    assert therm_h1["available_mw"] == 80.0   # período 1 del día 1
    assert therm_h1["available_pu"] == 0.8
    assert payload["generator_availability"]["summary"]["time_alignment"]["method"] == "first_day_24_of_48"

    ren_h4 = next(
        row
        for row in payload["renewable_profiles"]["rows"]
        if row["generator_id"] == "G3REN01" and row["snapshot_id"] == "h_04"
    )
    assert ren_h4["forecast_mw"] == 20.0   # período 4 del día 1
    assert ren_h4["forecast_pu"] == 0.4

    summary_path = (
        outroot / "renewable_profiles" / "renewable_profiles_summary.json"
    )
    summary_json = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary_json["consistency_flags"]["all_forecast_ids_exist_in_generators"] is True

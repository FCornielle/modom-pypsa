from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.loads import canonicalize_load_id, export_loads_time_series


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
    sheet_names = ["PDemanda", "e_datdem", "DEMANDA SMC"]
    rows_by_sheet = {
        "PDemanda": [
            ["NOMBRE", "1", "2"],
            ["ZTESTF-D1", "1.0", "2.0"],
            ["ZTESTF-D2", "3.0", "4.0"],
            ["WOTROF-D1", "5.0", "6.0"],
        ],
        "e_datdem": [
            ["22", "12", "12"],
            ["TABLE", "DATDEM", ""],
            [""],
            ["*MARTES"],
            ["", "", "dm.1"],
            ["WTESTF", "", "1.0"],
            ["WOTROF", "", "2.0"],
        ],
        "DEMANDA SMC": [
            ["IDCARGA", "INICIO", "FIN", "ESTATUS", "OPERADOR", "IDDISILENT", "IDBARRA", "NOMBRE", "TIPO", "H1", "H2"],
            ["1000-TESTF-T01", "", "", "Activo", "+", "ZTESTF-D1", "WTESTF", "TEST 1", "Declarado", "1.0", "2.0"],
            ["1000-TESTF-T02", "", "", "Activo", "+", "ZTESTF-D2", "WTESTF", "TEST 2", "Declarado", "3.0", "4.0"],
            ["1000-OTROF-T01", "", "", "Activo", "+", "WOTROF-D1", "WOTROF", "OTRO", "Declarado", "5.0", "6.0"],
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


def test_canonicalize_load_id() -> None:
    assert canonicalize_load_id("ZADOMF-D1") == "WADOMF"
    assert canonicalize_load_id("WOTROF-D2") == "WOTROF"


def test_export_loads_time_series(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outdir = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_loads_time_series(xlsm_path, outdir)

    assert len(payload["raw_long_rows"]) == 6
    assert len(payload["loads_time_series"]) == 4
    assert len(payload["smc_load_registry"]) == 3

    first = payload["loads_time_series"][0]
    assert first["load_id"] == "WOTROF"
    assert first["load_id_source"] == "resolved_bus_id"
    testf_h1 = next(
        row
        for row in payload["loads_time_series"]
        if row["load_id"] == "WTESTF" and row["time_block_id"] == "h_01"
    )
    assert testf_h1["p_set_mw"] == 4.0
    assert testf_h1["aggregation_row_count"] == 2
    assert testf_h1["bus_resolution_method_examples"] == "unique_bus_in_demanda_smc"

    summary_path = outdir / "loads_time_series_reconciliation_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["counts"]["loads_time_series_load_count"] == 2
    assert summary["reconciliation"]["canonical_vs_e_datdem_exact_overlap_count"] == 2

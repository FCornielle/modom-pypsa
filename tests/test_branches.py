from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.branches import export_branches, infer_branch_type


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
    sheet_names = ["MAPEO TODAS LAS BARRAS", "e_datred"]
    rows_by_sheet = {
        "MAPEO TODAS LAS BARRAS": [
            ["ORG", "", "", "", ""],
            ["MAPEO", "", "", "", ""],
            ["CODIGO VIEJO", "NOMBRE VIEJO", "CODIGO NUEVO", "NOMBRE NUEVO", "CAMBIO EL CODIGO?"],
            ["WOLD1", "BUS OLD 1", "WNEW1", "BUS NEW 1", "SI"],
            ["WOLD2", "BUS OLD 2", "WNEW2", "BUS NEW 2", "NO"],
        ],
        "e_datred": [
            ["22", "12", "12"],
            ["TABLE", "", "DATRED"],
            ["", "", "", "", "", "", "r", "x", "flmx", "status", "csl"],
            ["WNEW1", ".", "WNEW2", ".", "L1", "", "0", "0.1", "10", "1", "1"],
            ["WNEW2", ".", "WEXTRA1", ".", "T1", "", "0.01", "0.2", "20", "0", "1"],
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


def test_infer_branch_type() -> None:
    assert infer_branch_type("L1") == "line"
    assert infer_branch_type("T1") == "transformer"


def test_export_branches(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outdir = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_branches(xlsm_path, outdir)

    assert len(payload["branches"]) == 2
    summary = payload["summary"]["counts"]
    assert summary["line_count"] == 1
    assert summary["transformer_count"] == 1
    assert summary["missing_bus_reference_count"] == 0
    assert summary["duplicate_branch_base_id_count"] == 0

    transformer = next(row for row in payload["branches"] if row["branch_type"] == "transformer")
    assert transformer["to_bus"] == "WEXTRA1"
    assert transformer["to_bus_in_buses"] is True
    assert transformer["branch_parallel_index"] == 1

    summary_path = outdir / "branches_reconciliation_summary.json"
    assert summary_path.exists()
    summary_json = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary_json["consistency_flags"]["all_branch_endpoints_resolved_in_buses"] is True

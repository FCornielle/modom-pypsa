from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.workbook_inventory import export_workbook_inventory


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
    sheet_names = ["e_sets", "e_datred", "e_datgen", "e_datdem", "PDemanda"]
    sheet_targets = {
        name: f"worksheets/sheet{idx}.xml" for idx, name in enumerate(sheet_names, start=1)
    }
    rows_by_sheet = {
        "e_sets": [
            ["titulo"],
            ["nota"],
            ["periodo", "etiqueta", "fecha"],
            ["1", "h_1", "2026-05-31"],
            ["2", "h_2", "2026-05-31"],
        ],
        "e_datred": [
            ["meta"],
            ["otra"],
            ["barra", "desde", "hasta"],
            ["L1", "B1", "B2"],
        ],
        "e_datgen": [
            ["meta"],
            ["otra"],
            ["otra"],
            ["gen_id", "barra", "pmax"],
            ["G1", "B1", "100"],
        ],
        "e_datdem": [
            ["meta"],
            ["otra"],
            ["otra"],
            ["otra"],
            ["carga", "barra", "p_mw"],
            ["D1", "B2", "10"],
        ],
        "PDemanda": [
            ["load_id", "h_1", "h_2"],
            ["D1", "10", "11"],
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
            f'Target="{sheet_targets[name]}"/>'
            for idx, name in enumerate(sheet_names, start=1)
        )
        + "</Relationships>"
    )

    with ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        for idx, name in enumerate(sheet_names, start=1):
            zf.writestr(f"xl/worksheets/sheet{idx}.xml", _worksheet_xml(rows_by_sheet[name]))


def test_export_workbook_inventory(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outdir = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_workbook_inventory(xlsm_path=xlsm_path, outdir=outdir, preview_rows=2)

    assert payload["sheet_count"] == 5
    assert payload["focus_sheet_names"] == [
        "e_sets",
        "e_datred",
        "e_datgen",
        "e_datdem",
        "PDemanda",
    ]

    inventory_path = outdir / "sheet_inventory.csv"
    workbook_json = outdir / "workbook_inventory.json"
    focus_json = outdir / "focus_sheets" / "pdemanda.json"
    focus_preview = outdir / "focus_sheets" / "pdemanda_preview.csv"

    assert inventory_path.exists()
    assert workbook_json.exists()
    assert focus_json.exists()
    assert focus_preview.exists()

    exported = json.loads(workbook_json.read_text(encoding="utf-8"))
    pdemanda_summary = next(
        item for item in exported["focus_sheets"] if item["sheet_name"] == "PDemanda"
    )
    assert pdemanda_summary["resolved_header_row_trimmed_1_based"] == 1
    assert pdemanda_summary["first_useful_columns"] == ["load_id", "h_1", "h_2"]

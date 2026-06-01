from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.snapshots import export_snapshots


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
    sheet_names = ["e_sets", "PDemanda"]
    rows_by_sheet = {
        "e_sets": [
            ["SETS"],
            [""],
            ["PD", "", "", "periodos", "/", "pd001*pd007", "/", ""],
            ["N", "", "", "horizonte de estudio", "/", "1*48", "/", ""],
        ],
        "PDemanda": [
            ["NOMBRE", "1", "2", "3", "4"],
            ["LOAD_1", "10", "11", "12", "13"],
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


def test_export_snapshots(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outdir = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_snapshots(xlsm_path, outdir)

    assert len(payload["snapshots"]) == 4
    assert payload["snapshots"][0]["snapshot_id"] == "h_01"
    assert payload["horizon_summary"]["dispatch_horizon"]["range_spec"] == "1*48"
    assert payload["horizon_summary"]["load_profile_horizon"]["block_count"] == 4
    assert payload["horizon_summary"]["consistency_flags"]["canonical_v1_uses_24h_load_blocks"]
    assert payload["horizon_summary"]["consistency_flags"][
        "requires_operational_48_to_24_translation"
    ]

    snapshots_csv = outdir / "snapshots.csv"
    summary_json = outdir / "snapshot_horizon_summary.json"
    assert snapshots_csv.exists()
    assert summary_json.exists()

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["dispatch_horizon"]["period_count"] == 48
    assert summary["canonical_horizon_v1"]["block_count"] == 4
    assert summary["load_profile_horizon"]["block_labels"] == ["1", "2", "3", "4"]

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from modom_pypsa.buses import export_buses, infer_bus_voltage, normalize_bus_code


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
            ["WOLDC", "BUS OLD C", "WNEWC", "BUS NEW C", "NO"],
            ["WOLDE", "BUS OLD E", "WNEWE", "BUS NEW E 138 KV", "NO"],
        ],
        "e_datred": [
            ["22", "12", "12"],
            ["TABLE", "", "DATRED"],
            ["", "", "", "", "", "", "r", "x", "flmx", "status", "csl"],
            ["WNEW1", ".", "WEXTRA1", ".", "L1", "", "0", "0.1", "10", "1", "1"],
            ["* WEXTRA1", ".", "WNEW2", ".", "L1", "", "0", "0.1", "10", "1", "1"],
            ["WNEWC", ".", "WNEWE", ".", "T1", "", "0", "0.1", "10", "1", "1"],
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


def test_normalize_bus_code() -> None:
    assert normalize_bus_code("* WEXTRA1") == "WEXTRA1"
    assert normalize_bus_code(" WNEW1 ") == "WNEW1"


def test_infer_bus_voltage() -> None:
    assert infer_bus_voltage("WBON2E", "", "") == (138.0, "suffix_E_default", "medium")
    assert infer_bus_voltage("WBON2F", "", "") == (69.0, "suffix_F_default", "medium")
    assert infer_bus_voltage("WCTP1D", "PUNTA CATALINA 1 345 KV BARRA 1", "") == (
        345.0,
        "name_explicit",
        "high",
    )
    assert infer_bus_voltage("WLMI7K", "LOS MINA 7 13.5", "") == (
        13.5,
        "name_explicit",
        "high",
    )
    assert infer_bus_voltage("WNEW2", "BUS NEW 2", "") == (None, "unresolved", "low")


def test_export_buses(tmp_path: Path) -> None:
    xlsm_path = tmp_path / "sample.xlsm"
    outdir = tmp_path / "out"
    _build_test_workbook(xlsm_path)

    payload = export_buses(xlsm_path, outdir)

    assert len(payload["buses"]) == 5
    summary = payload["summary"]["counts"]
    assert summary["mapping_bus_count"] == 4
    assert summary["e_datred_bus_count"] == 5
    assert summary["e_datred_only_bus_count"] == 1
    assert summary["mapping_only_bus_count"] == 0

    extra = next(row for row in payload["buses"] if row["bus_id_modom"] == "WEXTRA1")
    assert extra["bus_origin"] == "e_datred_only"
    assert extra["e_datred_endpoint_count"] == 2
    assert extra["v_nom_kv"] == ""
    assert extra["v_nom_inference_method"] == "unresolved"
    assert extra["v_nom_confidence"] == "low"

    mapped = next(row for row in payload["buses"] if row["bus_id_modom"] == "WNEW2")
    assert mapped["v_nom_kv"] == ""
    assert mapped["v_nom_inference_method"] == "unresolved"

    topology_bus = next(row for row in payload["buses"] if row["bus_id_modom"] == "WNEWC")
    assert topology_bus["v_nom_kv"] == 138.0
    assert topology_bus["v_nom_inference_method"] == "topology_transformer_consensus"
    assert topology_bus["v_nom_confidence"] == "low"

    summary_path = outdir / "buses_reconciliation_summary.json"
    assert summary_path.exists()
    summary_json = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary_json["counts"]["mapping_and_e_datred_overlap_count"] == 4
    assert summary_json["counts"]["buses_with_v_nom_kv_count"] == 2
    assert summary_json["counts"]["buses_without_v_nom_kv_count"] == 3
    assert summary_json["counts"]["v_nom_topology_transformer_consensus_count"] == 1
    assert summary_json["consistency_flags"]["all_buses_have_v_nom_kv"] is False

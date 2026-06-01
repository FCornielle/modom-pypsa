"""Lectura reproducible de workbooks XLSM de MODOM sin ejecutar macros.

El proyecto trata el `.xlsm` como un contenedor Office Open XML. La lectura se
hace directamente sobre el XML interno para evitar depender de Excel, VBA o
componentes gráficos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)")
DIMENSION_REF_RE = re.compile(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?")


def col_to_num(col: str) -> int:
    """Convierte columnas Excel tipo `AA` a índice 1-based."""
    value = 0
    for ch in col:
        value = value * 26 + ord(ch) - 64
    return value


def num_to_col(value: int) -> str:
    """Convierte índices 1-based a letras de columna Excel."""
    out: list[str] = []
    while value > 0:
        value, rem = divmod(value - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


def trim_matrix(matrix: list[list[str]]) -> list[list[str]]:
    """Recorta filas y columnas completamente vacías del borde de la matriz."""
    non_empty_rows = [
        idx for idx, row in enumerate(matrix) if any(str(cell).strip() for cell in row)
    ]
    if not non_empty_rows:
        return []

    start_row = non_empty_rows[0]
    end_row = non_empty_rows[-1]
    relevant = matrix[start_row : end_row + 1]

    non_empty_cols = [
        idx
        for idx in range(max(len(row) for row in relevant))
        if any(idx < len(row) and str(row[idx]).strip() for row in relevant)
    ]
    if not non_empty_cols:
        return []

    start_col = non_empty_cols[0]
    end_col = non_empty_cols[-1]
    return [row[start_col : end_col + 1] for row in relevant]


def normalize_header(value: str, fallback_col: int) -> str:
    """Normaliza encabezados de hoja a nombres de columna estables."""
    text = str(value or "").strip()
    if not text:
        return f"col_{num_to_col(fallback_col)}"
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-zÁÉÍÓÚÑáéíóúñ_()./-]+", "", text)
    return text or f"col_{num_to_col(fallback_col)}"


def matrix_to_structured_rows(
    matrix: list[list[str]],
    header_row: int,
) -> tuple[list[str], list[dict[str, str]]]:
    """Transforma una matriz recortada a filas estructuradas.

    `header_row` es 1-based respecto a la matriz ya recortada.
    """
    if not matrix or len(matrix) < header_row:
        return ([], [])

    header = matrix[header_row - 1]
    headers = [normalize_header(value, idx + 1) for idx, value in enumerate(header)]
    rows: list[dict[str, str]] = []
    for row in matrix[header_row:]:
        if not any(str(cell).strip() for cell in row):
            continue
        item = {
            headers[idx]: row[idx] if idx < len(row) else ""
            for idx in range(len(headers))
        }
        rows.append(item)
    return (headers, rows)


@dataclass(frozen=True)
class WorkbookSheet:
    """Metadatos básicos de una hoja del workbook."""

    sheet_index: int
    sheet_name: str
    dimension_ref: str | None
    row_count_trimmed: int
    col_count_trimmed: int


class XlsmReader:
    """Lector de hojas XLSM basado en XML interno del archivo Office."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zf = ZipFile(path)
        self.shared_strings = self._load_shared_strings()
        self.sheet_targets = self._load_sheet_targets()

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.zf.namelist():
            return []
        root = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
        out = []
        for si in root.findall(f"{XML_NS}si"):
            out.append("".join(t.text or "" for t in si.iter(f"{XML_NS}t")))
        return out

    def _load_sheet_targets(self) -> dict[str, str]:
        workbook = ET.fromstring(self.zf.read("xl/workbook.xml"))
        rels = ET.fromstring(self.zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        targets: dict[str, str] = {}
        for sheet in workbook.find(f"{XML_NS}sheets"):
            rid = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            targets[sheet.attrib["name"]] = "xl/" + relmap[rid]
        return targets

    def workbook_sheet_names(self) -> list[str]:
        return list(self.sheet_targets.keys())

    def read_sheet_dimension(self, sheet_name: str) -> tuple[str | None, int, int]:
        """Lee el rango usado declarado por la hoja sin materializar toda la matriz."""
        target = self.sheet_targets[sheet_name]
        root = ET.fromstring(self.zf.read(target))
        dimension = root.find(f"{XML_NS}dimension")
        if dimension is None:
            return (None, 0, 0)

        ref = dimension.attrib.get("ref", "").strip()
        if not ref:
            return (None, 0, 0)

        match = DIMENSION_REF_RE.fullmatch(ref)
        if not match:
            return (ref, 0, 0)

        start_col, start_row, end_col, end_row = match.groups()
        end_col = end_col or start_col
        end_row = end_row or start_row
        row_count = int(end_row) - int(start_row) + 1
        col_count = col_to_num(end_col) - col_to_num(start_col) + 1
        return (ref, row_count, col_count)

    def read_sheet_matrix(self, sheet_name: str) -> list[list[str]]:
        target = self.sheet_targets[sheet_name]
        root = ET.fromstring(self.zf.read(target))
        rows_data: dict[int, dict[int, str]] = {}
        max_col = 0

        for row in root.findall(f".//{XML_NS}sheetData/{XML_NS}row"):
            row_idx = int(row.attrib["r"])
            current: dict[int, str] = {}
            for cell in row.findall(f"{XML_NS}c"):
                ref = cell.attrib.get("r", "")
                match = CELL_REF_RE.match(ref)
                if not match:
                    continue
                col_idx = col_to_num(match.group(1))
                current[col_idx] = self._cell_value(cell)
                max_col = max(max_col, col_idx)
            if current:
                rows_data[row_idx] = current

        if not rows_data:
            return []

        max_row = max(rows_data)
        matrix: list[list[str]] = []
        for row_idx in range(1, max_row + 1):
            row_map = rows_data.get(row_idx, {})
            matrix.append(
                [row_map.get(col_idx, "") for col_idx in range(1, max_col + 1)]
            )
        return trim_matrix(matrix)

    def _cell_value(self, cell: ET.Element) -> str:
        cell_type = cell.attrib.get("t")
        value = cell.find(f"{XML_NS}v")
        inline = cell.find(f"{XML_NS}is")

        if cell_type == "s" and value is not None:
            idx = int(value.text)
            return self.shared_strings[idx] if idx < len(self.shared_strings) else ""
        if cell_type == "inlineStr" and inline is not None:
            return "".join(node.text or "" for node in inline.iter(f"{XML_NS}t"))
        if value is not None:
            return value.text or ""
        return ""

    def build_sheet_inventory(self) -> list[WorkbookSheet]:
        inventory: list[WorkbookSheet] = []
        for idx, sheet_name in enumerate(self.workbook_sheet_names(), start=1):
            dimension_ref, row_count, col_count = self.read_sheet_dimension(sheet_name)
            inventory.append(
                WorkbookSheet(
                    sheet_index=idx,
                    sheet_name=sheet_name,
                    dimension_ref=dimension_ref,
                    row_count_trimmed=row_count,
                    col_count_trimmed=col_count,
                )
            )
        return inventory

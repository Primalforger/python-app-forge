from pathlib import Path

import pytest

from app_forge.table_exports import export_pdf, export_xlsx


class Column:
    def __init__(self, key, title="", visible=True):
        self.key, self.title, self.visible = key, title, visible


class Model:
    columns = [Column("name", "Name"), Column("secret", "Secret", False), Column("amount", "Amount")]

    def __init__(self):
        self._rows = [
            {"name": "alpha", "secret": "hidden", "amount": 4, "_id": 0},
            {"name": "=1+1", "secret": "hidden too", "amount": 7, "_id": 1},
        ]
        self.selection = {1}

    def result_rows(self):
        return list(self._rows)

    def selected_rows(self):
        return [row for row in self.result_rows() if row["_id"] in self.selection]


def test_xlsx_exports_visible_filtered_rows_and_freezes_header(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = export_xlsx(Model(), tmp_path / "nested" / "table.xlsx")
    workbook = openpyxl.load_workbook(path, data_only=False)
    sheet = workbook.active
    assert list(sheet.values) == [("Name", "Amount"), ("alpha", 4), ("=1+1", 7)]
    assert sheet["A3"].data_type == "s"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:B3"


def test_xlsx_can_export_only_selected_rows(tmp_path):
    pytest.importorskip("openpyxl")
    path = export_xlsx(Model(), tmp_path / "selected.xlsx", only_selected=True)
    import openpyxl
    sheet = openpyxl.load_workbook(path).active
    assert list(sheet.values) == [("Name", "Amount"), ("=1+1", 7)]


def test_pdf_export_creates_valid_document_and_escapes_cell_markup(tmp_path):
    pytest.importorskip("reportlab")
    path = export_pdf(Model(), tmp_path / "table.pdf", title="Results <today>")
    assert path.read_bytes().startswith(b"%PDF-")
    assert path.stat().st_size > 500


def test_pdf_export_handles_empty_visible_columns(tmp_path):
    pytest.importorskip("reportlab")
    model = Model()
    model.columns = [Column("name", visible=False)]
    path = export_pdf(model, tmp_path / "empty.pdf")
    assert path.read_bytes().startswith(b"%PDF-")


def test_export_rejects_non_boolean_selection_flag(tmp_path):
    pytest.importorskip("openpyxl")
    with pytest.raises(TypeError, match="only_selected"):
        export_xlsx(Model(), tmp_path / "bad.xlsx", only_selected=1)

"""Regression coverage for importing NpA PDFs into the application store."""

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pymupdf
import pytest

from jobroom_helper.utils.db_helper import ApplicationStore


spec = importlib.util.spec_from_file_location(
    "parse_npa", Path(__file__).resolve().parents[1] / "scripts/parse_npa.py"
)
parse_npa = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = parse_npa
spec.loader.exec_module(parse_npa)


def application_lines(role="Senior Engineer"):
    return [
        "01.05.2026",
        "gespeichert",
        "02.05.2026",
        "Example AG",
        "CH-8000 Zurich",
        role,
        "https://example.com/jobs/1",
        "X",
    ]


def test_pdf_text_extraction_closes_document(tmp_path, monkeypatch):
    path = tmp_path / "applications.pdf"
    with pymupdf.open() as doc:
        for value in ("  First page  ", "Second page"):
            doc.new_page().insert_text((72, 72), value)
        doc.save(path)
    doc = pymupdf.open(path)
    monkeypatch.setattr(parse_npa.pymupdf, "open", lambda _: doc)
    assert parse_npa.iter_pdf_lines(str(path)) == ["First page", "Second page"]
    assert doc.is_closed


def test_pdf_is_closed_when_extraction_fails(monkeypatch):
    doc = MagicMock()
    doc.__enter__.return_value = doc
    page = MagicMock()
    page.get_text.side_effect = RuntimeError("extraction failed")
    doc.__iter__.return_value = iter([page])
    monkeypatch.setattr(parse_npa.pymupdf, "open", lambda _: doc)
    with pytest.raises(RuntimeError, match="extraction failed"):
        parse_npa.iter_pdf_lines("broken.pdf")
    doc.__exit__.assert_called_once()


def test_distinct_source_rows_survive_import_and_rerun(tmp_path):
    # Identical company, date, title and link can represent separate applications.
    lines = application_lines() * 2
    rows = parse_npa.rows_from_starts("05", lines, parse_npa.find_row_starts(lines))
    urls = [parse_npa.build_url(row) for row in rows]
    assert len(set(urls)) == 2
    assert urls == [parse_npa.build_url(row) for row in rows]
    assert parse_npa.build_url(replace(rows[0], month="06")) not in urls
    db_path = str(tmp_path / "applications.db")
    assert parse_npa.insert_rows([rows[0]], db_path) == 1
    assert parse_npa.insert_rows(rows + rows, db_path) == 1
    assert parse_npa.insert_rows(rows, db_path) == 0
    assert len(ApplicationStore(db_path).get_database_data()) == 2


def test_url_requires_source_row_number():
    row = parse_npa.parse_block("05", application_lines(), 0, 8)
    with pytest.raises(ValueError, match="source row number"):
        parse_npa.build_url(row)


def test_missing_pdf_and_unknown_month_continue_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(parse_npa, "MONTHS", ["05", "10"])
    path = tmp_path / "NpA_2026-10.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "\n".join(application_lines()))
        doc.save(path)
    rows, summary = parse_npa.load_rows(str(tmp_path))
    assert len(rows) == 1
    assert summary == [("10", None, 1)]
    parse_npa.print_summary(summary)
    output = capsys.readouterr()
    assert "Skipping missing PDF:" in output.err
    assert "NpA_2026-05.pdf" in output.err
    assert "10" in output.out
    db_path = str(tmp_path / "applications.db")
    assert parse_npa.insert_rows(rows, db_path) == 1
    assert (
        ApplicationStore(db_path).get_database_data().iloc[0]["Source"]
        == "Job-Room (NpA 10)"
    )

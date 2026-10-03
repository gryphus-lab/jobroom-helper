"""Exercise status reconciliation against synthetic SQLite records only."""

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest


SQL = (
    Path(__file__).resolve().parents[1] / "scripts/fix_application_status.sql"
).read_text()
# .bail is a sqlite3 CLI directive; executescript already stops on the first error.
SQL = SQL.replace(".bail on\n", "")
TARGET_URL = "https://example.com/confirmed-application"


@pytest.fixture
def db():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("""CREATE TABLE applications (
            id TEXT, URL TEXT, Company TEXT, Role TEXT, "Applied date" TEXT,
            Stage TEXT, Notes TEXT, "Last Update Date" TEXT,
            "Update Details" TEXT, updated_at TEXT
        )""")
        conn.executemany(
            "INSERT INTO applications (id, URL, Company, Stage, Notes) VALUES (?, ?, ?, ?, ?)",
            [
                ("target", TARGET_URL, "Detecon AG", "Applied", "Confirmed rejection"),
                ("other", "https://example.com/other", "Detecon AG", "Applied", ""),
                (
                    "review",
                    "https://example.com/review",
                    "Example",
                    "Applied",
                    "Unfortunately we will not be able to schedule the interview until next week",
                ),
            ],
        )
        conn.commit()
        yield conn


def configured_sql(url=TARGET_URL):
    expected = "INSERT INTO confirmed_detecon VALUES (NULL, NULL, NULL);"
    assert expected in SQL
    escaped_url = url.replace("'", "''")
    replacement = (
        "INSERT INTO confirmed_detecon VALUES "
        f"('{escaped_url}', NULL, NULL);"
    )
    return SQL.replace(expected, replacement)


def test_configured_sql_escapes_quotes_in_target_url():
    sql = configured_sql("https://example.com/o'brien")
    assert "VALUES ('https://example.com/o''brien', NULL, NULL);" in sql


def test_only_confirmed_target_changes_and_rerun_is_idempotent(db):
    db.executescript(configured_sql())
    assert db.execute("SELECT id, Stage FROM applications ORDER BY id").fetchall() == [
        ("other", "Applied"),
        ("review", "Applied"),
        ("target", "Rejected"),
    ]
    before = db.execute("SELECT * FROM applications ORDER BY id").fetchall()
    db.executescript(configured_sql())
    assert db.execute("SELECT * FROM applications ORDER BY id").fetchall() == before


@pytest.mark.parametrize(
    "sql",
    [SQL, configured_sql("https://example.com/missing")],
    ids=["unset", "missing"],
)
def test_unset_or_missing_target_rolls_back(db, sql):
    with pytest.raises(sqlite3.IntegrityError, match="expected_single_detecon_row"):
        db.executescript(sql)
    assert not db.in_transaction
    assert (
        db.execute(
            "SELECT COUNT(*) FROM applications WHERE Stage = 'Applied'"
        ).fetchone()[0]
        == 3
    )


def test_nonunique_target_rolls_back(db):
    db.execute(
        "INSERT INTO applications (id, URL, Stage) VALUES ('duplicate', ?, 'Applied')",
        [TARGET_URL],
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.executescript(configured_sql())
    assert (
        db.execute(
            "SELECT COUNT(*) FROM applications WHERE Stage = 'Rejected'"
        ).fetchone()[0]
        == 0
    )


def test_unexpected_update_count_rolls_back(db):
    db.execute("""CREATE TRIGGER suppress_update BEFORE UPDATE ON applications
                  BEGIN SELECT RAISE(IGNORE); END""")
    with pytest.raises(sqlite3.IntegrityError):
        db.executescript(configured_sql())
    assert not db.in_transaction
    assert (
        db.execute("SELECT Stage FROM applications WHERE id = 'target'").fetchone()[0]
        == "Applied"
    )


@pytest.mark.parametrize("configured", [False, True])
def test_sqlite_cli_stops_on_invalid_target(db, tmp_path, configured):
    if shutil.which("sqlite3") is None:
        pytest.skip("sqlite3 executable is not available on PATH")
    path = tmp_path / "applications.db"
    with sqlite3.connect(path) as target:
        db.backup(target)
    script = configured_sql() if configured else SQL
    result = subprocess.run(
        ["sqlite3", str(path)],
        input=".bail on\n" + script,
        text=True,
        capture_output=True,
    )
    assert (result.returncode == 0) is configured
    with sqlite3.connect(path) as target:
        stages = dict(target.execute("SELECT id, Stage FROM applications"))
    assert stages == {
        "target": "Rejected" if configured else "Applied",
        "other": "Applied",
        "review": "Applied",
    }

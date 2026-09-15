"""Tests for the local SQLite ApplicationStore."""

import multiprocessing

import pytest

from jobroom_helper.config import get_db_path
from jobroom_helper.utils.db_helper import ApplicationStore, unwrap_property


def _create_page_in_process(db_path, barrier):
    barrier.wait()
    return ApplicationStore(db_path=db_path).create_page(properties=_base_properties())


@pytest.fixture
def store(tmp_path):
    """Return an ApplicationStore backed by a temporary SQLite file."""
    return ApplicationStore(db_path=str(tmp_path / "applications.db"))


def _base_properties(**overrides):
    """Build canonical application properties with optional overrides."""
    props = {
        "Company": "Acme",
        "Role": "Engineer",
        "URL": "https://example.com/job/1",
        "Date": "2026-01-01",
        "Type": "electronic",
        "Applied date": "2026-01-01",
        "Tracked": False,
        "Stage": "Applied",
        "Source": "Company site",
        "Address": "Main Street 1",
    }
    props.update(overrides)
    return props


def test_create_page_inserts_row_and_returns_id(store):
    """Creating an application persists its fields and returns its row id."""
    row_id = store.create_page(properties=_base_properties())

    assert isinstance(row_id, str)
    assert row_id

    df = store.get_database_data()
    assert len(df) == 1
    assert df.loc[0, "id"] == row_id
    assert df.loc[0, "Company"] == "Acme"
    assert df.loc[0, "Role"] == "Engineer"
    assert df.loc[0, "URL"] == "https://example.com/job/1"


def test_create_page_dedups_on_duplicate_url(store, capsys):
    """Repeated creates for one URL reuse the original application row."""
    first_id = store.create_page(properties=_base_properties())
    second_id = store.create_page(properties=_base_properties(Company="Acme Duplicate"))

    assert first_id == second_id
    out = capsys.readouterr().out
    assert "already exists" in out

    df = store.get_database_data()
    assert len(df) == 1
    # The duplicate did not overwrite the original row.
    assert df.loc[0, "Company"] == "Acme"


def test_create_page_concurrent_creates_deduplicate(tmp_path):
    db_path = str(tmp_path / "applications.db")
    ApplicationStore(db_path=db_path)
    context = multiprocessing.get_context("spawn")

    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        with context.Pool(2) as pool:
            row_ids = pool.starmap(
                _create_page_in_process,
                [(db_path, barrier), (db_path, barrier)],
            )

    assert row_ids[0] == row_ids[1]
    assert row_ids[0]
    assert len(ApplicationStore(db_path=db_path).get_database_data()) == 1


def test_get_database_data_returns_expected_columns(store):
    """Database reads expose canonical columns in their declared order."""
    store.create_page(properties=_base_properties())
    df = store.get_database_data()

    expected_columns = {
        "id",
        "Company",
        "Role",
        "URL",
        "Date",
        "Type",
        "Applied date",
        "Tracked",
        "Stage",
        "Source",
        "Notes",
        "Last Update Date",
        "Update Details",
        "Description",
        "Address",
        "Street",
        "Number",
        "POBox",
        "PLZ_Ort",
        "Contact",
        "Email",
        "Phone",
        "RAV",
        "Arbeitspensum",
        "Interview",
        "Status",
    }
    assert expected_columns.issubset(set(df.columns))


def test_get_database_data_empty_returns_columns(store):
    """An empty database still returns the canonical DataFrame schema."""
    df = store.get_database_data()
    assert df.empty
    assert "Company" in df.columns
    assert "id" in df.columns


def test_get_database_data_filters_by_date_and_tracked(store):
    """Combined date and tracking filters select only matching rows."""
    store.create_page(
        properties=_base_properties(
            URL="https://example.com/a", **{"Applied date": "2026-01-05"}
        )
    )
    store.create_page(
        properties=_base_properties(
            URL="https://example.com/b", **{"Applied date": "2026-02-15"}
        )
    )

    month_filter = {
        "and": [
            {"property": "Applied date", "date": {"on_or_after": "2026-01-01"}},
            {"property": "Applied date", "date": {"before": "2026-02-01"}},
            {"property": "Tracked", "checkbox": {"equals": False}},
        ]
    }
    df = store.get_database_data(filter=month_filter)
    assert len(df) == 1
    assert df.loc[0, "URL"] == "https://example.com/a"


def test_get_database_data_filters_tracked_true(store):
    """The tracked filter selects rows whose tracked flag is true."""
    row_id = store.create_page(properties=_base_properties())
    store.update_row(row_id, {"Tracked": {"checkbox": True}})
    store.create_page(properties=_base_properties(URL="https://example.com/untracked"))

    tracked = store.get_database_data(
        filter={"property": "Tracked", "checkbox": {"equals": True}}
    )
    assert len(tracked) == 1
    assert tracked.loc[0, "id"] == row_id


def test_get_database_data_filters_stage_and_company(store):
    """Status and rich-text filters map to their canonical columns."""
    store.create_page(
        properties=_base_properties(URL="https://example.com/r", Stage="Rejected")
    )
    store.create_page(
        properties=_base_properties(URL="https://example.com/a", Stage="Applied")
    )

    rejected = store.get_database_data(
        filter={"property": "Stage", "status": {"equals": "Rejected"}}
    )
    assert len(rejected) == 1
    assert rejected.loc[0, "Stage"] == "Rejected"

    by_company = store.get_database_data(
        filter={"property": "Company", "rich_text": {"equals": "Acme"}}
    )
    assert len(by_company) == 2


def test_update_row_unwraps_checkbox_and_status(store):
    """Row updates unwrap checkbox and status compatibility payloads."""
    row_id = store.create_page(properties=_base_properties())

    assert store.update_row(row_id, {"Tracked": {"checkbox": True}}) is True
    assert store.update_row(row_id, {"Stage": {"status": {"name": "Rejected"}}}) is True

    df = store.get_database_data()
    assert df.loc[0, "Tracked"] == "True"
    assert df.loc[0, "Stage"] == "Rejected"


def test_update_row_accepts_plain_scalar(store):
    """Row updates accept canonical scalar values without wrappers."""
    row_id = store.create_page(properties=_base_properties())
    assert store.update_row(row_id, {"Notes": "some note"}) is True
    df = store.get_database_data()
    assert df.loc[0, "Notes"] == "some note"


def test_update_row_missing_id_returns_false(store):
    """Updating an unknown row id reports failure."""
    assert store.update_row("does-not-exist", {"Tracked": {"checkbox": True}}) is False


def test_create_page_ignores_database_id_and_prop_name_map(store):
    """Legacy compatibility arguments do not alter canonical storage."""
    row_id = store.create_page(
        database_id="ignored",
        properties=_base_properties(),
        prop_name_map={"Company": "Firma"},
    )
    df = store.get_database_data(database_id="ignored")
    assert df.loc[0, "id"] == row_id
    # Canonical column name is used, not the remapped one.
    assert "Company" in df.columns


def test_get_db_path_default(monkeypatch):
    """Database path configuration exposes its default value."""
    monkeypatch.delenv("JOBROOM_DB_PATH", raising=False)
    assert get_db_path() == "data/applications.db"


def test_get_db_path_env(monkeypatch):
    """Database path configuration exposes an environment override."""
    monkeypatch.setenv("JOBROOM_DB_PATH", "/tmp/custom.db")
    assert get_db_path() == "/tmp/custom.db"


def test_default_db_path_uses_env(monkeypatch, tmp_path):
    """A store without a path uses the environment and creates its parent."""
    target = tmp_path / "nested" / "apps.db"
    monkeypatch.setenv("JOBROOM_DB_PATH", str(target))
    store = ApplicationStore()
    assert store.db_path == str(target)
    # The parent directory was created.
    assert target.parent.exists()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"checkbox": True}, True),
        ({"status": {"name": "Applied"}}, "Applied"),
        ({"select": {"name": "LinkedIn"}}, "LinkedIn"),
        ({"date": {"start": "2026-01-01"}}, "2026-01-01"),
        ({"url": "https://x"}, "https://x"),
        ({"email": "a@x.com"}, "a@x.com"),
        ({"phone_number": "+41"}, "+41"),
        ({"number": 3}, 3),
        ({"rich_text": [{"text": {"content": "hello"}}]}, "hello"),
        ({"title": [{"text": {"content": "Engineer"}}]}, "Engineer"),
        ("plain", "plain"),
        (None, None),
    ],
)
def test_unwrap_property(value, expected):
    """Compatibility payload shapes unwrap to canonical scalar values."""
    assert unwrap_property(value) == expected


def test_create_page_handles_failure(monkeypatch, store):
    """Database connection failures make application creation return None."""

    def boom(*args, **kwargs):
        """Raise a representative SQLite connection error."""
        raise __import__("sqlite3").Error("db is broken")

    monkeypatch.setattr(store, "_connect", boom)
    assert store.create_page(properties=_base_properties()) is None

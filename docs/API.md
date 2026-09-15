# API Documentation

## ApplicationStore

Local SQLite-backed store for tracked job applications. Drop-in replacement for
the previous Notion helper.

### Usage

```python
from jobroom_helper.utils import ApplicationStore

store = ApplicationStore()  # uses JOBROOM_DB_PATH or data/applications.db

row_id = store.create_page(
    properties={
        "Company": "Acme",
        "Role": "Engineer",
        "URL": "https://example.com/job",
        "Stage": "Applied",
    }
)

df = store.get_database_data()
```

### Methods

#### `__init__(db_path: str | None = None)`

Open (creating if needed) the SQLite database and ensure the table exists.

**Parameters:**

- `db_path` (str, optional): Path to the SQLite file. Defaults to the
  `JOBROOM_DB_PATH` environment variable, else `data/applications.db`.

#### `get_database_data(database_id=None, filter: dict | None = None) -> pd.DataFrame`

Fetch matching rows from the database.

**Parameters:**

- `database_id`: Accepted for signature compatibility; ignored.
- `filter` (dict, optional): A supported filter dict (the shapes built by
  `get_month_filter`, `get_rejected_filter`, and the company-address lookup),
  translated to SQL `WHERE` clauses.

**Returns:**

- `pd.DataFrame`: DataFrame with the canonical application columns plus `id`.

#### `create_page(database_id=None, properties: dict, prop_name_map=None) -> str | None`

Insert a new application row from canonical scalar properties. `URL` is unique;
if the URL already exists the existing id is returned without inserting a
duplicate.

**Returns:**

- `str`: The row id on success.
- `None`: On failure.

#### `update_row(page_id: str, properties: dict) -> bool`

Update columns for the row with the given id. Notion-style property dicts
(`{"checkbox": v}`, `{"status": {"name": v}}`, …) are unwrapped to scalars
before writing; plain scalars are accepted too.

**Returns:**

- `bool`: True on success, False if the row does not exist or on error.

## Session Helper

Helper functions for managing Selenium WebDriver sessions.

### Functions

#### `save_session(driver)`

Save cookies and storage from the current driver session to disk.

#### `load_session(driver) -> bool`

Restore a session saved today into the driver. Returns True if restored.

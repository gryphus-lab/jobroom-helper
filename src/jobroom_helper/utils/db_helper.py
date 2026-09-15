"""Local SQLite-backed application store.

Drop-in replacement for the old Notion helper: exposes the same method
surface (``get_database_data``, ``create_page``, ``update_row``) and returns
data in the same shapes so callers barely change.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pandas as pd

DEFAULT_DB_PATH = "data/applications.db"

# Canonical columns stored for each application. Order matters for the
# CREATE TABLE statement and for building INSERT statements.
_APPLICATION_COLUMNS: tuple[str, ...] = (
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
    # Job-Room form fields (config.FIELD_SELECTORS).
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
)


def unwrap_property(value: Any) -> Any:
    """Reduce a Notion-style property dict down to a scalar value.

    Accepts the small set of shapes callers may still pass
    (``{"checkbox": v}``, ``{"status": {"name": v}}``, ``{"date": {"start":
    v}}``, ``{"rich_text": [{"text": {"content": v}}]}``, ``{"title": [...]}``,
    ``{"select": {"name": v}}``, ``{"url": v}``, ``{"email": v}``,
    ``{"phone_number": v}``, ``{"number": v}``). Plain scalars pass through
    unchanged.
    """
    if not isinstance(value, dict):
        return value

    scalar_keys = ("checkbox", "url", "email", "phone_number", "number")
    for key in scalar_keys:
        if key in value:
            return value[key]

    nested_keys = {"status": "name", "select": "name", "date": "start"}
    for key, nested_key in nested_keys.items():
        if key in value:
            return (value.get(key) or {}).get(nested_key)

    for rich_key in ("rich_text", "title"):
        if rich_key in value:
            return _unwrap_text_fragments(value.get(rich_key))
    return value


def _unwrap_text_fragments(fragments: Any) -> str:
    return "".join(
        (fragment.get("text", {}) or {}).get("content", "")
        for fragment in (fragments or [])
        if isinstance(fragment, dict)
    )


def _quote(identifier: str) -> str:
    """Quote a column identifier for safe use in SQL."""
    return '"' + identifier.replace('"', '""') + '"'


class ApplicationStore:
    """SQLite-backed store for tracked job applications."""

    def __init__(self, db_path: Optional[str] = None):
        """Open (creating if needed) the SQLite database and ensure the table.

        Args:
            db_path: Path to the SQLite file. Defaults to the ``JOBROOM_DB_PATH``
                environment variable, else ``data/applications.db``.
        """
        self.db_path = db_path or os.environ.get("JOBROOM_DB_PATH", DEFAULT_DB_PATH)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._create_table()

    def _connect(self) -> sqlite3.Connection:
        """Open a connection that exposes result rows by column name."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table(self) -> None:
        """Create the applications table when the database is uninitialized."""
        column_defs = ",\n            ".join(
            f"{_quote(col)} TEXT" for col in _APPLICATION_COLUMNS if col != "URL"
        )
        sql = f"""
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            "URL" TEXT UNIQUE,
            {column_defs},
            created_at TEXT,
            updated_at TEXT
        )
        """
        with self._connect() as conn:
            conn.execute(sql)
            conn.commit()

    def get_database_data(
        self,
        filter: Optional[Dict] = None,
        database_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return all matching rows as a DataFrame.

        Args:
            filter: Optional Notion-style filter dict; the known shapes built by
                the callers are translated into SQL WHERE clauses.
            database_id: Ignored legacy Notion database identifier.

        Returns:
            pd.DataFrame with the canonical application columns plus ``id``.
        """
        where_sql, params = self._build_where(filter)
        query = "SELECT * FROM applications"
        if where_sql:
            query += f" WHERE {where_sql}"

        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(query, params).fetchall()]

        columns = ["id", *_APPLICATION_COLUMNS]
        if not rows:
            return pd.DataFrame(columns=columns)

        df = pd.DataFrame(rows)
        # Preserve the downstream column set/order; drop bookkeeping columns.
        for col in columns:
            if col not in df.columns:
                df[col] = None
        return df[columns]

    def _build_where(self, filter: Optional[Dict]) -> tuple[str, list]:
        """Translate a supported Notion-style filter dict into SQL.

        Recognizes the shapes built by ``get_month_filter``,
        ``get_rejected_filter`` and ``_existing_company_address``.
        """
        if not filter:
            return "", []

        if isinstance(filter, dict) and "and" in filter:
            conditions = filter["and"]
        else:
            conditions = [filter]

        clauses: List[str] = []
        params: List[Any] = []
        for condition in conditions:
            clause, clause_params = self._translate_condition(condition)
            if clause:
                clauses.append(clause)
                params.extend(clause_params)
        return " AND ".join(clauses), params

    def _translate_condition(self, condition: Dict) -> tuple[str, list]:
        """Translate one supported filter condition into SQL and parameters."""
        prop = condition.get("property")
        if not prop:
            return "", []
        col = _quote(prop)

        if "date" in condition:
            date_filter = condition["date"]
            if "on_or_after" in date_filter:
                return f"{col} >= ?", [date_filter["on_or_after"]]
            if "before" in date_filter:
                return f"{col} < ?", [date_filter["before"]]
        if "checkbox" in condition:
            expected = condition["checkbox"].get("equals")
            # Tracked is stored as a string ("True"/"False") or NULL.
            if expected:
                return f"{col} = ?", ["True"]
            return f"({col} IS NULL OR {col} != ?)", ["True"]
        if "status" in condition:
            return f"{col} = ?", [condition["status"].get("equals")]
        for text_key in ("rich_text", "title"):
            if text_key in condition:
                return f"{col} = ?", [condition[text_key].get("equals")]
        return "", []

    def create_page(
        self,
        properties: Optional[Dict[str, Any]] = None,
        database_id: Optional[str] = None,
        prop_name_map: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Insert a new application row from canonical scalar properties.

        ``URL`` is UNIQUE for natural dedup: if the URL already exists the
        existing id is returned without inserting a duplicate.

        Args:
            properties: Canonical-key -> scalar value mapping.
            database_id: Ignored legacy Notion database identifier.
            prop_name_map: Ignored legacy Notion property-name mapping.

        Returns:
            The row id on success, or None on failure.
        """
        properties = properties or {}
        url = properties.get("URL")

        try:
            if url:
                existing_id = self._find_id_by_url(url)
                if existing_id is not None:
                    print(
                        f"   ℹ️  Entry already exists for URL {url}; "
                        f"reusing existing id {existing_id[:8]}..."
                    )
                    return existing_id

            row_id = uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            values = {
                col: _to_storage(properties.get(col))
                for col in _APPLICATION_COLUMNS
                if col in properties
            }
            values["id"] = row_id
            values["created_at"] = now
            values["updated_at"] = now

            columns = list(values.keys())
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(_quote(col) for col in columns)
            with self._connect() as conn:
                cursor = conn.execute(
                    f"""
                    INSERT INTO applications ({column_sql}) VALUES ({placeholders})
                    ON CONFLICT("URL") DO NOTHING
                    """,
                    [values[col] for col in columns],
                )
                if cursor.rowcount == 0 and url:
                    row = conn.execute(
                        'SELECT id FROM applications WHERE "URL" = ?', [url]
                    ).fetchone()
                    return row["id"] if row else None
                conn.commit()
            print(f"   ✅ Application row created (id: {row_id[:8]}...)")
            return row_id
        except sqlite3.Error as exc:
            print(f"   ❌ Failed to create application row: {exc}")
            return None

    def _find_id_by_url(self, url: str) -> Optional[str]:
        """Return the application id associated with a URL, if one exists."""
        with self._connect() as conn:
            row = conn.execute(
                'SELECT id FROM applications WHERE "URL" = ?', [url]
            ).fetchone()
        return row["id"] if row else None

    def update_row(self, page_id: str, properties: Dict[str, Any]) -> bool:
        """Update columns for the row with the given id.

        Unwraps Notion-style property dicts to scalars before writing and
        accepts plain scalar values too.

        Returns:
            True on success, False if the row does not exist or on error.
        """
        try:
            with self._connect() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM applications WHERE id = ?", [page_id]
                ).fetchone()
                if not exists:
                    print(f"   ❌ No application row found for id {page_id}")
                    return False

                assignments = []
                params: List[Any] = []
                for key, raw_value in properties.items():
                    assignments.append(f"{_quote(key)} = ?")
                    params.append(_to_storage(unwrap_property(raw_value)))
                assignments.append("updated_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
                params.append(page_id)

                conn.execute(
                    f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?",
                    params,
                )
                conn.commit()
            print(f"   ✅ Application row updated (id: {page_id[:8]}...)")
            return True
        except sqlite3.Error as exc:
            print(f"   ❌ Failed to update application row: {exc}")
            return False


def _to_storage(value: Any) -> Any:
    """Normalize a value for storage as TEXT (booleans -> "True"/"False")."""
    if value is None:
        return None
    return str(value)

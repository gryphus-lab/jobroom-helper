# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-run CLI that pulls job-application records from a local SQLite database and uses Selenium to fill the work-effort ("Efforts to find work") form on https://www.job-room.ch. It is **interactive by design**: it pauses for manual login (AGOV + QR scan), and pauses again before submitting each form so the user can review the filled fields. It is not headless and not unattended.

## Commands

This project is driven by `uv` (Python 3.12+, see `mise.toml` for tooling). `mise run <task>` wraps the common ones.

```bash
uv sync                                  # install deps (mise run install)
uv run -m jobroom_helper new             # process new entries (mise run new); also: uv run autofill
uv run -m jobroom_helper update-rejections  # update rejected entries (mise run update)
uv run -m jobroom_helper create <url>    # scrape a URL and insert an application (mise run create)
uv run -m jobroom_helper list            # list tracked applications (mise run list)
uv run pytest                            # run all tests (mise run test); coverage is on by default → htmlcov/
uv run pytest tests/test_db_helper.py::test_name   # run a single test
uv run ruff check . && uv run ruff format --check .     # lint (mise run lint)
uv run ruff format . && uv run ruff check --fix .       # format + autofix (mise run format)
```

Note: pytest's `addopts` always runs coverage (`--cov`, html + term-missing). Tests live in `tests/` but are **excluded from ruff lint** (see `pyproject.toml [tool.ruff].exclude`).

## Architecture

The run is a linear pipeline in `__main__.py:main()`:

1. **Fetch** — `ApplicationStore.get_database_data()` queries the local SQLite database with a filter built by `get_month_filter()`: records whose `Applied date` falls in the current calendar month **and** `Tracked == false`. Returns a pandas `DataFrame`, one row per application, with the row `id` preserved as a column.
2. **Transform** — `prepare_dataframe()` mutates the DataFrame in place: trims `PLZ_Ort` to its first 4 chars (postal code for the typeahead), unpacks `Date`/`Type` via `extract_formatted_field` (which `ast.literal_eval`s a stringified `{"string": ...}` dict), and hardcodes `RAV`/`Arbeitspensum`/`Status` to `"false"` (these drive radio-button selectors, not literal values).
3. **Login** — `handle_login()` (in `selenium_helper.py`) tries `load_session()` first; on miss, walks the manual login UI and blocks on `input()` until the user confirms AGOV login, then `save_session()`.
4. **Process** — `process_records()` navigates to `WEBSITE_URL + "work-efforts"`, and for each row clicks "add work effort", iterates `FIELD_SELECTORS`, calls `fill_field()` per field, blocks on `input()` for manual review/submit, then calls `ApplicationStore.update_row()` to set `Tracked: true`.

### Field filling (`selenium_helper.py`)

`fill_field()` is a dispatcher that picks a strategy by inspecting the **selector string and field name** (not a declared field type):

- selector contains `typeahead` → `fill_typeahead` (types, waits for an `ngb-typeahead` suggestion button, clicks it, else falls back to ENTER)
- selector contains `checkbox`, or field is `Type`/`Interview` → `fill_checkbox`
- selector contains `radio` → `fill_radio`
- otherwise → `fill_text`

`Type` and `Interview` are special: their `FIELD_SELECTORS` entry is a placeholder (`"dummy"`), and the real selector is resolved at runtime by `resolve_type_selector(value)` based on the record's value (`electronic`/`phone`/`vorstellungsgespräch`). `Type` resolves to a CSS selector; `Interview` to an XPath. Clicks generally go through `driver.execute_script("arguments[0].click();", el)` (`EXECUTE_SCRIPT_CLICK`) rather than `.click()` to bypass overlay/visibility issues.

### Session persistence (`session_helper.py`)

Sessions are saved to `cookies/` (cookies + localStorage + sessionStorage + `session_info.json` with a date stamp). **Daily policy:** `load_session()` only restores a session saved _today_; otherwise it deletes the old files and forces a fresh login. This matches the target site's daily-login requirement.

### Storage layer (`db_helper.py`)

`ApplicationStore` wraps a local SQLite database (stdlib `sqlite3`), with one row per application in an `applications` table. `URL` is `UNIQUE` for natural dedup. The class is a drop-in for the previous Notion helper: `get_database_data()` returns a `DataFrame` with the same canonical columns, `create_page()` inserts a row from canonical scalar properties, and `update_row()` unwraps the Notion-style property dicts (`{"checkbox": ...}`, `{"status": {"name": ...}}`) that `selenium_helper` still passes. The database path comes from `JOBROOM_DB_PATH` (env) or defaults to `data/applications.db`.

## Conventions & gotchas

- **The code is tightly coupled to the job-room.ch DOM.** Selectors in `config.py:FIELD_SELECTORS` and the login button selectors in `handle_login()` will break when the site changes; this is the most common reason a run fails. Failures save a screenshot to `results/jobroom_*_error.png`.
- `WEBSITE_URL` is loaded from a git-ignored `.env` file via `python-dotenv` in `config.py`. Copy `.env.example` → `.env` to set it. Importing `config.py` no longer raises when optional envs are absent; `get_website_url()` raises only when actually called without `WEBSITE_URL`.
- Field/value semantics are **German-site-specific** (e.g. `PLZ_Ort` = postal code + city, `Arbeitspensum` = workload, `RAV` = unemployment office). Column names (`Date`, `Type`, `Company`, `Role`, `PLZ_Ort`, …) must match `FIELD_SELECTORS` keys exactly.
- There is debug `print()` noise throughout; intentional for this interactive tool.

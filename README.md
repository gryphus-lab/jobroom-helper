# Job-Room Helper

Automates web form filling by reading job-application records from a local
SQLite database and using Selenium to populate the Job-Room work-effort form.

## Features

- Stores applications in a local SQLite database (no external service required)
- Exposes the records as a pandas `DataFrame`
- Opens Chrome with Selenium and `webdriver-manager`
- Fills text inputs, typeahead fields, checkboxes, and radio buttons
- Handles interview records by checking `Vorstellungsgespräch` only when the row is an interview
- Marks processed records as tracked by updating the `Tracked` flag
- `create` command scrapes a job URL and inserts a new application (dedup by URL)
- `list` command prints all tracked applications

## Overview

- Filters records for the current month where `Applied date` is within the month and `Tracked` is `false`
- Processes all matching records from the local tracker
- Requires a manual login step before automation continues
- Waits for user confirmation before form submission and before closing the browser

## Requirements

- Python 3.12+
- `uv` package manager (configured in `mise.toml`)
- Chrome browser installed
- `webdriver-manager` for automatic ChromeDriver management

## Installation

1. Sync dependencies using `uv`:

   ```bash
   uv sync
   ```

2. Copy the example environment file and fill in your local values:

   ```bash
   cp .env.example .env
   ```

3. Configure your target website (and optionally the DB path) in `.env`:
   - Set `WEBSITE_URL`
   - Optionally set `JOBROOM_DB_PATH` (defaults to `data/applications.db`)
   - Optionally set `ENABLE_BROWSER_FALLBACK`

4. Update `FIELD_SELECTORS` in `src/jobroom_helper/config.py` if the target form changes.

## Project Structure

```text
jobroom-helper/
├── src/jobroom_helper/
│   ├── __init__.py              # Package initialization
│   ├── __main__.py              # Main entry point
│   ├── config.py                # Configuration variables
│   └── utils/
│       ├── __init__.py
│       ├── db_helper.py         # Local SQLite application store
│       ├── selenium_helper.py   # Selenium form filling helpers
│       └── session_helper.py    # Selenium session management
├── tests/                       # Unit tests
│   ├── test_config.py
│   ├── test_db_helper.py
│   ├── test_selenium_helper.py
│   └── test_session_helper.py
├── docs/                        # Documentation
├── pyproject.toml               # Project configuration
├── mise.toml                    # Mise/task configuration
└── README.md
```

## Usage

### Create a tracker entry from a URL

The `create` command inserts a new application into the local database by
scraping basic metadata from a URL. URLs are unique, so re-running `create`
on the same URL reuses the existing entry instead of creating a duplicate.

Examples:

```bash
# Create and store in the local tracker
mise run create 'https://example.com/job'

# Dry-run: print the properties that would be inserted, without writing
mise run create 'https://example.com/job' --dry-run

# Override extracted company/role values
mise run create 'https://example.com/job' --company='MyCo' --role='Engineer'
```

New applications always start at `Stage = "Applied"`.

### List tracked applications

```bash
mise run list
# or
uv run -m jobroom_helper list
```

### Run with uv

```bash
# Process new untracked entries for the current month
uv run -m jobroom_helper new

# Update rejected entries
uv run -m jobroom_helper update-rejections

# Or using mise
mise run new
mise run update
```

### Run tests

```bash
uv run pytest
```

Pytest writes terminal and HTML coverage reports, plus `coverage.xml` for SonarQube.

### Code quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check . --fix
```

## Configuration

Create a local `.env` file:

```bash
cp .env.example .env
```

Then set:

- `WEBSITE_URL` — the target website URL
- `JOBROOM_DB_PATH` — (optional) path to the SQLite database
- `ENABLE_BROWSER_FALLBACK` — (optional) enable the headless-browser scraping fallback

Edit `src/jobroom_helper/config.py` only when the target form selectors change:

- `FIELD_SELECTORS` — mapping of tracker columns to CSS selectors for the web form

### Important

- `Type` and `Interview` are handled specially in `utils/selenium_helper.py` using selector/value resolvers.
- `PLZ_Ort` is trimmed to the first 4 characters before being entered in the typeahead field.
- The script depends on the current target site's form structure and may require selector updates.

## CI and SonarQube

GitHub Actions runs `mise run install`, `mise run test`, and then the SonarQube scan. The test step generates `coverage.xml`, which is read by Sonar through `sonar.python.coverage.reportPaths`.

The SonarQube scan requires `SONAR_TOKEN` to be configured as a GitHub Actions secret.

## Execution

Run the project with:

```bash
uv run autofill
```

The script will:

1. query the local tracker for current-month, untracked records
2. open Chrome and navigate to the configured site
3. prompt for manual login
4. process each matching row
5. wait for confirmation before submission
6. update the record's `Tracked` flag on success

## Notes

- Error screenshots are saved under `results/jobroom_fill_field_error.png` and `results/jobroom_main_error.png`.
- `utils/db_helper.py` uses the stdlib `sqlite3` module and `pandas`.
- The project includes a development dependency on `ruff`.

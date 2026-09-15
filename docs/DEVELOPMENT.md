# Developer Guide

## Setup

### Prerequisites

- Python 3.12 or higher
- pip or uv (package manager)

### Installation

1. Clone the repository

```bash
git clone <repository-url>
cd jobroom-helper
```

1. Install dependencies (creates the `.venv` and installs the `dev` dependency group)

```bash
uv sync
```

## Project Structure

```text
jobroom-helper/
├── src/
│   └── jobroom_helper/     # Main package
│       ├── __init__.py
│       ├── __main__.py               # Entry point
│       ├── config.py                 # Configuration
│       └── utils/
│           ├── __init__.py
│           ├── db_helper.py          # Local SQLite application store
│           └── session_helper.py     # Selenium session management
├── tests/                            # Unit tests
│   ├── __init__.py
│   ├── test_config.py
│   └── test_db_helper.py
├── docs/                             # Documentation
├── pyproject.toml                    # Project metadata and dependencies
├── README.md
└── .gitignore
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=src/jobroom_helper

# Run specific test file
pytest tests/test_config.py

# Run tests in verbose mode
pytest -v
```

## Code Quality

### Formatting

```bash
ruff format src tests
```

### Linting

```bash
ruff check src tests
ruff check --fix src tests
```

## Running the Application

### As a module

```bash
python -m jobroom_helper
```

### As a command

```bash
autofill
```

## Configuration

Configure the environment-dependent values in `.env`:

- `WEBSITE_URL`: Target website URL
- `JOBROOM_DB_PATH`: (optional) path to the SQLite database

Update `src/jobroom_helper/config.py` with:

- `FIELD_SELECTORS`: CSS selectors for form fields

## Development Workflow

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Create a pull request

## Common Tasks

### Adding a new dependency

```bash
# Add a runtime dependency
uv add <package>

# Add a dev-only dependency
uv add --dev <package>
```

### Adding a new test

- Create test file in `tests/` directory
- Name it `test_*.py`
- Run `pytest` to verify

### Adding a new module

- Create module in `src/jobroom_helper/`
- Update `src/jobroom_helper/__init__.py` if needed
- Add tests in `tests/`

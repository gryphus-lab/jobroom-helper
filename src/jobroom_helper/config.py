"""Configuration for the Job-Room autofill tool."""

import os

from dotenv import load_dotenv

# Load user/instance-specific secrets from a local .env file (see .env.example).
load_dotenv()


def _required_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required configuration: {name}")
    return value


def get_db_path() -> str:
    """Return the SQLite database path (env JOBROOM_DB_PATH or default)."""
    return os.environ.get("JOBROOM_DB_PATH", "data/applications.db")


APPLIED_DATE = "Applied date"
EXIT_MESSAGE = "     Exiting...\n"
SCROLL_INTO_VIEW_SCRIPT = "arguments[0].scrollIntoView({block: 'center'});"

FIELD_SELECTORS = {
    "Date": "input[id*='date']",
    "Type": "dummy",  # This will be overridden in code
    "Company": "input[id*='company.name']",
    "Street": "input[id*='company.street']",
    "Number": "input[id*='company.house-number']",
    "POBox": "input[id*='company.postbox-number']",
    "PLZ_Ort": "input[id*='single-typeahead-']",
    "Contact": "input[id*='contact-person']",
    "Email": "input[id*='contact.email']",
    "Phone": "input[id*='global.phone']",
    "Role": "input[id*='job-title']",
    "URL": "input[id*='online-form-url']",
    "RAV": "label[for*='radio-button-'][for$='false']",
    "Arbeitspensum": "label[for*='radio-button-'][for$='FULLTIME']",
    "Interview": "dummy",
    "Status": "label[for*='radio-button-'][for$='PENDING']",
}

COOKIES_FILE = "cookies/jobroom_cookies.json"

EXECUTE_SCRIPT_CLICK = "arguments[0].click();"

# Selectors for updating an existing entry's status to "Absage"
REJECTION_SELECTORS = {
    "status_radio_absage": "label[for*='radio-button-'][for$='REJECTED']",
    "absagegrund_input": "textarea[id*='rejection-reason']",
}

ENTRY_SELECTOR = "alv-work-effort"

# arbeit.swiss Job-Room base URL. Stable public endpoint, so it defaults here
# and only needs WEBSITE_URL in the environment to point at a different host.
DEFAULT_WEBSITE_URL = "https://www.job-room.ch/"


def get_website_url() -> str:
    """Return the Job-Room base URL (env WEBSITE_URL or the default)."""
    return os.environ.get("WEBSITE_URL", "").strip() or DEFAULT_WEBSITE_URL


def is_browser_fallback_enabled() -> bool:
    """Return whether the opt-in browser fallback is enabled."""
    return os.environ.get("ENABLE_BROWSER_FALLBACK", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }

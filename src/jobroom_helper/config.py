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

# Selector for marking an existing entry as "Vorstellungsgespräch".
#
# IMPORTANT: In the Job-Room "Ergebnis der Bewerbung" group, Vorstellungsgespräch
# is a standalone CHECKBOX, NOT one of the status radio buttons. It is ticked
# ALONGSIDE the status radio, which stays at "Noch offen" (the application is
# still open — an interview is not a terminal outcome). So this flow must check
# the Vorstellungsgespräch checkbox and must NOT touch the status radio.
# An interview also has no reason/Absagegrund field.
INTERVIEW_SELECTORS = {
    "interview_checkbox": "input[type='checkbox'][id*='interview']",
}

# Search box on the work-efforts page used to locate an existing entry by
# company name, independent of the current control period. The id contains
# literal dots, so they must be escaped in a CSS selector.
WORK_EFFORTS_SEARCH_SELECTOR = r"#alv-input-field-portal\.work-efforts\.search\.query-0"

ENTRY_SELECTOR = "alv-work-effort"


def get_website_url() -> str:
    return _required_setting("WEBSITE_URL")


def is_browser_fallback_enabled() -> bool:
    """Return whether the opt-in browser fallback is enabled."""
    return os.environ.get("ENABLE_BROWSER_FALLBACK", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }

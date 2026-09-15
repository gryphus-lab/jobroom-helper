"""Tests for configuration module."""

import pytest

from jobroom_helper.config import (
    FIELD_SELECTORS,
    get_db_path,
    get_website_url,
    is_browser_fallback_enabled,
)


def test_config_import_does_not_require_notion_envs(monkeypatch):
    """Importing config must not raise even when Notion envs are absent."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_ID", raising=False)
    # Re-import to confirm module import does not raise without those envs.
    import importlib

    import jobroom_helper.config as config_module

    importlib.reload(config_module)
    assert config_module.FIELD_SELECTORS


def test_get_db_path_default(monkeypatch):
    monkeypatch.delenv("JOBROOM_DB_PATH", raising=False)
    assert get_db_path() == "data/applications.db"


def test_get_db_path_env(monkeypatch):
    monkeypatch.setenv("JOBROOM_DB_PATH", "/tmp/db.sqlite")
    assert get_db_path() == "/tmp/db.sqlite"


def test_get_website_url_requires_setting(monkeypatch):
    monkeypatch.setenv("WEBSITE_URL", "https://example.com")
    assert get_website_url() == "https://example.com"

    monkeypatch.delenv("WEBSITE_URL", raising=False)
    with pytest.raises(RuntimeError, match="WEBSITE_URL"):
        get_website_url()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("", False), ("no", False)],
)
def test_is_browser_fallback_enabled(monkeypatch, value, expected):
    monkeypatch.setenv("ENABLE_BROWSER_FALLBACK", value)
    assert is_browser_fallback_enabled() is expected


def test_field_selectors_structure():
    """Test that FIELD_SELECTORS has required fields."""
    required_fields = {
        "Date",
        "Type",
        "Company",
        "Street",
        "Email",
        "Phone",
        "Role",
    }
    assert required_fields.issubset(set(FIELD_SELECTORS.keys()))


def test_field_selectors_are_strings():
    """Test that all selectors are strings."""
    for field, selector in FIELD_SELECTORS.items():
        assert isinstance(selector, str), f"Selector for {field} is not a string"

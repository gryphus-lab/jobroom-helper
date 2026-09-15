"""Tests for the mise.toml task configuration."""

import tomllib
from pathlib import Path

import pytest

MISE_TOML_PATH = Path(__file__).resolve().parent.parent / "mise.toml"


@pytest.fixture(scope="module")
def mise_config():
    """Load and parse the mise.toml file."""
    with open(MISE_TOML_PATH, "rb") as f:
        return tomllib.load(f)


def test_mise_toml_is_valid_toml(mise_config):
    """Test that mise.toml parses without errors and has a tasks table."""
    assert "tasks" in mise_config


def test_new_task_has_short_alias(mise_config):
    """Test that the 'new' task exposes the 'n' alias."""
    new_task = mise_config["tasks"]["new"]
    assert new_task["run"] == "uv run -m jobroom_helper new"
    assert new_task["alias"] == ["n"]


def test_update_task_runs_update_rejections_with_short_alias(mise_config):
    """Regression test: the 'update' task must run the 'update-rejections'
    entry point (not dependency updates) and expose the 'u' alias.

    This guards against re-introducing the earlier naming collision where
    'update' ambiguously referred to both dependency updates and the
    update-rejections script."""
    update_task = mise_config["tasks"]["update"]
    assert update_task["run"] == "uv run -m jobroom_helper update-rejections"
    assert update_task["alias"] == ["u"]


def test_update_deps_task_upgrades_dependencies(mise_config):
    """Regression test: dependency upgrades must live under 'update-deps',
    freeing up the 'update' task name for the update-rejections script."""
    update_deps_task = mise_config["tasks"]["update-deps"]
    assert update_deps_task["run"] == "uv sync --upgrade"


def test_task_names_are_unique(mise_config):
    """Test there is no ambiguity between the 'update' and 'update-deps' tasks."""
    tasks = mise_config["tasks"]
    assert "update" in tasks
    assert "update-deps" in tasks
    assert tasks["update"]["run"] != tasks["update-deps"]["run"]


def test_all_aliases_are_unique(mise_config):
    """Test that no two tasks share the same alias."""
    seen_aliases = []
    for task in mise_config["tasks"].values():
        for alias in task.get("alias", []):
            assert alias not in seen_aliases, f"Duplicate alias: {alias}"
            seen_aliases.append(alias)


def test_add_task_unchanged(mise_config):
    """Test that the 'add' task for adding dependencies remains intact."""
    add_task = mise_config["tasks"]["add"]
    assert add_task["run"] == "uv add {args}"


def test_create_task_forwards_cli_arguments_automatically(mise_config):
    """The create task must let mise append the URL and CLI options."""
    create_task = mise_config["tasks"]["create"]
    assert create_task["run"] == "uv run -m jobroom_helper create"
    assert "{args}" not in create_task["run"]
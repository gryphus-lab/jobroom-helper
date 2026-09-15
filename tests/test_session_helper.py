import json
from types import SimpleNamespace

from selenium.common.exceptions import WebDriverException

from jobroom_helper.utils import session_helper


class DummyDriver:
    def __init__(self):
        self.added = []
        self.cookies = [{"name": "a", "value": "1", "sameSite": "Lax"}]
        self.scripts = []

    def get_cookies(self):
        return self.cookies

    def execute_script(self, script, *args):
        # emulate returning storage when asked
        if "localStorage" in script:
            return {"k": "v"}
        self.scripts.append((script, args))
        return None

    def add_cookie(self, cookie):
        # record cookie added
        self.added.append(cookie)

    def get(self, url):
        self.last_get = url

    def refresh(self):
        self.refreshed = True


def test_save_session_writes_files(tmp_path, monkeypatch):
    cookies_file = tmp_path / "jobroom_cookies.json"
    storage_file = tmp_path / "jobroom_storage.json"

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    driver = DummyDriver()

    session_helper.save_session(driver)

    # files created
    assert cookies_file.exists()
    assert storage_file.exists()

    with open(cookies_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)

    with open(storage_file, "r", encoding="utf-8") as f:
        storage = json.load(f)
    assert "localStorage" in storage


def test__apply_cookies_removes_same_site(monkeypatch):
    driver = DummyDriver()
    cookies = [{"name": "x", "value": "y", "sameSite": "None"}]

    session_helper._apply_cookies(driver, cookies)

    assert len(driver.added) == 1
    assert "sameSite" not in driver.added[0]


def test__restore_storage_applies_items(tmp_path, monkeypatch):
    storage_file = tmp_path / "jobroom_storage.json"
    content = {"localStorage": {"a": "1"}, "sessionStorage": {"b": "2"}}
    storage_file.write_text(json.dumps(content))

    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    recorded = []

    class ExecDriver:
        def execute_script(self, script, *args):
            recorded.append((script, args))

    d = ExecDriver()
    session_helper._restore_storage(d)

    # two calls should be made to set items
    assert any("localStorage.setItem" in r[0] for r in recorded)
    assert any("sessionStorage.setItem" in r[0] for r in recorded)


def test_load_session_no_cookie_file(tmp_path, monkeypatch):
    # point to a non-existent cookies file
    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(tmp_path / "nope.json"))
    d = DummyDriver()
    assert session_helper.load_session(d) is False


def test_load_session_success(tmp_path, monkeypatch):
    cookies_file = tmp_path / "jobroom_cookies.json"
    storage_file = tmp_path / "jobroom_storage.json"

    cookies_file.write_text(json.dumps([{"name": "c", "value": "v"}]))
    storage_file.write_text(json.dumps({"localStorage": {}}))

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    calls = SimpleNamespace(opened=False)

    class RestDriver:
        def __init__(self):
            self.added = []

        def get(self, url):
            calls.opened = True

        def add_cookie(self, c):
            self.added.append(c)

        def refresh(self):
            calls.refreshed = True

        def execute_script(self, script, *args):
            return None

    d = RestDriver()
    assert session_helper.load_session(d) is True
    assert getattr(calls, "opened") is True


def test_load_session_success_without_info_file(tmp_path, monkeypatch):
    cookies_file = tmp_path / "jobroom_cookies.json"
    storage_file = tmp_path / "jobroom_storage.json"

    cookies_file.write_text(json.dumps([{"name": "c", "value": "v"}]))
    storage_file.write_text(json.dumps({"localStorage": {}}))

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))
    monkeypatch.setattr(session_helper, "SESSION_INFO_FILE", str(tmp_path / "jobroom_session_info.json"))

    calls = SimpleNamespace(opened=False)

    class RestDriver:
        def __init__(self):
            self.added = []

        def get(self, url):
            calls.opened = True

        def add_cookie(self, c):
            self.added.append(c)

        def refresh(self):
            calls.refreshed = True

        def execute_script(self, script, *args):
            return None

    d = RestDriver()
    assert session_helper.load_session(d) is True
    assert getattr(calls, "opened") is True


def test_load_session_fails_with_stale_session_info(tmp_path, monkeypatch):
    cookies_file = tmp_path / "jobroom_cookies.json"
    storage_file = tmp_path / "jobroom_storage.json"
    info_file = tmp_path / "jobroom_session_info.json"

    cookies_file.write_text(json.dumps([{"name": "c", "value": "v"}]))
    storage_file.write_text(json.dumps({"localStorage": {}}))
    info_file.write_text(json.dumps({"date": "2000-01-01T00:00:00"}))

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))
    monkeypatch.setattr(session_helper, "SESSION_INFO_FILE", str(info_file))

    d = DummyDriver()
    assert session_helper.load_session(d) is False
    assert not cookies_file.exists()
    assert not storage_file.exists()
    assert not info_file.exists()


def test_save_session_creates_directory_if_not_exists(tmp_path, monkeypatch):
    """Test that save_session creates cookies directory."""
    cookies_dir = tmp_path / "session_cookies"
    cookies_file = cookies_dir / "jobroom_cookies.json"

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(tmp_path / "storage.json"))

    driver = DummyDriver()
    session_helper.save_session(driver)

    assert cookies_file.exists()


def test_apply_cookies_keeps_important_attributes(monkeypatch):
    """Test _apply_cookies preserves important cookie attributes."""
    driver = DummyDriver()
    cookies = [
        {
            "name": "test",
            "value": "val",
            "domain": "example.com",
            "path": "/",
            "secure": True,
            "sameSite": "Strict",
        }
    ]

    session_helper._apply_cookies(driver, cookies)

    assert len(driver.added) == 1
    added_cookie = driver.added[0]
    assert added_cookie["name"] == "test"
    assert added_cookie["value"] == "val"
    assert added_cookie["domain"] == "example.com"
    assert added_cookie["path"] == "/"
    assert added_cookie["secure"] is True
    assert "sameSite" not in added_cookie


def test_restore_storage_with_empty_storage(tmp_path, monkeypatch):
    """Test _restore_storage with empty storage file."""
    storage_file = tmp_path / "storage.json"
    storage_file.write_text(json.dumps({"localStorage": {}, "sessionStorage": {}}))

    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    recorded = []

    class Driver:
        def execute_script(self, script, *args):
            recorded.append((script, args))

    d = Driver()
    session_helper._restore_storage(d)
    # No items to set means no execute_script calls
    assert len(recorded) == 0


def test_is_session_from_today_returns_false_for_invalid_metadata(
    tmp_path, monkeypatch
):
    """Test that is_session_from_today returns False for corrupt metadata."""
    info_file = tmp_path / "session_info.json"
    info_file.write_text("not json")
    monkeypatch.setattr(session_helper, "SESSION_INFO_FILE", str(info_file))

    assert session_helper._is_session_from_today() is False


def test_save_session_handles_storage_webdriver_error(tmp_path, monkeypatch):
    """Test that save_session handles WebDriverException when reading storage."""
    cookies_file = tmp_path / "cookies.json"
    storage_file = tmp_path / "storage.json"
    info_file = tmp_path / "session_info.json"
    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))
    monkeypatch.setattr(session_helper, "SESSION_INFO_FILE", str(info_file))

    class Driver(DummyDriver):
        def execute_script(self, script, *args):
            raise WebDriverException("storage unavailable")

    session_helper.save_session(Driver())

    assert json.loads(storage_file.read_text()) == {}
    assert info_file.exists()


def test_apply_cookies_ignores_webdriver_errors():
    """Test that apply_cookies gracefully handles WebDriverException."""
    class Driver:
        def add_cookie(self, cookie):
            raise WebDriverException("cookie rejected")

    session_helper._apply_cookies(Driver(), [{"name": "x", "value": "y"}])


def test_load_session_returns_false_for_invalid_cookie_json(tmp_path, monkeypatch):
    """Test that load_session returns False for corrupt cookie JSON."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("not json")
    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))

    assert session_helper.load_session(DummyDriver()) is False


def test_restore_storage_handles_missing_keys(tmp_path, monkeypatch):
    """Test _restore_storage handles missing storage keys gracefully."""
    storage_file = tmp_path / "storage.json"
    # Only localStorage, no sessionStorage
    storage_file.write_text(json.dumps({"localStorage": {"key": "value"}}))

    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    recorded = []

    class Driver:
        def execute_script(self, script, *args):
            recorded.append((script, args))

    d = Driver()
    session_helper._restore_storage(d)
    # Should have called setItem for localStorage only
    assert any("localStorage" in r[0] for r in recorded)
    assert not any("sessionStorage" in r[0] for r in recorded)

def test_load_session_with_corrupted_json(tmp_path, monkeypatch):
    """Test load_session handles corrupted JSON gracefully."""
    cookies_file = tmp_path / "cookies.json"
    storage_file = tmp_path / "storage.json"

    cookies_file.write_text("not valid json {")
    storage_file.write_text(json.dumps({}))

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    driver = DummyDriver()
    # Should handle JSON error gracefully
    result = session_helper.load_session(driver)
    # Will fail but shouldn't crash
    assert result is False


def test_save_session_with_multiple_storages(tmp_path, monkeypatch):
    """Test save_session with both localStorage and sessionStorage."""
    cookies_file = tmp_path / "cookies.json"
    storage_file = tmp_path / "storage.json"

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))

    class Driver:
        def get_cookies(self):
            return [{"name": "c1", "value": "v1"}]

        def execute_script(self, script, *args):
            if "localStorage" in script:
                return {"ls_key": "ls_val"}
            if "sessionStorage" in script:
                return {"ss_key": "ss_val"}
            return None

    driver = Driver()
    session_helper.save_session(driver)

    with open(storage_file, "r") as f:
        data = json.load(f)
    assert "localStorage" in data
    assert "sessionStorage" in data


def test_default_file_paths_use_generic_names():
    """Regression test: session files should use generic (non-branded) names."""
    assert session_helper.COOKIES_FILE == "cookies/cookies.json"
    assert session_helper.STORAGE_FILE == "cookies/storage.json"
    assert session_helper.SESSION_INFO_FILE == "cookies/session_info.json"


def test_ensure_directory_exists_creates_nested_directories(tmp_path):
    """Test _ensure_directory_exists creates missing parent directories."""
    nested_file = tmp_path / "a" / "b" / "c" / "file.json"
    assert not nested_file.parent.exists()

    session_helper._ensure_directory_exists(str(nested_file))

    assert nested_file.parent.exists()
    assert nested_file.parent.is_dir()


def test_ensure_directory_exists_is_idempotent(tmp_path):
    """Test _ensure_directory_exists does not fail if directory already exists."""
    existing_file = tmp_path / "existing" / "file.json"
    existing_file.parent.mkdir(parents=True)

    # Should not raise even though the directory already exists
    session_helper._ensure_directory_exists(str(existing_file))

    assert existing_file.parent.exists()


def test_save_session_creates_separate_directories_for_each_file(tmp_path, monkeypatch):
    """Test save_session creates independent directories for cookies, storage, and info files."""
    cookies_file = tmp_path / "cookies_dir" / "cookies.json"
    storage_file = tmp_path / "storage_dir" / "storage.json"
    info_file = tmp_path / "info_dir" / "session_info.json"

    monkeypatch.setattr(session_helper, "COOKIES_FILE", str(cookies_file))
    monkeypatch.setattr(session_helper, "STORAGE_FILE", str(storage_file))
    monkeypatch.setattr(session_helper, "SESSION_INFO_FILE", str(info_file))

    driver = DummyDriver()
    session_helper.save_session(driver)

    assert cookies_file.exists()
    assert storage_file.exists()
    assert info_file.exists()

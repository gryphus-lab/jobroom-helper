import builtins
from types import SimpleNamespace

from selenium.common.exceptions import TimeoutException

from jobroom_helper.config import EXECUTE_SCRIPT_CLICK
from jobroom_helper.utils import selenium_helper


def test_resolve_type_selector_known():
    # Input values are the German Job-Room terms the DataFrame now carries
    # ("Elektronisch"/"Telefonisch"); the resolved DOM selector still targets
    # the underlying 'electronic'/'phone' checkbox attributes.
    electronic_selector = selenium_helper.resolve_type_selector("elektronisch")
    assert electronic_selector is not None
    assert "electronic" in electronic_selector

    phone_selector = selenium_helper.resolve_type_selector("telefonisch")
    assert phone_selector is not None
    assert "phone" in phone_selector

    assert (
        selenium_helper.resolve_type_selector(
            {"type": "string", "string": "Vorstellungsgespräch"}
        )
        == "//label[normalize-space()='Vorstellungsgespräch']"
    )
    assert selenium_helper.resolve_type_selector("unknown") is None


def test_get_notion_scalar_value_extracts_wrapped_string():
    value = "{'type': 'string', 'string': 'Vorstellungsgespräch'}"

    assert selenium_helper.get_notion_scalar_value(value) == "Vorstellungsgespräch"
    assert (
        selenium_helper.get_notion_scalar_value({"type": "string", "string": "x"})
        == "x"
    )
    assert selenium_helper.get_notion_scalar_value("plain") == "plain"


def test_fill_text_calls_clear_and_send_keys():
    calls = SimpleNamespace(cleared=False, sent=None)

    class Elem:
        def clear(self):
            calls.cleared = True

        def send_keys(self, v):
            calls.sent = v

    e = Elem()
    selenium_helper.fill_text(e, "Role", "Developer")
    assert calls.cleared is True
    assert calls.sent == "Developer"


def test_fill_checkbox_and_radio_execute_script(monkeypatch):
    executed = []

    class Driver:
        def execute_script(self, script, element):
            executed.append(script)

    class Elem:
        def __init__(self, visible=True):
            self._vis = visible

        def is_displayed(self):
            return self._vis

    d = Driver()
    visible_elem = Elem(True)
    selenium_helper.fill_checkbox(d, visible_elem, "CheckMe")
    assert executed

    executed.clear()
    selenium_helper.fill_radio(d, visible_elem, "Radio", True)
    assert executed


def test_fill_checkbox_and_radio_skip_unselected_elements():
    """Test that checkbox and radio filling skips hidden elements."""
    executed = []

    class Driver:
        def execute_script(self, script, element):
            executed.append(script)

    class Elem:
        def is_displayed(self):
            return False

    element = Elem()
    selenium_helper.fill_checkbox(Driver(), element, "Hidden")
    selenium_helper.fill_radio(Driver(), element, "Radio", False)

    assert executed == []


def test_get_notion_scalar_value_returns_original_for_malformed_literal():
    """Test that malformed literal strings are returned unchanged."""
    value = "{'type': 'string'"

    assert selenium_helper.get_notion_scalar_value(value) == value


def test_fill_field_saves_screenshot_on_webdriver_error():
    """Test that fill_field saves a screenshot when a timeout occurs."""
    screenshots = []

    class Wait:
        def until(self, condition):
            raise TimeoutException("missing")

    class Driver:
        def save_screenshot(self, path):
            screenshots.append(path)

    selenium_helper.fill_field(Driver(), Wait(), "Role", "input.role", "Engineer")

    assert screenshots == ["results/jobroom_fill_field_error.png"]


def test_fill_field_type_unknown_returns_none():
    # When Type resolves to None, fill_field should return early
    result = selenium_helper.fill_field(
        None, None, "Type", "selector", "unknown", row={}
    )
    assert result is None


def test_fill_field_interview_skips_non_interview_value():
    result = selenium_helper.fill_field(
        None,
        None,
        "Interview",
        "dummy",
        {"type": "string", "string": "Electronic"},
        row={},
    )
    assert result is None


def test_fill_field_interview_clicks_wrapped_interview_value():
    executed = []
    waited_for = []

    class Elem:
        def is_displayed(self):
            return True

    class Wait:
        def until(self, arg):
            waited_for.append(arg)
            return Elem()

    class Driver:
        def execute_script(self, script, *args):
            executed.append(script)

    selenium_helper.fill_field(
        Driver(),
        Wait(),
        "Interview",
        "dummy",
        "{'type': 'string', 'string': 'Vorstellungsgespräch'}",
        row={},
    )

    assert waited_for
    assert any(script == selenium_helper.EXECUTE_SCRIPT_CLICK for script in executed)


def test_fill_field_text_branch(monkeypatch):
    class Elem:
        def __init__(self):
            self.cleared = False
            self.sent = None

        def clear(self):
            self.cleared = True

        def send_keys(self, v):
            self.sent = v

        def get_attribute(self, k):
            return self.sent or ""

    class Wait:
        def until(self, arg):
            return Elem()

    class Driver:
        def execute_script(self, *args, **kwargs):
            return None

    selenium_helper.fill_field(Driver(), Wait(), "Role", "input.foo", "Engineer")


def test_get_entries_returns_empty_on_exception():
    class Driver:
        def find_elements(self, *args, **kwargs):
            raise selenium_helper.NoSuchElementException("boom")

    assert selenium_helper._get_entries(Driver()) == []


def test_get_month_year_pairs_parses_unique_dates():
    class DataFrameLike:
        def __init__(self, values):
            self.values = values
            self.empty = False

        def get(self, key, default=None):
            return self.values.get(key, default)

    df = DataFrameLike(
        {
            "Applied date": [
                "2026-07-01",
                "2026-07-15",
                "2026-08-15",
                None,
                "invalid",
            ]
        }
    )

    assert selenium_helper._get_month_year_pairs(df) == [("2026", 7), ("2026", 8)]


def test_find_existing_entry_matches_exact_then_fallback():
    class Entry:
        def __init__(self, text):
            self.text = text

    class Driver:
        def __init__(self, entries):
            self.entries = entries

        def find_elements(self, *args, **kwargs):
            return self.entries

    exact_entry = selenium_helper._find_existing_entry(
        Driver([Entry("Acme Consulting Developer")]), "Acme", "Developer"
    )
    assert exact_entry is not None

    prefix_entry = selenium_helper._find_existing_entry(
        Driver([Entry("Acme Labs Developer")]), "Acme Solutions", "Developer"
    )
    assert prefix_entry is not None


def test_find_entry_by_company_prefix():
    class Entry:
        def __init__(self, text):
            self.text = text

    entries = [Entry("Acme GmbH")]
    result = selenium_helper._find_entry_by_company_prefix(entries, "Acme Solutions")
    assert result is not None


def test_format_absagegrund_parses_date_and_falls_back():
    assert (
        selenium_helper._format_absagegrund("2026-07-01", "Reason") == "01.07: Reason"
    )
    assert selenium_helper._format_absagegrund("invalid", "Reason") == (
        "invalid: Reason"
    )


def test_is_absagegrund_candidate_filters_non_reason_fields():
    class Elem:
        def __init__(self, el_id, visible=True):
            self._id = el_id
            self._visible = visible

        def get_attribute(self, key):
            return self._id if key == "id" else ""

        def is_displayed(self):
            return self._visible

    assert not selenium_helper._is_absagegrund_candidate(Elem("company-name"))
    assert selenium_helper._is_absagegrund_candidate(Elem("reason-field"))


def test_find_absagegrund_in_entry_prefers_reason_field():
    class Elem:
        def __init__(self, el_id):
            self._id = el_id

        def get_attribute(self, key):
            return self._id if key == "id" else ""

        def is_displayed(self):
            return True

    class Entry:
        def find_elements(self, by, selector):
            return [Elem("company-name"), Elem("reason-text")]

    element = selenium_helper._find_absagegrund_in_entry(Entry())
    assert element is not None
    assert element.get_attribute("id") == "reason-text"


def test_find_absagegrund_fallback_calls_wait():
    class Wait:
        def __init__(self):
            self.called = False

        def until(self, arg):
            self.called = True
            return "fallback"

    wait = Wait()
    assert selenium_helper._find_absagegrund_fallback(wait) == "fallback"
    assert wait.called


def test_fill_absagegrund_uses_fallback_if_no_inline_field(monkeypatch):
    element_state = {}

    class Elem:
        def clear(self):
            element_state["cleared"] = True

        def send_keys(self, value):
            element_state["sent"] = value

    class Entry:
        def find_elements(self, by, selector):
            return []

    class Wait:
        def until(self, arg):
            return Elem()

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    selenium_helper._fill_absagegrund(Driver(), Wait(), Entry(), "01.07: Reason")
    assert element_state["cleared"] is True
    assert element_state["sent"] == "01.07: Reason"


def test_update_notion_tracked_prints_status(monkeypatch):
    """Tracker updates print distinct success and failure messages."""
    printed = []

    class Notion:
        def __init__(self, result):
            self.result = result

        def update_row(self, page_id, properties):
            assert page_id == "page123"
            assert properties == {"Tracked": {"checkbox": True}}
            return self.result

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(args))
    selenium_helper._update_notion_tracked(Notion(True), "page123")
    selenium_helper._update_notion_tracked(Notion(False), "page123")
    assert any("Record processed" in item for args in printed for item in args)
    assert any(
        "Failed to update tracker record." in item for args in printed for item in args
    )


def test_fill_typeahead_supports_suggestion_and_enter(monkeypatch):
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class Elem:
        def __init__(self):
            self.values = []
            self._displayed = True

        def is_displayed(self):
            return self._displayed

        def send_keys(self, value):
            self.values.append(value)

        def get_attribute(self, key):
            return "" if key != "value" else "Developer"

    class Suggestion:
        def click(self):
            self.clicked = True

    class Wait:
        def __init__(self, mode):
            self.mode = mode

        def until(self, arg):
            if self.mode == "suggestion":
                return Suggestion()
            raise TimeoutException("timeout")

    driver = SimpleNamespace(execute_script=lambda *args, **kwargs: None)
    element = Elem()
    selenium_helper.fill_typeahead(
        driver, Wait("suggestion"), element, "Role", "Developer"
    )
    assert element.values == ["Developer"]

    fallback_element = Elem()
    selenium_helper.fill_typeahead(
        driver, Wait("timeout"), fallback_element, "Role", "Developer"
    )
    assert fallback_element.values[-1] == selenium_helper.Keys.ENTER


def test_expand_month_section_and_process_rejected_entry(monkeypatch):
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class FakeElement:
        def __init__(self, text=""):
            self.text = text

    class Driver:
        def __init__(self):
            self.scripts = []
            self.find_calls = []

        def find_elements(self, by, selector):
            self.find_calls.append(selector)
            if "collapsed" in selector:
                return [FakeElement()]
            return []

        def execute_script(self, *args, **kwargs):
            self.scripts.append(args)

    class FakeRow:
        def __init__(self):
            self._values = {
                "Company": "Acme",
                "Role": "Developer",
                "Last Update Date": "2026-07-01",
                "Update Details": "No fit",
            }

        def get(self, key, default=None):
            return self._values.get(key, default)

    driver = Driver()
    df = SimpleNamespace(empty=False, get=lambda key, default=None: ["2026-07-01"])
    selenium_helper._expand_month_section(driver, df)
    assert driver.scripts

    called = {}
    monkeypatch.setattr(
        selenium_helper,
        "_search_for_company",
        lambda *_args, **_kwargs: called.setdefault("searched", True) or True,
    )
    monkeypatch.setattr(
        selenium_helper,
        "_find_existing_entry",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        selenium_helper,
        "_update_rejected_entry",
        lambda *args, **kwargs: called.setdefault("updated", True),
    )
    monkeypatch.setattr(
        selenium_helper,
        "_report_missing_entry",
        lambda *args, **kwargs: called.setdefault("missing", True),
    )

    selenium_helper._process_rejected_entry(driver, None, None, FakeRow(), 0, 1)
    assert called.get("searched") is True
    assert called.get("updated") is True


def _install_fake_webdriverwait(monkeypatch, *, found_selectors=None, missing=False):
    """Patch selenium_helper.WebDriverWait with a fake that resolves locators.

    handle_login now clicks via WebDriverWait(...).until(
    ec.element_to_be_clickable(locator)). The fake records every locator it is
    asked for on the driver (so tests can assert which controls were sought) and
    either returns a clickable stub or raises TimeoutException to simulate a
    control that never renders.

    Args:
        found_selectors: if given, only these selectors resolve; others time out.
        missing: if True, every locator times out (no control present).
    """

    class FakeWait:
        def __init__(self, driver, timeout):
            self.driver = driver

        def until(self, condition):
            locator = getattr(condition, "_locator", None)
            selector = locator[1] if locator else None
            if hasattr(self.driver, "sought"):
                self.driver.sought.append(selector)
            if missing or (
                found_selectors is not None and selector not in found_selectors
            ):
                raise selenium_helper.TimeoutException("not clickable")
            return SimpleNamespace(click=lambda: None)

    # ec.element_to_be_clickable returns a callable; stash the locator on it so
    # the fake wait can inspect which control was requested.
    def fake_clickable(locator):
        cond = lambda driver: True  # noqa: E731
        cond._locator = locator
        return cond

    monkeypatch.setattr(selenium_helper, "WebDriverWait", FakeWait)
    monkeypatch.setattr(selenium_helper.ec, "element_to_be_clickable", fake_clickable)


def test_click_when_ready_primary_succeeds(monkeypatch):
    clicked = []
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        selenium_helper.ec,
        "element_to_be_clickable",
        lambda loc: type("C", (), {"_locator": loc})(),
    )

    class FakeWait:
        def __init__(self, driver, timeout):
            self.timeout = timeout

        def until(self, condition):
            if condition._locator[1] == "primary.css":
                return SimpleNamespace(click=lambda: clicked.append("primary"))
            raise selenium_helper.TimeoutException("nope")

    monkeypatch.setattr(selenium_helper, "WebDriverWait", FakeWait)

    result = selenium_helper._click_when_ready(
        driver=object(),
        primary=(selenium_helper.By.CSS_SELECTOR, "primary.css"),
        fallback=(selenium_helper.By.XPATH, "//fallback"),
        label="Login button",
    )
    assert result is True
    assert clicked == ["primary"]


def test_click_when_ready_falls_back_to_secondary(monkeypatch):
    clicked = []
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        selenium_helper.ec,
        "element_to_be_clickable",
        lambda loc: type("C", (), {"_locator": loc})(),
    )

    class FakeWait:
        def __init__(self, driver, timeout):
            self.timeout = timeout

        def until(self, condition):
            # Primary CSS times out; text-based XPath fallback succeeds.
            if condition._locator[1] == "//fallback":
                return SimpleNamespace(click=lambda: clicked.append("fallback"))
            raise selenium_helper.TimeoutException("primary not clickable")

    monkeypatch.setattr(selenium_helper, "WebDriverWait", FakeWait)

    result = selenium_helper._click_when_ready(
        driver=object(),
        primary=(selenium_helper.By.CSS_SELECTOR, "primary.css"),
        fallback=(selenium_helper.By.XPATH, "//fallback"),
        label="AGOV button",
    )
    assert result is True
    assert clicked == ["fallback"]


def test_click_when_ready_both_missing_returns_false(monkeypatch):
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        selenium_helper.ec,
        "element_to_be_clickable",
        lambda loc: type("C", (), {"_locator": loc})(),
    )

    class FakeWait:
        def __init__(self, driver, timeout):
            pass

        def until(self, condition):
            raise selenium_helper.TimeoutException("never clickable")

    monkeypatch.setattr(selenium_helper, "WebDriverWait", FakeWait)

    result = selenium_helper._click_when_ready(
        driver=object(),
        primary=(selenium_helper.By.CSS_SELECTOR, "primary.css"),
        fallback=(selenium_helper.By.XPATH, "//fallback"),
        label="Login button",
        already_message="already on login page?",
    )
    assert result is False


def test_handle_login_falls_back_to_fresh_login(monkeypatch):
    monkeypatch.setattr(selenium_helper, "load_session", lambda driver: True)
    monkeypatch.setattr(selenium_helper, "save_session", lambda driver: None)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "")
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    _install_fake_webdriverwait(monkeypatch)

    class Driver:
        def __init__(self):
            self.current_url = "https://example.com/login"
            self.visited = []
            self.sought = []

        def get(self, url):
            self.visited.append(url)

    driver = Driver()
    assert selenium_helper.handle_login(driver) is True
    assert driver.visited[0] == selenium_helper.get_website_url()


def test_handle_login_fresh_login_with_buttons(monkeypatch):
    """Test handle_login when session is not restored and buttons are found."""
    monkeypatch.setattr(selenium_helper, "load_session", lambda driver: False)
    monkeypatch.setattr(selenium_helper, "save_session", lambda driver: None)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "")
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    _install_fake_webdriverwait(monkeypatch)

    class Driver:
        def __init__(self):
            self.current_url = "https://example.com"
            self.visited = []
            self.sought = []

        def get(self, url):
            self.visited.append(url)

    driver = Driver()
    result = selenium_helper.handle_login(driver)
    assert result is True
    # The Login control should be waited on before the manual-login pause.
    assert any("btn-primary" in (s or "") for s in driver.sought)


def test_handle_login_missing_buttons(monkeypatch):
    """Test handle_login when buttons never render (every wait times out)."""
    monkeypatch.setattr(selenium_helper, "load_session", lambda driver: False)
    monkeypatch.setattr(selenium_helper, "save_session", lambda driver: None)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "")
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    _install_fake_webdriverwait(monkeypatch, missing=True)

    class Driver:
        def __init__(self):
            self.current_url = "https://example.com"
            self.sought = []

        def get(self, url):
            pass

    driver = Driver()
    # Even when no control is found, login must not crash and still returns True
    # so the manual-login pause can run.
    result = selenium_helper.handle_login(driver)
    assert result is True


def test_process_records_flow(monkeypatch):
    """Test process_records iterates and fills fields."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "")

    fill_calls = []

    def fake_fill(driver, wait, field_name, selector, value, row=None):
        fill_calls.append((field_name, selector, value))

    monkeypatch.setattr(selenium_helper, "fill_field", fake_fill)

    class Driver:
        def __init__(self):
            self.visited = []

        def get(self, url):
            self.visited.append(url)

        def find_element(self, by, selector):
            return SimpleNamespace(click=lambda: None)

    class Notion:
        def update_row(self, page_id, properties):
            return True

    driver = Driver()
    df = SimpleNamespace(
        iterrows=lambda: [
            (
                0,
                {
                    "id": "page1",
                    "Role": "Engineer",
                    "Company": "Acme",
                },
            )
        ]
    )
    selenium_helper.process_records(driver, None, df, Notion())
    assert len(fill_calls) > 0


def test_resolve_type_selector_case_insensitive():
    """Test resolve_type_selector handles case variations."""
    assert selenium_helper.resolve_type_selector("ELEKTRONISCH") is not None
    assert selenium_helper.resolve_type_selector("Telefonisch") is not None
    assert selenium_helper.resolve_type_selector("VORSTELLUNGSGESPRÄCH") is not None


def test_resolve_type_selector_dict_with_string():
    """Test resolve_type_selector with dict containing string key."""
    result = selenium_helper.resolve_type_selector(
        {"type": "string", "string": "vorstellungsgespräch"}
    )
    assert result is not None
    assert "Vorstellungsgespräch" in result


def test_get_notion_scalar_value_with_complex_dict():
    """Test get_notion_scalar_value with nested dict."""
    result = selenium_helper.get_notion_scalar_value(
        {"type": "rich_text", "rich_text": [{"plain_text": "text"}]}
    )
    assert result == [{"plain_text": "text"}]


def test_fill_field_resolves_interview_type(monkeypatch):
    """Test fill_field correctly handles Interview field type."""
    waited = []
    executed = []

    class Wait:
        def until(self, arg):
            waited.append(arg)
            return SimpleNamespace(is_displayed=lambda: True)

    class Driver:
        def execute_script(self, script, elem):
            executed.append(script)

    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    selenium_helper.fill_field(
        Driver(),
        Wait(),
        "Interview",
        "dummy",
        "vorstellungsgespräch",
        row={},
    )
    assert waited
    assert executed


def test_expand_month_section_for_each_month(monkeypatch):
    """Test _expand_month_section_for handles all month names."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    calls = []

    class Driver:
        def find_elements(self, by, selector):
            calls.append(selector)
            return [SimpleNamespace(scrollIntoView=lambda: None)]

        def execute_script(self, script, elem=None):
            pass

    driver = Driver()
    # Test multiple months
    for month in ["Januar", "Februar", "März", "April", "Mai", "Juni"]:
        calls.clear()
        selenium_helper._expand_month_section_for(driver, month, "2024")
        assert calls


def test_search_for_company_types_query(monkeypatch):
    """_search_for_company finds the search box, clears it, and types company."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class FakeBox:
        def __init__(self):
            self.events = []  # ordered log of clear()/send_keys calls
            self.clicked = False
            self.cleared = False

        def click(self):
            self.clicked = True

        def clear(self):
            self.cleared = True
            self.events.append(("clear",))

        def send_keys(self, *args):
            self.events.append(args)

        def get_attribute(self, _name):
            return ""  # field reports empty after clearing

    box = FakeBox()

    class FakeWait:
        def until(self, _condition):
            return box

    class Driver:
        def __init__(self):
            self.scripts = []

        def execute_script(self, *args, **kwargs):
            self.scripts.append(args)

    result = selenium_helper._search_for_company(Driver(), FakeWait(), "Acme AG")
    assert result is True
    assert box.clicked is True
    assert box.cleared is True
    # The company name was typed into the box.
    assert any("Acme AG" in a for a in box.events)
    # Clear happens BEFORE the company string is typed (no concatenation).
    clear_idx = box.events.index(("clear",))
    type_idx = next(i for i, a in enumerate(box.events) if "Acme AG" in a)
    assert clear_idx < type_idx


def test_search_for_company_backspaces_residual_value(monkeypatch):
    """If the field still holds a prior query, it is backspaced out before typing.

    Guards the concatenated-search bug: when several rejections are processed
    in one run, a stale value must not survive into the next search.
    """
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class FakeBox:
        def __init__(self):
            self.events = []
            # Field reports a leftover query until a BACKSPACE flush occurs.
            self._value = "StaleCo"

        def click(self):
            pass

        def clear(self):
            self.events.append(("clear",))

        def send_keys(self, *args):
            self.events.append(args)
            # BACKSPACE arrives as a single string (BACKSPACE repeated N times).
            if any(
                isinstance(a, str) and selenium_helper.Keys.BACKSPACE in a for a in args
            ):
                self._value = ""  # flush clears the residual value

        def get_attribute(self, _name):
            return self._value

    box = FakeBox()

    class FakeWait:
        def until(self, _condition):
            return box

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    result = selenium_helper._search_for_company(Driver(), FakeWait(), "Acme AG")
    assert result is True
    # A BACKSPACE fallback fired to flush the residual "StaleCo" value.
    assert any(
        isinstance(k, str) and selenium_helper.Keys.BACKSPACE in k
        for a in box.events
        for k in a
    )
    assert any("Acme AG" in a for a in box.events)


def test_search_for_company_returns_false_when_box_missing(monkeypatch):
    """_search_for_company returns False gracefully if the search box isn't found."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class FakeWait:
        def until(self, _condition):
            raise selenium_helper.TimeoutException("no search box")

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    result = selenium_helper._search_for_company(Driver(), FakeWait(), "Acme AG")
    assert result is False


def test_find_entry_with_no_entries_returns_none():
    """Test _find_existing_entry when no entries exist."""

    class Driver:
        def find_elements(self, by, selector):
            return []

    result = selenium_helper._find_existing_entry(Driver(), "Acme", "Developer")
    assert result is None


def test_find_entry_by_company_with_empty_entries():
    """Test _find_entry_by_company with empty list."""
    result = selenium_helper._find_entry_by_company([], "Acme", "Developer")
    assert result is None


def test_find_entry_by_company_prefix_with_empty_company():
    """Test _find_entry_by_company_prefix with empty company name."""
    result = selenium_helper._find_entry_by_company_prefix([], "", "Developer")
    assert result is None


def test_format_absagegrund_with_invalid_date():
    """Test _format_absagegrund gracefully handles invalid dates."""
    result = selenium_helper._format_absagegrund("not-a-date", "Reason")
    assert "Reason" in result


def test_set_status_rejected_uses_fallback_xpath(monkeypatch):
    """Test _set_status_rejected falls back to XPath."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    script_calls = []
    find_calls = []

    class Driver:
        def execute_script(self, script, elem):
            script_calls.append(script)

    class Entry:
        def find_element(self, by, selector):
            find_calls.append((by, selector))
            if len(find_calls) == 1:
                raise selenium_helper.NoSuchElementException("Not found")
            return SimpleNamespace()

    driver = Driver()
    result = selenium_helper._set_status_rejected(driver, Entry())
    assert result is True
    assert find_calls == [
        (selenium_helper.By.CSS_SELECTOR, "label[for$='-REJECTED']"),
        (
            selenium_helper.By.XPATH,
            ".//label[contains(text(), 'Absage')]",
        ),
    ]
    assert script_calls


def test_set_status_rejected_returns_true_on_success(monkeypatch):
    """Test _set_status_rejected returns True when the label is clicked."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    script_calls = []

    class Driver:
        def execute_script(self, script, elem):
            script_calls.append(script)

    class Entry:
        def find_element(self, by, selector):
            return SimpleNamespace()

    driver = Driver()
    result = selenium_helper._set_status_rejected(driver, Entry())
    assert result is True
    assert script_calls


def test_check_interview_checkbox_ticks_when_unchecked(monkeypatch):
    """_check_interview_checkbox clicks the checkbox when it is not yet ticked."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    clicks = []

    class Checkbox:
        def is_selected(self):
            return False

    class Driver:
        def execute_script(self, script, elem):
            if script == selenium_helper.EXECUTE_SCRIPT_CLICK:
                clicks.append(elem)

    class Entry:
        def find_element(self, by, selector):
            return Checkbox()

    result = selenium_helper._check_interview_checkbox(Driver(), Entry())
    assert result is True
    # The checkbox was clicked exactly once (status radio never touched).
    assert len(clicks) == 1


def test_check_interview_checkbox_idempotent_when_already_checked(monkeypatch):
    """_check_interview_checkbox leaves an already-ticked checkbox untouched."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    clicks = []

    class Checkbox:
        def is_selected(self):
            return True

    class Driver:
        def execute_script(self, script, elem):
            if script == selenium_helper.EXECUTE_SCRIPT_CLICK:
                clicks.append(elem)

    class Entry:
        def find_element(self, by, selector):
            return Checkbox()

    result = selenium_helper._check_interview_checkbox(Driver(), Entry())
    assert result is True
    # No click fired — the checkbox was already selected.
    assert clicks == []


def test_find_interview_checkbox_falls_back_to_label(monkeypatch):
    """When the id selector misses, the checkbox is resolved via its label's 'for'."""

    class Checkbox:
        def is_selected(self):
            return False

    class Label:
        def get_attribute(self, name):
            return "alv-checkbox-3-interview" if name == "for" else None

    class Entry:
        def find_element(self, by, selector):
            if by == selenium_helper.By.CSS_SELECTOR:
                raise selenium_helper.NoSuchElementException("no id match")
            if by == selenium_helper.By.XPATH:
                return Label()
            if by == selenium_helper.By.ID:
                return Checkbox()
            raise selenium_helper.NoSuchElementException("unexpected")

    found = selenium_helper._find_interview_checkbox(Entry())
    assert isinstance(found, Checkbox)


def test_check_interview_checkbox_returns_false_when_missing(monkeypatch):
    """_check_interview_checkbox returns False if the checkbox cannot be found."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class Driver:
        def execute_script(self, script, elem):
            pass

    class Entry:
        def find_element(self, by, selector):
            raise selenium_helper.NoSuchElementException("missing")

    assert selenium_helper._check_interview_checkbox(Driver(), Entry()) is False


def test_process_interview_entry_updates_and_marks_tracked(monkeypatch):
    """_process_interview_entry ticks the checkbox and marks the row processed."""
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)
    monkeypatch.setattr(builtins, "input", lambda *a, **k: "")

    monkeypatch.setattr(selenium_helper, "_search_for_company", lambda *a, **k: True)
    entry = SimpleNamespace()
    monkeypatch.setattr(selenium_helper, "_find_existing_entry", lambda *a, **k: entry)
    monkeypatch.setattr(
        selenium_helper, "_check_interview_checkbox", lambda *a, **k: True
    )

    tracked = []

    class Store:
        def update_row(self, page_id, properties):
            tracked.append((page_id, properties))
            return True

    class Driver:
        def execute_script(self, *a, **k):
            pass

    row = {"id": 42, "Company": "Acme", "Role": "Architect"}
    selenium_helper._process_interview_entry(Driver(), None, Store(), row, 0, 1)

    # The tracker row was marked processed (Tracked=True).
    assert tracked and tracked[0][0] == 42
    assert tracked[0][1]["Tracked"]["checkbox"] is True


def test_matches_role_empty_role_always_matches():
    """A falsy role should match any entry."""

    class Entry:
        text = "Some Company Developer"

    assert selenium_helper._matches_role(Entry(), None) is True
    assert selenium_helper._matches_role(Entry(), "") is True


def test_matches_role_checks_first_word_of_role():
    class Entry:
        text = "Acme Corp Senior Developer"

    assert selenium_helper._matches_role(Entry(), "Developer Backend") is True
    assert selenium_helper._matches_role(Entry(), "Manager Backend") is False


def test_find_entry_by_company_requires_matching_role():
    """Regression test: entries matching the company name but not the role
    should NOT be returned, to avoid mixing up multiple applications to the
    same company for different positions."""

    class Entry:
        def __init__(self, text):
            self.text = text

    entries = [Entry("Acme Corp Manager")]

    # Company matches but role does not -> no match
    assert (
        selenium_helper._find_entry_by_company(entries, "Acme", role="Developer")
        is None
    )

    # Company and role both match -> match
    assert (
        selenium_helper._find_entry_by_company(entries, "Acme", role="Manager")
        is entries[0]
    )


def test_find_entry_by_company_prefix_requires_matching_role():
    """Regression test: prefix matching must also respect the role filter."""

    class Entry:
        def __init__(self, text):
            self.text = text

    entries = [Entry("Acme Solutions Manager")]

    assert (
        selenium_helper._find_entry_by_company_prefix(
            entries, "Acme GmbH", role="Developer"
        )
        is None
    )
    assert (
        selenium_helper._find_entry_by_company_prefix(
            entries, "Acme GmbH", role="Manager"
        )
        is entries[0]
    )


def test_get_month_year_pairs_with_none_dataframe():
    """Test _get_month_year_pairs returns [] when df is None."""
    assert selenium_helper._get_month_year_pairs(None) == []


def test_get_month_year_pairs_with_empty_dataframe():
    """Test _get_month_year_pairs returns [] when df.empty is True."""

    class EmptyDf:
        empty = True

    assert selenium_helper._get_month_year_pairs(EmptyDf()) == []


def test_get_month_year_pairs_skips_short_date_parts():
    """Dates without at least a year-month part should be skipped."""

    class DataFrameLike:
        empty = False

        def get(self, key, default=None):
            return ["2026"]  # only a year, no month part

    assert selenium_helper._get_month_year_pairs(DataFrameLike()) == []


def test_expand_month_section_returns_early_for_empty_dataframe(monkeypatch):
    """_expand_month_section should not query the driver when there are no
    month/year pairs to expand."""

    class Driver:
        def find_elements(self, *args, **kwargs):
            raise AssertionError("find_elements should not be called")

    class EmptyDf:
        empty = True

    selenium_helper._expand_month_section(Driver(), EmptyDf())


def test_update_rejected_entry_stops_when_status_fails(monkeypatch):
    """If setting status to rejected fails, the flow should stop before
    attempting to fill the Absagegrund field or updating Notion."""
    calls = {"fill": False, "input": False, "notion": False}

    monkeypatch.setattr(selenium_helper, "_set_status_rejected", lambda *a, **k: False)
    monkeypatch.setattr(
        selenium_helper,
        "_fill_absagegrund",
        lambda *a, **k: calls.__setitem__("fill", True),
    )
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: calls.__setitem__("input", True)
    )
    monkeypatch.setattr(
        selenium_helper,
        "_update_notion_tracked",
        lambda *a, **k: calls.__setitem__("notion", True),
    )
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    selenium_helper._update_rejected_entry(
        Driver(), None, None, {"id": "p1"}, "Acme", "01.07: Reason", entry=object()
    )

    assert calls == {"fill": False, "input": False, "notion": False}


def test_update_rejected_entry_stops_when_absagegrund_fails(monkeypatch):
    """If filling the Absagegrund field fails, Notion should not be updated."""
    calls = {"input": False, "notion": False}

    monkeypatch.setattr(selenium_helper, "_set_status_rejected", lambda *a, **k: True)
    monkeypatch.setattr(selenium_helper, "_fill_absagegrund", lambda *a, **k: False)
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: calls.__setitem__("input", True)
    )
    monkeypatch.setattr(
        selenium_helper,
        "_update_notion_tracked",
        lambda *a, **k: calls.__setitem__("notion", True),
    )
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    selenium_helper._update_rejected_entry(
        Driver(), None, None, {"id": "p1"}, "Acme", "01.07: Reason", entry=object()
    )

    assert calls == {"input": False, "notion": False}


def test_update_rejected_entry_completes_when_both_steps_succeed(monkeypatch):
    """When both status update and Absagegrund fill succeed, Notion should
    be updated and the user prompted to confirm."""
    calls = {"input": False, "notion_page_id": None}

    monkeypatch.setattr(selenium_helper, "_set_status_rejected", lambda *a, **k: True)
    monkeypatch.setattr(selenium_helper, "_fill_absagegrund", lambda *a, **k: True)
    monkeypatch.setattr(
        "builtins.input", lambda *a, **k: calls.__setitem__("input", True)
    )
    monkeypatch.setattr(
        selenium_helper,
        "_update_notion_tracked",
        lambda notion, page_id: calls.__setitem__("notion_page_id", page_id),
    )
    monkeypatch.setattr(selenium_helper.time, "sleep", lambda *_: None)

    class Driver:
        def execute_script(self, *args, **kwargs):
            pass

    selenium_helper._update_rejected_entry(
        Driver(), None, None, {"id": "p1"}, "Acme", "01.07: Reason", entry=object()
    )

    assert calls["input"] is True
    assert calls["notion_page_id"] == "p1"


def test_resolve_element_type_field_uses_xpath_for_slash_selector_v2(monkeypatch):
    """Test _resolve_element uses XPath locator when resolve_type_selector
    returns an XPath-style selector (starting with '//')."""

    # Track what expected_conditions was called with
    ec_calls = []

    # Mock ec.presence_of_element_located to capture the locator tuple
    class FakeEC:
        @staticmethod
        def presence_of_element_located(locator):
            ec_calls.append(locator)
            return lambda driver: SimpleNamespace()

    class Wait:
        def until(self, arg):
            return SimpleNamespace()

    monkeypatch.setattr(
        selenium_helper,
        "resolve_type_selector",
        lambda value: "//label[normalize-space()='Vorstellungsgespräch']",
    )

    # Replace ec in the module
    original_ec = selenium_helper.ec
    selenium_helper.ec = FakeEC()

    try:
        selenium_helper._resolve_element(
            Wait(), "Type", "dummy", "vorstellungsgespräch", row={}
        )

        assert ec_calls
        locator = ec_calls[0]
        assert locator[0] == selenium_helper.By.XPATH
    finally:
        selenium_helper.ec = original_ec


def test_resolve_element_type_field_uses_css_for_plain_selector_v2(monkeypatch):
    """Test _resolve_element uses CSS selector locator for non-XPath selectors."""

    # Track what expected_conditions was called with
    ec_calls = []

    # Mock ec.presence_of_element_located to capture the locator tuple
    class FakeEC:
        @staticmethod
        def presence_of_element_located(locator):
            ec_calls.append(locator)
            return lambda driver: SimpleNamespace()

    class Wait:
        def until(self, arg):
            return SimpleNamespace()

    monkeypatch.setattr(
        selenium_helper,
        "resolve_type_selector",
        lambda value: "label[for*='alv-checkbox-portal'][for*='electronic']",
    )

    # Replace ec in the module
    original_ec = selenium_helper.ec
    selenium_helper.ec = FakeEC()

    try:
        selenium_helper._resolve_element(Wait(), "Type", "dummy", "electronic", row={})

        assert ec_calls
        locator = ec_calls[0]
        assert locator[0] == selenium_helper.By.CSS_SELECTOR
    finally:
        selenium_helper.ec = original_ec


def test_fill_field_skips_empty_text_value(monkeypatch):
    """Empty text values must be skipped: no element resolved, nothing typed."""
    resolved = {"called": False}

    def fake_resolve(*args, **kwargs):
        resolved["called"] = True
        return object()

    monkeypatch.setattr(selenium_helper, "_resolve_element", fake_resolve)

    class Driver:
        def execute_script(self, *args, **kwargs):
            raise AssertionError("should not fill an empty field")

    class Wait:
        def until(self, arg):
            raise AssertionError("should not resolve an empty field")

    for empty in ("", "nan", "none", None, float("nan")):
        selenium_helper.fill_field(Driver(), Wait(), "Street", "input.street", empty)

    assert resolved["called"] is False


def test_fill_field_empty_radio_still_processed():
    """Radio fields carry fixed flags, not text, so they are not skipped."""
    seen = {"resolved": False, "scripts": []}

    class Elem:
        pass

    class Wait:
        def until(self, arg):
            seen["resolved"] = True
            return Elem()

    class Driver:
        def execute_script(self, *args, **kwargs):
            seen["scripts"].append(args[0])
            return None

    # value "false" is a flag for a radio selector – must NOT be skipped:
    # the element is resolved and the radio is clicked via execute_script.
    selenium_helper.fill_field(
        Driver(), Wait(), "RAV", "label[for*='radio-button-']", "false"
    )
    assert seen["resolved"] is True
    assert EXECUTE_SCRIPT_CLICK in seen["scripts"]

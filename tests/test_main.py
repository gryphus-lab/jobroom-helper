import builtins
from datetime import datetime, timezone
from typing import Any, cast

import httpcore
import httpx
import pandas as pd
import pytest

from jobroom_helper import __main__ as main_mod

# Real implementation captured at import time, before the autouse fixture
# stubs it out, so fallback-specific tests can exercise the genuine function.
_REAL_SCRAPE_WITH_BROWSER = main_mod._scrape_with_browser


@pytest.fixture(autouse=True)
def _disable_browser_fallback(monkeypatch):
    """By default, disable the Selenium browser fallback in _scrape_url so unit
    tests exercise the HTTP path in isolation and never launch a real browser.
    Tests that specifically cover the fallback re-patch _scrape_with_browser."""
    monkeypatch.setattr(main_mod, "_scrape_with_browser", lambda url: None)


class FakeDriver:
    def __init__(self):
        self.screenshots = []
        self.quit_called = False
        self.current_url = "https://example.com"

    def get(self, url):
        self.current_url = url

    def save_screenshot(self, path):
        self.screenshots.append(path)

    def quit(self):
        self.quit_called = True


class FakeWait:
    def __init__(self, driver, timeout):
        self.driver = driver
        self.timeout = timeout


class _ImmediateWait:
    def __init__(self, driver, timeout):
        self.driver = driver
        self.timeout = timeout

    def until(self, condition):
        return condition(self.driver)


def _client_for_response(response, **kwargs):
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return response

    return FakeClient(**kwargs)


class FakeStore:
    def __init__(self, df=None):
        self.df = df if df is not None else pd.DataFrame()
        self.calls = []

    def get_database_data(self, database_id=None, filter=None):
        """Record a lookup and return an isolated copy of the fixture data."""
        self.calls.append(("get", filter))
        return self.df.copy()

    def update_row(self, page_id, properties):
        """Record a successful tracker update."""
        self.calls.append(("update", page_id, properties))
        return True

    def create_page(self, database_id=None, properties=None, prop_name_map=None):
        """Record a tracker create and return a stable fake id."""
        self.calls.append(("create", properties))
        return "new-page-id"


def _create_call(store):
    """Return the create_page call from FakeStore.calls, ignoring lookups."""
    for call in store.calls:
        if call[0] == "create":
            return call
    raise AssertionError("create_page was not called")


# Backwards-compatible alias for tests that still build a fake store instance.
FakeNotion = FakeStore


def test_existing_company_address_uses_company_filter():
    """Existing-address lookups filter tracker rows by exact company name."""
    store = FakeStore(pd.DataFrame({"Address": ["Main Street 1"]}))

    address = main_mod._existing_company_address(store, "Acme")

    assert address == "Main Street 1"
    assert store.calls == [
        ("get", {"property": "Company", "rich_text": {"equals": "Acme"}})
    ]


def test_extract_formatted_field_and_monday_helpers():
    assert main_mod.extract_formatted_field("{'string': 'x'}") == "x"
    assert main_mod.extract_formatted_field("bad") == "bad"

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert main_mod._first_monday_on_or_after(start) == start

    monday = datetime(2024, 1, 8, tzinfo=timezone.utc)
    assert (
        main_mod._first_monday_on_or_after(datetime(2024, 1, 7, tzinfo=timezone.utc))
        == monday
    )

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(main_mod, "datetime", FakeDateTime)
        start_date, end_date = main_mod._get_open_period()
        assert start_date
        assert end_date
    finally:
        monkeypatch.undo()


class FakeDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2024, 2, 1, tzinfo=timezone.utc)


def test_get_month_and_rejected_filters_use_shared_dates(monkeypatch):
    monkeypatch.setattr(
        main_mod, "_get_open_period", lambda: ("2024-01-01", "2024-02-05")
    )

    month_filter = main_mod.get_month_filter()
    rejected_filter = main_mod.get_rejected_filter()

    assert month_filter["and"][0]["property"] == main_mod.APPLIED_DATE
    assert rejected_filter["and"][1]["property"] == main_mod.APPLIED_DATE
    assert month_filter["and"][2]["property"] == "Tracked"
    assert rejected_filter["and"][2]["property"] == "Tracked"
    assert rejected_filter["and"][3]["property"] == "Stage"


def test_create_arg_parser_uses_expected_defaults():
    """Test that create argument parser defaults are correct."""
    args = main_mod._create_arg_parser().parse_args(["https://example.com/job"])

    assert args.url == "https://example.com/job"
    assert args.dry_run is False
    assert args.company_override is None
    assert args.role_override is None


def test_create_arg_parser_parses_optional_arguments():
    """Test that create argument parser handles all optional flags."""
    args = main_mod._create_arg_parser().parse_args(
        [
            "https://example.com/job",
            "--dry-run",
            "--company",
            "Acme",
            "--role",
            "Software Engineer",
        ]
    )

    assert args.url == "https://example.com/job"
    assert args.dry_run is True
    assert args.company_override == "Acme"
    assert args.role_override == "Software Engineer"


def test_run_create_from_args_requires_arguments(capsys):
    """Test that run_create_from_args exits when no arguments are provided."""
    with pytest.raises(SystemExit) as exc_info:
        main_mod._run_create_from_args(None, [])

    assert exc_info.value.code == 1
    assert f"Usage: {main_mod.CREATE_USAGE}" in capsys.readouterr().out


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_create_from_args_forwards_options(monkeypatch, dry_run):
    """Test that run_create_from_args correctly forwards parsed options.

    Dry runs do not construct or receive a database store.
    """
    created_store = object()
    calls = []

    monkeypatch.setattr(
        main_mod,
        "_run_create",
        lambda store, url, **kwargs: calls.append((store, url, kwargs)),
    )
    monkeypatch.setattr(main_mod, "ApplicationStore", lambda: created_store)

    main_mod._run_create_from_args(
        None,
        [
            "https://example.com/job",
            *(["--dry-run"] if dry_run else []),
            "--company",
            "Acme",
            "--role",
            "Software Engineer",
        ],
    )

    assert calls == [
        (
            None if dry_run else created_store,
            "https://example.com/job",
            {
                "dry_run": dry_run,
                "company_override": "Acme",
                "role_override": "Software Engineer",
            },
        )
    ]


def test_prepare_dataframe_transforms_columns():
    df = pd.DataFrame(
        [
            {
                "Date": "{'string': '2024-01-01'}",
                "Type": "{'string': 'electronic'}",
                "PLZ_Ort": "12345 Bern",
            }
        ]
    )

    main_mod.prepare_dataframe(df)

    assert df["Date"].iloc[0] == "01.01.2024"
    assert df["Type"].iloc[0] == "electronic"
    assert df["PLZ_Ort"].iloc[0] == "1234"
    assert df["RAV"].iloc[0] == "false"
    assert df["Arbeitspensum"].iloc[0] == "false"
    assert df["Status"].iloc[0] == "false"


def test_scrape_url_extracts_metadata_with_beautifulsoup(monkeypatch):
    class Response:
        status_code = 200
        text = (
            "<html><title>Engineer</title>"
            '<meta name="description" content="Build systems">'
            "<h1>Senior Engineer</h1></html>"
        )

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response())
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/1")

    assert result == {
        "url": "https://93.184.216.34/jobs/1",
        "title": "Engineer",
        "description": "Build systems",
        "h1": "Senior Engineer",
        "text": "Engineer\nSenior Engineer",
    }


def test_scrape_with_beautifulsoup_extracts_company_from_nested_json_ld_graph():
    """Test that company extraction handles nested JSON-LD graph arrays."""
    result = main_mod._scrape_with_beautifulsoup(
        """
                <html>
                    <head>
                        <script type="application/ld+json">
                            {"@context":"https://schema.org","@graph":[
                                {"@type":"JobPosting","hiringOrganization":{"name":"Acme"}}
                            ]}
                        </script>
                    </head>
                    <body><h1>Engineer</h1></body>
                </html>
                """,
        {},
    )

    assert result["company"] == "Acme"


def test_scrape_with_beautifulsoup_extracts_company_from_object_json_ld_graph():
    """Test that company extraction handles JSON-LD graph objects."""
    result = main_mod._scrape_with_beautifulsoup(
        """
                <script type="application/ld+json">
                    {"@graph":{"@type":"JobPosting",
                        "hiringOrganization":{"name":"Globex"}}}
                </script>
                """,
        {},
    )

    assert result["company"] == "Globex"


def test_scrape_url_uses_og_description_and_regex_fallback(monkeypatch):
    class Response:
        status_code = 200
        text = (
            "<html><title>Engineer</title>"
            '<meta property="og:description" content="Ship products">'
            "<h1>Platform Engineer</h1></html>"
        )

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response())
    )
    monkeypatch.setattr(
        main_mod,
        "BeautifulSoup",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("parser error")),
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/2")

    assert result["title"] == "Engineer"
    assert result["description"] == "Ship products"
    assert result["h1"] == "Platform Engineer"


def test_regex_page_text_excludes_noscript_content():
    result = main_mod._scrape_with_regex(
        "<html><body><noscript>secret</noscript><p>Visible job</p></body></html>",
        {"url": "https://93.184.216.34/jobs/1"},
    )

    assert result["text"] == "Visible job"


def test_scrape_url_allows_captcha_in_valid_description(monkeypatch):
    class Response:
        status_code = 200
        text = (
            "<html><title>Engineer</title><h1>Engineer</h1>"
            "<p>CAPTCHA training.</p></html>"
        )

    monkeypatch.setattr(
        main_mod.httpx,
        "Client",
        lambda **kwargs: _client_for_response(Response()),
    )

    assert "blocked" not in main_mod._scrape_url("https://93.184.216.34/jobs/1")


def test_scrape_url_marks_blocking_body_text(monkeypatch):
    class Response:
        status_code = 200
        text = (
            "<html><title>Engineer</title><h1>Engineer</h1>"
            "<body>Access Denied</body></html>"
        )

    monkeypatch.setattr(
        main_mod.httpx,
        "Client",
        lambda **kwargs: _client_for_response(Response()),
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/blocked-body")

    assert result["blocked"] == "The website returned an access-blocked page"


def test_scrape_url_marks_access_blocked_pages(monkeypatch):
    class Response:
        status_code = 403
        text = "<html><title>Blocked - Indeed.com</title><h1>Access Denied</h1></html>"

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response())
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/blocked")

    assert result["blocked"] == "The website returned an access-blocked page"


def test_scrape_url_sends_browser_headers(monkeypatch):
    """The HTTP fetch must send realistic browser headers so soft anti-bot
    walls (e.g. Indeed) do not immediately serve a block page."""
    captured = {}

    class Response:
        status_code = 200
        text = "<html><title>Role</title><h1>Role</h1></html>"

    def fake_client(**kwargs):
        captured.update(kwargs)
        return _client_for_response(Response())

    monkeypatch.setattr(main_mod.httpx, "Client", fake_client)
    main_mod._scrape_url("https://93.184.216.34/jobs/1")

    headers = captured.get("headers", {})
    assert "User-Agent" in headers
    assert "Chrome" in headers["User-Agent"]
    assert headers.get("Accept-Language", "").startswith("en")


def test_scrape_url_falls_back_to_browser_when_blocked(monkeypatch):
    """The browser fallback stays disabled unless explicitly opted in."""

    class Response:
        status_code = 403
        text = "<html><title>Blocked - Indeed.com</title></html>"

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response())
    )
    monkeypatch.delenv("ENABLE_BROWSER_FALLBACK", raising=False)
    driver_calls = []
    monkeypatch.setattr(main_mod, "_create_headless_driver", driver_calls.append)

    result = main_mod._scrape_url("https://93.184.216.34/jobs/blocked")

    assert result["blocked"] == main_mod.BLOCKED_PAGE_MESSAGE
    assert driver_calls == []


def test_scrape_url_returns_successful_browser_result(monkeypatch):
    class Response:
        status_code = 403
        text = "<html><title>Blocked</title></html>"

    browser_result = {"url": "https://93.184.216.34/jobs/1", "title": "Role"}
    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response())
    )
    monkeypatch.setenv("ENABLE_BROWSER_FALLBACK", "true")
    monkeypatch.setattr(
        main_mod, "_scrape_with_browser", lambda url, trusted=False: browser_result
    )

    assert main_mod._scrape_url(browser_result["url"]) == browser_result


def test_scrape_with_browser_returns_none_when_still_blocked(monkeypatch):
    """If the rendered page still looks blocked, the browser fallback returns
    None so the caller keeps the original blocked result."""

    class _Driver:
        page_source = "<html><title>Access Denied</title></html>"

        def set_page_load_timeout(self, *_):
            pass

        def get(self, *_):
            pass

        def execute_script(self, *_):
            return "complete"

        def quit(self):
            pass

    monkeypatch.setattr(main_mod, "_validate_external_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(main_mod, "_create_headless_driver", lambda: _Driver())
    monkeypatch.setattr(
        main_mod,
        "WebDriverWait",
        lambda driver, timeout: _ImmediateWait(driver, timeout),
    )

    assert (
        _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/blocked", trusted=True)
        is None
    )


def test_scrape_with_browser_returns_none_when_body_is_blocked(monkeypatch):
    class _Driver:
        page_source = "<html><title>Job</title><body>Access Denied</body></html>"

        def set_page_load_timeout(self, *_):
            pass

        def get(self, *_):
            pass

        def execute_script(self, *_):
            return "complete"

        def quit(self):
            pass

    monkeypatch.setattr(main_mod, "_validate_external_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(main_mod, "_create_headless_driver", lambda: _Driver())
    monkeypatch.setattr(
        main_mod,
        "WebDriverWait",
        lambda driver, timeout: _ImmediateWait(driver, timeout),
    )

    assert (
        _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/blocked", trusted=True)
        is None
    )


def test_scrape_with_browser_rejects_invalid_trusted_url(monkeypatch):
    driver_calls = []
    monkeypatch.setattr(main_mod, "_create_headless_driver", driver_calls.append)

    assert _REAL_SCRAPE_WITH_BROWSER("http://127.0.0.1", trusted=True) is None
    assert driver_calls == []


def test_scrape_with_browser_returns_none_when_driver_fails_and_quit_fails(
    monkeypatch,
):
    class _Driver:
        def set_page_load_timeout(self, *_):
            pass

        def get(self, *_):
            raise RuntimeError("browser unavailable")

        def quit(self):
            raise RuntimeError("quit failed")

    monkeypatch.setattr(main_mod, "_validate_external_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(main_mod, "_create_headless_driver", lambda: _Driver())

    assert (
        _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/1", trusted=True) is None
    )


def test_scrape_with_browser_uses_regex_when_beautifulsoup_fails(monkeypatch):
    class _Driver:
        page_source = "<html><title>Role</title><h1>Engineer</h1></html>"

        def set_page_load_timeout(self, *_):
            pass

        def get(self, *_):
            pass

        def execute_script(self, *_):
            return "complete"

        def quit(self):
            pass

    monkeypatch.setattr(main_mod, "_validate_external_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(main_mod, "_create_headless_driver", lambda: _Driver())
    monkeypatch.setattr(
        main_mod,
        "WebDriverWait",
        lambda driver, timeout: _ImmediateWait(driver, timeout),
    )
    monkeypatch.setattr(
        main_mod,
        "_scrape_with_beautifulsoup",
        lambda html, result: (_ for _ in ()).throw(RuntimeError("parser error")),
    )

    result = _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/1", trusted=True)

    assert result["h1"] == "Engineer"


def test_scrape_with_browser_rejects_untrusted_url_before_driver_creation(monkeypatch):
    driver_calls = []
    monkeypatch.setattr(main_mod, "_create_headless_driver", driver_calls.append)

    assert _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/1") is None
    assert driver_calls == []


def test_scrape_with_browser_parses_rendered_html(monkeypatch):
    """A successful browser render is parsed with the standard pipeline."""

    class _Driver:
        page_source = (
            "<html><head><title>Head of AI - ACME</title>"
            '<meta property="og:site_name" content="ACME"></head>'
            "<body><h1>Head of AI</h1></body></html>"
        )

        def set_page_load_timeout(self, *_):
            pass

        def get(self, *_):
            pass

        def execute_script(self, *_):
            return "complete"

        def quit(self):
            pass

    monkeypatch.setattr(main_mod, "_validate_external_url", lambda url: "93.184.216.34")
    monkeypatch.setattr(main_mod, "_create_headless_driver", lambda: _Driver())
    monkeypatch.setattr(
        main_mod,
        "WebDriverWait",
        lambda driver, timeout: _ImmediateWait(driver, timeout),
    )

    result = _REAL_SCRAPE_WITH_BROWSER("https://93.184.216.34/jobs/1", trusted=True)

    assert result is not None
    assert result["h1"] == "Head of AI"
    assert result["company"] == "ACME"


def test_create_headless_driver_uses_webdriver_manager(monkeypatch):
    class FakeOptions:
        def __init__(self):
            self.arguments = []
            self.experimental_options = []

        def add_argument(self, argument):
            self.arguments.append(argument)

        def add_experimental_option(self, name, value):
            self.experimental_options.append((name, value))

    class FakeManager:
        def install(self):
            return "/tmp/managed-chromedriver"

    created = {}

    monkeypatch.setattr(main_mod, "Options", FakeOptions)
    monkeypatch.setattr(main_mod, "ChromeDriverManager", FakeManager)
    monkeypatch.setattr(main_mod, "Service", lambda path: path)

    class FakeDriver:
        def execute_cdp_cmd(self, command, payload):
            created["cdp"] = (command, payload)

    def fake_chrome(service, options):
        created["driver"] = (service, options)
        return FakeDriver()

    monkeypatch.setattr(main_mod.webdriver, "Chrome", fake_chrome)

    driver = main_mod._create_headless_driver()

    assert isinstance(driver, FakeDriver)
    assert created["driver"][0] == "/tmp/managed-chromedriver"
    assert "--headless=new" in created["driver"][1].arguments
    assert created["cdp"][0] == "Page.addScriptToEvaluateOnNewDocument"


def test_create_headless_driver_uses_path_when_manager_unavailable(monkeypatch):
    created = {}

    class FakeOptions:
        def add_argument(self, argument):
            pass

        def add_experimental_option(self, name, value):
            pass

    class FakeDriver:
        def execute_cdp_cmd(self, command, payload):
            created["cdp"] = command

    monkeypatch.setattr(main_mod, "Options", FakeOptions)
    monkeypatch.setattr(main_mod, "ChromeDriverManager", None)
    monkeypatch.setattr(main_mod.shutil, "which", lambda name: "/tmp/chromedriver")
    monkeypatch.setattr(main_mod, "Service", lambda path: path)

    def fake_chrome(service, options):
        created["service"] = service
        return FakeDriver()

    monkeypatch.setattr(main_mod.webdriver, "Chrome", fake_chrome)

    assert isinstance(main_mod._create_headless_driver(), FakeDriver)
    assert created["service"] == "/tmp/chromedriver"
    assert created["cdp"] == "Page.addScriptToEvaluateOnNewDocument"


def test_scrape_url_marks_403_and_429_blocked_regardless_of_content(monkeypatch):
    """403 and 429 status codes should always be marked as blocked, even if
    the response content doesn't contain blocking markers."""

    # Test 403 with normal-looking content
    class Response403:
        status_code = 403
        text = "<html><title>Job Opening</title><h1>Software Engineer</h1></html>"

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response403())
    )
    result = main_mod._scrape_url("https://93.184.216.34/jobs/1")
    assert result["blocked"] == "The website returned an access-blocked page"

    # Test 429 with normal-looking content
    class Response429:
        status_code = 429
        text = "<html><title>Job Opening</title><h1>Software Engineer</h1></html>"

    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(Response429())
    )
    result = main_mod._scrape_url("https://93.184.216.34/jobs/2")
    assert result["blocked"] == "The website returned an access-blocked page"


def test_run_create_does_not_create_page_for_blocked_scrape(monkeypatch, capsys):
    """Blocked scrape results stop creation before the tracker is touched."""
    monkeypatch.setattr(
        main_mod,
        "_scrape_url",
        lambda url: {"url": url, "title": "Access Denied", "blocked": "blocked"},
    )
    store = FakeStore()

    with pytest.raises(SystemExit):
        main_mod._run_create(store, "https://93.184.216.34/jobs/blocked")

    output = capsys.readouterr().out
    assert "Entry was not created: blocked" in output
    assert store.calls == []


def test_scrape_url_returns_url_when_fetch_fails(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            raise RuntimeError("network unavailable")

    def fake_client_for_network_error(**kwargs):
        return FakeClient()

    monkeypatch.setattr(main_mod.httpx, "Client", fake_client_for_network_error)

    assert main_mod._scrape_url("https://93.184.216.34/jobs/3") == {
        "url": "https://93.184.216.34/jobs/3",
        "blocked": "The URL could not be fetched: network unavailable",
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "https://user:password@example.com/",
    ],
)
def test_scrape_url_rejects_ssrf_targets(url, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("network request should not be made")

    monkeypatch.setattr(main_mod.httpx, "Client", fail_if_called)

    with pytest.raises(ValueError):
        main_mod._scrape_url(url)


def test_scrape_url_disables_redirects(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = ""

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            calls.append(url)
            return Response()

    monkeypatch.setattr(main_mod.httpx, "Client", FakeClient)

    main_mod._scrape_url("https://93.184.216.34/jobs/4")

    assert calls[1] == "https://93.184.216.34/jobs/4"
    assert calls[0]["follow_redirects"] is False
    assert calls[0]["trust_env"] is False


def test_scrape_url_uses_validated_dns_address(monkeypatch):
    calls = []

    monkeypatch.setattr(
        main_mod.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs["transport"].address)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr(main_mod.httpx, "Client", FakeClient)

    main_mod._scrape_url("https://example.com/job")

    assert calls == ["93.184.216.34"]


def test_pinned_network_backend_delegates_pinned_tcp_connection():
    backend = object.__new__(main_mod._PinnedNetworkBackend)
    backend.address = "93.184.216.34"
    calls = []

    class FakeBackend:
        def connect_tcp(self, *args):
            calls.append(args)
            return "stream"

    backend.backend = cast(Any, FakeBackend())

    assert cast(Any, backend).connect_tcp(
        "example.com", 443, 2, "local", ["option"]
    ) == ("stream")
    assert calls == [("93.184.216.34", 443, 2, "local", ["option"])]


def test_scrape_url_pins_to_validated_address_preventing_dns_rebinding(monkeypatch):
    """Regression test: ensure the request uses the validated public IP even if
    DNS would later resolve to a private address (DNS rebinding attack)."""
    resolve_calls = []

    def resolve_once_public_then_private(*args, **kwargs):
        hostname = args[0]
        resolve_calls.append(hostname)
        if len(resolve_calls) == 1:
            # First call during validation: return public IP
            return [(2, 1, 6, "", ("93.184.216.34", 443))]
        else:
            # Hypothetical second call (should not happen): return private IP
            return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(
        main_mod.socket, "getaddrinfo", resolve_once_public_then_private
    )

    connected_address = None

    class FakeClient:
        def __init__(self, **kwargs):
            nonlocal connected_address
            connected_address = kwargs["transport"].address

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr(main_mod.httpx, "Client", FakeClient)

    main_mod._scrape_url("https://example.com/job")

    # Verify DNS was only called once (during validation)
    assert resolve_calls == ["example.com"]
    # Verify the connection used the validated public IP, not any later resolution
    assert connected_address == "93.184.216.34"


def test_log_scraped_values_bounds_page_text(capsys):
    text = "secret " * 100

    main_mod._log_scraped_values("https://example.com/job", {"text": text})

    output = capsys.readouterr().out
    assert f"length={len(text)}" in output
    assert text not in output


def test_scrape_url_accepts_hostname_with_public_dns(monkeypatch):
    monkeypatch.setattr(
        main_mod.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(10, 1, 6, "", ("2001:4860:4860::8888", 443, 0, 0))],
    )
    monkeypatch.setattr(
        main_mod.httpx,
        "Client",
        lambda **kwargs: _client_for_response(
            type("Response", (), {"status_code": 200, "text": ""})()
        ),
    )

    assert main_mod._scrape_url("https://example.com/job")["url"] == (
        "https://example.com/job"
    )


@pytest.mark.parametrize("status_code", [300, 500])
def test_scrape_url_marks_all_non_success_statuses_blocked(monkeypatch, status_code):
    response = type("Response", (), {"status_code": status_code, "text": ""})()
    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(response)
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/status")

    assert result["blocked"] == f"The website returned HTTP {status_code}"


def test_scrape_url_reports_general_http_failure_status(monkeypatch):
    response = type("Response", (), {"status_code": 404, "text": ""})()
    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(response)
    )

    result = main_mod._scrape_url("https://93.184.216.34/jobs/missing")

    assert result["blocked"] == "The website returned HTTP 404"


def test_scrape_url_follows_bounded_validated_redirects(monkeypatch):
    responses = iter(
        [
            type(
                "Response",
                (),
                {"status_code": 302, "headers": {"location": "/next"}, "text": ""},
            )(),
            type("Response", (), {"status_code": 200, "headers": {}, "text": ""})(),
        ]
    )
    requested_urls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, requested_url):
            requested_urls.append(requested_url)
            return next(responses)

    monkeypatch.setattr(main_mod.httpx, "Client", FakeClient)

    main_mod._scrape_url("https://93.184.216.34/jobs/start")

    assert requested_urls == [
        "https://93.184.216.34/jobs/start",
        "https://93.184.216.34/next",
    ]


def test_scrape_url_validates_redirect_target(monkeypatch):
    response = type(
        "Response",
        (),
        {
            "status_code": 302,
            "headers": {"location": "http://127.0.0.1/private"},
            "text": "",
        },
    )()
    monkeypatch.setattr(
        main_mod.httpx, "Client", lambda **kwargs: _client_for_response(response)
    )

    with pytest.raises(ValueError):
        main_mod._scrape_url("https://93.184.216.34/jobs/start")


class StubCoreResponse:
    def __init__(self, headers, chunks=()):
        self.status = 200
        self.headers = headers
        self.extensions = {}
        self.chunks = chunks
        self.closed = False

    def iter_stream(self):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_pinned_transport_rejects_oversized_content_length_and_closes_response():
    core_response = StubCoreResponse(
        [(b"content-length", str(main_mod.MAX_DOCUMENT_BYTES + 1).encode())]
    )
    transport = object.__new__(main_mod._PinnedTransport)
    transport.hostname = "example.com"
    transport.pool = cast(
        Any,
        type("Pool", (), {"handle_request": lambda self, request: core_response})(),
    )

    with pytest.raises(main_mod._DocumentTooLargeError):
        transport.handle_request(httpx.Request("GET", "https://example.com"))

    assert core_response.closed


def test_limited_response_stream_rejects_oversized_stream_without_content_length():
    core_response = StubCoreResponse(
        [], (b"x" * main_mod.MAX_DOCUMENT_BYTES, b"overflow")
    )
    stream = main_mod._LimitedResponseStream(cast(httpcore.Response, core_response))

    with pytest.raises(main_mod._DocumentTooLargeError):
        list(stream)

    assert core_response.closed


def test_run_create_dry_run_prints_canonical_properties(monkeypatch, capsys):
    """Dry-run creation prints canonical values without writing a row."""
    monkeypatch.setattr(
        main_mod,
        "_scrape_url",
        lambda url: {
            "url": url,
            "title": "Scraped title",
            "description": "Scraped description",
        },
    )
    store = FakeStore()

    main_mod._run_create(
        store,
        "https://93.184.216.34/jobs/1",
        dry_run=True,
        company_override="Acme",
        role_override="Developer",
    )

    output = capsys.readouterr().out
    assert "🔎 Scraped values from https://93.184.216.34/jobs/1:" in output
    assert "   title: [length=13, preview=Scraped title]" in output
    assert "📝 Values prepared for the tracker:" in output
    assert "   Company: [length=4, preview=Acme]" in output
    assert "   Role: [length=9, preview=Developer]" in output
    assert "   Stage: [length=7, preview=Applied]" in output
    assert "--- Dry run: properties to insert ---" in output
    assert "'Company': 'Acme'" in output
    assert "'Role': 'Developer'" in output
    assert "'Stage': 'Applied'" in output
    assert "'URL': 'https://93.184.216.34/jobs/1'" in output
    assert "   Source: [length=12, preview=Company site]" in output
    assert "   Notes: None" in output
    assert "   Last Update Date:" in output
    assert "   Update Details: [length=9, preview=New entry]" in output
    assert "'Source': 'Company site'" in output
    assert "'Notes': None" in output
    assert "'Description': 'Scraped description'" in output
    assert store.calls == []


def test_run_create_populates_zurich_fields(monkeypatch):
    """Zurich job metadata maps to the expected canonical tracker fields."""
    monkeypatch.setattr(
        main_mod,
        "_scrape_url",
        lambda url: {
            "url": url,
            "title": "Verbose page title",
            "h1": "Head Legal IT and Operations 80-100%",
            "text": "Job description text",
        },
    )
    store = FakeStore()

    main_mod._run_create(
        store,
        "https://www.careers.zurich.com/job/1369843657",
    )

    _, properties = _create_call(store)
    assert properties["Company"] == "Zurich Insurance"
    assert properties["Role"] == "Head Legal IT and Operations 80-100%"
    assert properties["Stage"] == "Applied"
    assert properties["Source"] == "Company site"
    assert properties["Notes"] == "Job description text"
    assert properties["Last Update Date"]
    assert properties["Update Details"] == "New entry"
    assert "Description" in properties


@pytest.mark.parametrize(
    ("url", "expected_source"),
    [
        ("https://www.linkedin.com/jobs/view/123", "LinkedIn"),
        ("https://ch.indeed.com/viewjob?jk=123", "Indeed"),
        ("https://www.careers.zurich.com/job/123", "Company site"),
        ("https://notlinkedin.com/jobs/123", "Company site"),
        ("https://linkedin.com.example/jobs/123", "Company site"),
        ("https://indeed.com.example/jobs/123", "Company site"),
    ],
)
def test_build_create_properties_sets_source_from_url(url, expected_source):
    properties = main_mod._build_create_properties(
        url,
        {"text": "Job description"},
        "Example Company",
        "Engineer",
    )

    assert properties["Source"] == expected_source


def test_run_create_calls_store_with_canonical_properties(monkeypatch):
    """Creation passes canonical application properties to the store."""
    monkeypatch.setattr(
        main_mod,
        "_scrape_url",
        lambda url: {"url": url, "h1": "Data Engineer"},
    )
    store = FakeStore()

    main_mod._run_create(store, "https://93.184.216.34/jobs/2")

    _, properties = _create_call(store)
    assert properties["Company"] == "93.184.216.34"
    assert properties["Role"] == "Data Engineer"
    assert properties["URL"] == "https://93.184.216.34/jobs/2"
    assert properties["Type"] == "electronic"
    assert properties["Applied date"]
    assert properties["Stage"] == "Applied"
    assert properties["Source"] == "Company site"
    assert "Notes" in properties
    assert properties["Last Update Date"]
    assert properties["Update Details"] == "New entry"
    assert "Description" in properties
    assert "Tracked" not in properties


def test_run_create_reuses_existing_company_address(monkeypatch):
    """Creation reuses a non-empty address from an existing company row."""
    monkeypatch.setattr(
        main_mod,
        "_scrape_url",
        lambda url: {"url": url, "h1": "Data Engineer"},
    )
    store = FakeStore(pd.DataFrame({"Address": ["Reused Street 9"]}))

    main_mod._run_create(store, "https://93.184.216.34/jobs/2", company_override="Acme")

    _, properties = _create_call(store)
    assert properties["Address"] == "Reused Street 9"


def test_run_create_forces_stage_applied(monkeypatch):
    """Newly created applications always begin in the Applied stage."""
    monkeypatch.setattr(main_mod, "_scrape_url", lambda url: {"url": url, "h1": "Dev"})
    store = FakeStore()
    main_mod._run_create(store, "https://93.184.216.34/jobs/9")
    _, properties = _create_call(store)
    assert properties["Stage"] == "Applied"


def test_create_driver_builds_driver_and_wait(monkeypatch):
    class DummyManager:
        def install(self):
            return "/tmp/chromedriver"

    monkeypatch.setattr(main_mod, "ChromeDriverManager", DummyManager)
    monkeypatch.setattr(main_mod.shutil, "which", lambda _: "/tmp/chromedriver")
    monkeypatch.setattr(main_mod, "Service", lambda path: path)
    monkeypatch.setattr(main_mod, "WebDriverWait", FakeWait)

    created = []

    def fake_chrome(service=None, options=None):
        created.append((service, options))
        return FakeDriver()

    monkeypatch.setattr(main_mod.webdriver, "Chrome", fake_chrome)

    driver, wait = main_mod._create_driver()

    assert isinstance(driver, FakeDriver)
    assert isinstance(wait, FakeWait)
    assert created


def test_main_dispatches_modes(monkeypatch):
    """The CLI dispatches each supported mode and rejects unknown modes."""
    calls = []
    monkeypatch.setattr(main_mod, "ApplicationStore", lambda: "store")
    monkeypatch.setattr(
        main_mod, "_run_new_entries", lambda store: calls.append(("new", store))
    )
    monkeypatch.setattr(
        main_mod,
        "_run_update_rejections",
        lambda store: calls.append(("update", store)),
    )
    monkeypatch.setattr(
        main_mod, "_run_list", lambda store: calls.append(("list", store))
    )
    monkeypatch.setattr(main_mod.sys, "argv", ["prog", "new"])

    main_mod.main()
    assert calls[0][0] == "new"

    monkeypatch.setattr(main_mod.sys, "argv", ["prog", "update-rejections"])
    main_mod.main()
    assert calls[1][0] == "update"

    monkeypatch.setattr(main_mod.sys, "argv", ["prog", "list"])
    main_mod.main()
    assert calls[2][0] == "list"

    monkeypatch.setattr(main_mod.sys, "argv", ["prog", "invalid"])
    with pytest.raises(SystemExit):
        main_mod.main()


def test_run_list_empty_and_populated(capsys):
    """List output handles both empty and populated tracker data."""
    empty = FakeStore(pd.DataFrame())
    main_mod._run_list(empty)
    assert "No applications tracked yet" in capsys.readouterr().out

    populated = FakeStore(
        pd.DataFrame(
            [
                {
                    "Company": "Acme",
                    "Role": "Engineer",
                    "Stage": "Applied",
                    "Applied date": "2026-01-01",
                    "Source": "Company site",
                    "URL": "https://example.com/job",
                }
            ]
        )
    )
    main_mod._run_list(populated)
    out = capsys.readouterr().out
    assert "1 tracked application(s)" in out
    assert "Acme" in out
    assert "Engineer" in out
    assert "Company site" in out


def test_run_new_entries_handles_empty_and_error(monkeypatch):
    notion = FakeNotion(pd.DataFrame())
    monkeypatch.setattr(main_mod, "get_month_filter", lambda: {"filter": "month"})
    monkeypatch.setattr(main_mod, "prepare_dataframe", lambda df: None)
    monkeypatch.setattr(
        main_mod, "_create_driver", lambda: (FakeDriver(), FakeWait(FakeDriver(), 1))
    )
    monkeypatch.setattr(main_mod, "handle_login", lambda driver: None)
    monkeypatch.setattr(
        main_mod, "process_records", lambda driver, wait, df, notion: None
    )
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: "")

    main_mod._run_new_entries(notion)

    notion_with_rows = FakeNotion(pd.DataFrame([{"id": 1, "Role": "Engineer"}]))

    def raise_error(driver, wait, df, notion):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_mod, "process_records", raise_error)
    monkeypatch.setattr(
        main_mod, "_create_driver", lambda: (FakeDriver(), FakeWait(FakeDriver(), 1))
    )

    main_mod._run_new_entries(notion_with_rows)


def test_run_update_rejections_handles_empty_and_success(monkeypatch):
    notion = FakeNotion(pd.DataFrame())
    monkeypatch.setattr(main_mod, "get_rejected_filter", lambda: {"filter": "rejected"})
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: "")

    main_mod._run_update_rejections(notion)

    df = pd.DataFrame(
        [
            {
                "id": 1,
                "Company": "Acme",
                "Role": "Dev",
                "Last Update Date": "2024-01-01",
                "Update Details": "",
            }
        ]
    )
    notion = FakeNotion(df)
    main_mod._run_update_rejections(notion)

    df_with_details = pd.DataFrame(
        [
            {
                "id": 1,
                "Company": "Acme",
                "Role": "Dev",
                "Last Update Date": "2024-01-01",
                "Update Details": "reason",
            }
        ]
    )
    notion = FakeNotion(df_with_details)

    driver = FakeDriver()
    monkeypatch.setattr(
        main_mod, "_create_driver", lambda: (driver, FakeWait(driver, 1))
    )
    monkeypatch.setattr(main_mod, "handle_login", lambda driver: None)
    monkeypatch.setattr(
        main_mod, "update_rejected_records", lambda *args, **kwargs: None
    )

    main_mod._run_update_rejections(notion)
    assert driver.quit_called


def test_create_driver_with_chromedriver_manager_none(monkeypatch):
    """Test fallback when ChromeDriverManager is not available."""
    monkeypatch.setattr(main_mod, "ChromeDriverManager", None)
    monkeypatch.setattr(main_mod.shutil, "which", lambda _: "/usr/bin/chromedriver")
    monkeypatch.setattr(main_mod, "Service", lambda path: path)
    monkeypatch.setattr(main_mod, "WebDriverWait", FakeWait)

    created = []

    def fake_chrome(service=None, options=None):
        created.append((service, options))
        return FakeDriver()

    monkeypatch.setattr(main_mod.webdriver, "Chrome", fake_chrome)

    driver, wait = main_mod._create_driver()
    assert isinstance(driver, FakeDriver)
    assert created


def test_create_driver_no_chromedriver_found(monkeypatch):
    """Test error when neither ChromeDriverManager nor chromedriver in PATH."""
    monkeypatch.setattr(main_mod, "ChromeDriverManager", None)
    monkeypatch.setattr(main_mod.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="webdriver_manager not installed"):
        main_mod._create_driver()


def test_prepare_dataframe_with_missing_columns():
    """Test prepare_dataframe when Type is missing and Date is empty."""
    df = pd.DataFrame(
        [
            {
                "Date": None,
                "PLZ_Ort": "12345 Bern",
                "Company": "Test Corp",
            }
        ]
    )

    main_mod.prepare_dataframe(df)

    assert df["PLZ_Ort"].iloc[0] == "1234"
    assert df["Date"].iloc[0] == ""
    assert df["RAV"].iloc[0] == "false"
    assert df["Arbeitspensum"].iloc[0] == "false"
    assert df["Status"].iloc[0] == "false"


def test_get_open_period_december_to_january(monkeypatch):
    """Test _get_open_period crossing year boundary."""

    class FakeDec(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 12, 15, tzinfo=timezone.utc)

    monkeypatch.setattr(main_mod, "datetime", FakeDec)

    start_date, end_date = main_mod._get_open_period()
    assert "2024-12" in start_date
    assert "2025-01" in end_date


def test_get_open_period_january(monkeypatch):
    """Test _get_open_period in January."""

    class FakeJan(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(main_mod, "datetime", FakeJan)

    start_date, end_date = main_mod._get_open_period()
    assert "2023-12" in start_date or "2024-01" in start_date


def test_run_new_entries_with_screenshot_exception(monkeypatch):
    """Test _run_new_entries when exception occurs and screenshot can be saved."""
    df = pd.DataFrame([{"id": "page-1", "Role": "Engineer", "Company": "Acme"}])
    notion = FakeNotion(df)

    driver = FakeDriver()
    wait = FakeWait(driver, 1)

    monkeypatch.setattr(main_mod, "get_month_filter", lambda: {"filter": "month"})
    monkeypatch.setattr(main_mod, "prepare_dataframe", lambda df: None)
    monkeypatch.setattr(main_mod, "_create_driver", lambda: (driver, wait))
    monkeypatch.setattr(main_mod, "handle_login", lambda driver: None)

    def raise_exc(driver, wait, df, notion):
        raise ValueError("Test exception")

    monkeypatch.setattr(main_mod, "process_records", raise_exc)
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: "")

    main_mod._run_new_entries(notion)
    assert len(driver.screenshots) > 0
    assert driver.quit_called


def test_run_update_rejections_with_exception_handling(monkeypatch):
    """Test _run_update_rejections when screenshot fails."""
    df = pd.DataFrame(
        [
            {
                "id": "page-1",
                "Company": "Acme",
                "Role": "Dev",
                "Last Update Date": "2024-01-01",
                "Update Details": "reason",
            }
        ]
    )
    notion = FakeNotion(df)

    class ScreenshotFailingDriver(FakeDriver):
        def save_screenshot(self, path):
            raise OSError("disk full")

    driver = ScreenshotFailingDriver()
    wait = FakeWait(driver, 1)

    monkeypatch.setattr(main_mod, "get_rejected_filter", lambda: {"filter": "rejected"})
    monkeypatch.setattr(main_mod, "_create_driver", lambda: (driver, wait))
    monkeypatch.setattr(main_mod, "handle_login", lambda driver: None)

    def raise_exc(driver, wait, df, notion):
        raise RuntimeError("Test error")

    monkeypatch.setattr(main_mod, "update_rejected_records", raise_exc)
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: "")

    main_mod._run_update_rejections(notion)
    assert driver.quit_called


def test_extract_formatted_field_with_none():
    """Test extract_formatted_field with None value."""
    result = main_mod.extract_formatted_field(None)
    assert result is None


def test_extract_formatted_field_with_dict():
    """Test extract_formatted_field with dict that has string key."""
    result = main_mod.extract_formatted_field({"string": "value"})
    assert result == "value"


def test_first_monday_various_days():
    """Test _first_monday_on_or_after for different day offsets."""
    tuesday = datetime(2024, 1, 2, tzinfo=timezone.utc)  # Tuesday
    result = main_mod._first_monday_on_or_after(tuesday)
    assert result.weekday() == 0  # Monday is 0
    assert result > tuesday

    sunday = datetime(2024, 1, 7, tzinfo=timezone.utc)  # Sunday
    result = main_mod._first_monday_on_or_after(sunday)
    assert result.weekday() == 0
    assert result == datetime(2024, 1, 8, tzinfo=timezone.utc)


def test_extract_formatted_field_with_non_dict_parsed_value():
    """When ast.literal_eval succeeds but doesn't produce a dict, the
    original value should be returned unchanged (not None)."""
    assert main_mod.extract_formatted_field("123") == "123"
    assert main_mod.extract_formatted_field("[1, 2, 3]") == "[1, 2, 3]"
    assert main_mod.extract_formatted_field(123) == 123


def test_extract_formatted_field_dict_without_string_key():
    """Test extract_formatted_field with dict missing the 'string' key."""
    result = main_mod.extract_formatted_field("{'other': 'value'}")
    assert result is None


def test_get_month_filter_uses_applied_date_for_both_conditions():
    """Regression test: both date conditions in get_month_filter must use
    the APPLIED_DATE constant (previously the 'before' clause used a
    hardcoded 'Applied date' string, which happened to match but was
    inconsistent with the constant)."""
    month_filter = main_mod.get_month_filter()
    assert month_filter["and"][0]["property"] == main_mod.APPLIED_DATE
    assert month_filter["and"][1]["property"] == main_mod.APPLIED_DATE
    assert "before" in month_filter["and"][1]["date"]


def test_run_update_rejections_handles_screenshot_failure(monkeypatch):
    """Test _run_update_rejections gracefully handles a failing screenshot
    save when an exception occurs during update_rejected_records."""
    df = pd.DataFrame(
        [
            {
                "id": "page-1",
                "Company": "Acme",
                "Role": "Dev",
                "Last Update Date": "2024-01-01",
                "Update Details": "reason",
            }
        ]
    )
    notion = FakeNotion(df)

    class ScreenshotFailingDriver(FakeDriver):
        def save_screenshot(self, path):
            raise OSError("disk full")

    driver = ScreenshotFailingDriver()
    wait = FakeWait(driver, 1)

    printed = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: printed.append(args))
    monkeypatch.setattr(main_mod, "get_rejected_filter", lambda: {"filter": "rejected"})
    monkeypatch.setattr(main_mod, "_create_driver", lambda: (driver, wait))
    monkeypatch.setattr(main_mod, "handle_login", lambda driver: None)

    def raise_exc(driver, wait, df, notion):
        raise RuntimeError("Test error")

    monkeypatch.setattr(main_mod, "update_rejected_records", raise_exc)
    monkeypatch.setattr(builtins, "input", lambda *args, **kwargs: "")

    main_mod._run_update_rejections(notion)

    assert driver.quit_called
    assert any(
        "Could not save screenshot" in item
        for args in printed
        for item in args
        if isinstance(item, str)
    )


@pytest.mark.parametrize("missing_value", [None, pd.NA])
def test_prepare_dataframe_blank_plz_stays_blank(missing_value):
    """A missing PLZ_Ort must stay blank, not become 'nan' (bogus typeahead)."""
    df = pd.DataFrame(
        [
            {
                "Date": "2026-09-16",
                "Type": "electronic",
                "PLZ_Ort": missing_value,
            }
        ]
    )

    main_mod.prepare_dataframe(df)

    assert df["PLZ_Ort"].iloc[0] == ""


def test_to_swiss_date_formats_iso_and_handles_edge_cases():
    """ISO dates become TT.MM.JJJJ; blanks/unparseable pass through safely."""
    assert main_mod._to_swiss_date("2026-09-16") == "16.09.2026"
    assert main_mod._to_swiss_date("2024-01-01") == "01.01.2024"
    assert main_mod._to_swiss_date("") == ""
    assert main_mod._to_swiss_date(None) == ""
    assert main_mod._to_swiss_date(pd.NaT) == ""
    assert main_mod._to_swiss_date(pd.NA) == ""
    assert main_mod._to_swiss_date("nan") == ""
    # already Swiss / unparseable → returned unchanged (no crash)
    assert main_mod._to_swiss_date("16.09.2026") == "16.09.2026"


def test_prepare_dataframe_date_is_swiss_format():
    """prepare_dataframe must emit the Date column as TT.MM.JJJJ for the form."""
    df = pd.DataFrame([{"Date": "2026-09-16", "Type": "electronic", "PLZ_Ort": ""}])
    main_mod.prepare_dataframe(df)
    assert df["Date"].iloc[0] == "16.09.2026"

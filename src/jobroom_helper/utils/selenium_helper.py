import ast
import time
import traceback

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as ec

from jobroom_helper.config import (
    ENTRY_SELECTOR,
    EXECUTE_SCRIPT_CLICK,
    FIELD_SELECTORS,
    SCROLL_INTO_VIEW_SCRIPT,
    get_website_url,
)
from jobroom_helper.utils.session_helper import load_session, save_session


def get_notion_scalar_value(value):
    """Extract scalar value from simple property value wrappers.

    For type 'string', extracts the string value.
    For other types, extracts the value at the key matching the type.
    """
    if isinstance(value, dict):
        value_type = value.get("type")
        if isinstance(value_type, str) and value_type in value:
            return value.get(value_type)
        return value

    if isinstance(value, str) and value.startswith("{"):
        try:
            return get_notion_scalar_value(ast.literal_eval(value))
        except (SyntaxError, ValueError):
            return value

    return value


def resolve_type_selector(value):
    """Resolve selector for Type field based on value.

    Args:
        value: The type value to resolve

    Returns:
        str: The CSS selector for the type value, or None if unknown
    """
    type_value = str(get_notion_scalar_value(value)).strip().lower()

    if type_value == "electronic":
        return "label[for*='alv-checkbox-portal'][for*='electronic']"
    elif type_value == "phone":
        return "label[for*='alv-checkbox-portal'][for*='phone']"
    elif type_value == "vorstellungsgespräch":
        return "//label[normalize-space()='Vorstellungsgespräch']"
    else:
        print(f"   ⚠️ Unknown Type: {type_value}")
        return None


def fill_typeahead(driver, wait, element, field_name, value):
    """Fill typeahead field.

    Args:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        element: The element to fill
        field_name: Name of the field for logging
        value: Value to fill
    """
    if element.is_displayed():
        driver.execute_script(EXECUTE_SCRIPT_CLICK, element)

    element.send_keys(str(value))
    time.sleep(2)
    try:
        suggestion = wait.until(
            ec.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[id*='ngb-typeahead-']")
            )
        )

        suggestion.click()
        final_value = element.get_attribute("value")
        print(f"   ✓ Typeahead: {field_name} → Selected value: {final_value}")
    except TimeoutException:
        element.send_keys(Keys.ENTER)
        final_value = element.get_attribute("value")
        print(f"   ✓ Typeahead (Enter): {field_name} - Selected value: {final_value}")


def fill_checkbox(driver, element, field_name):
    """Fill checkbox field.

    Args:
        driver: Selenium WebDriver instance
        element: The checkbox element
        field_name: Name of the field for logging
    """
    if element.is_displayed():
        driver.execute_script(EXECUTE_SCRIPT_CLICK, element)
        print(f"   ✓ Checked {field_name}")
    else:
        print(f"   ⚠️ Checkbox not visible: {field_name}")


def fill_radio(driver, element, field_name, value):
    """Fill radio button field.

    Args:
        driver: Selenium WebDriver instance
        element: The radio button element
        field_name: Name of the field for logging
        value: Value indicating if it should be selected
    """
    if value:
        driver.execute_script(EXECUTE_SCRIPT_CLICK, element)
        print(f"   ✓ Selected radio {field_name}")


def fill_text(element, field_name, value):
    """Fill text input field.

    Args:
        element: The input element
        field_name: Name of the field for logging
        value: Value to fill
    """
    element.clear()
    element.send_keys(str(value))
    print(f"   ✓ Filled {field_name} → {value}")


def _resolve_element(wait, field_name, selector, value, row=None):
    if field_name == "Interview" and row is not None:
        interview_value = str(get_notion_scalar_value(value)).strip().lower()
        if interview_value != "vorstellungsgespräch":
            print(f"   → Skipping Interview: {interview_value}")
            return None

        selector = "//label[normalize-space()='Vorstellungsgespräch']"
        print(f"   → Setting Interview to: {interview_value}")
        return wait.until(ec.presence_of_element_located((By.XPATH, selector)))

    if field_name == "Type" and row is not None:
        selector = resolve_type_selector(value)
        if selector is None:
            return None
        print(f"   → Setting Type to: {str(value).strip().lower()}")
        locator = (
            (By.XPATH, selector)
            if selector.startswith("//")
            else (By.CSS_SELECTOR, selector)
        )
        return wait.until(ec.presence_of_element_located(locator))

    return wait.until(ec.presence_of_element_located((By.CSS_SELECTOR, selector)))


def _is_typeahead(selector):
    return "single-typeahead" in selector or "typeahead" in selector.lower()


def _should_use_checkbox(field_name, selector):
    return (
        "checkbox" in selector.lower()
        or field_name == "Type"
        or field_name == "Interview"
    )


def _fill_with_strategy(driver, wait, field_name, selector, element, value):
    if _is_typeahead(selector):
        fill_typeahead(driver, wait, element, field_name, value)
    elif _should_use_checkbox(field_name, selector):
        fill_checkbox(driver, element, field_name)
    elif "radio" in selector.lower():
        fill_radio(driver, element, field_name, value)
    else:
        fill_text(element, field_name, value)


def fill_field(driver, wait, field_name, selector, value, row=None):
    """Smart field filler with special handling for Type checkboxes.

    Args:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        field_name: Name of the field
        selector: CSS selector for the field
        value: Value to fill
        row: Optional row data for context
    """
    try:
        element = _resolve_element(wait, field_name, selector, value, row)
        if element is None:
            return

        driver.execute_script(SCROLL_INTO_VIEW_SCRIPT, element)
        time.sleep(0.8)
        _fill_with_strategy(driver, wait, field_name, selector, element, value)
    except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
        print(f"   ❌ Could not fill {field_name}: {value} ({exc})")
        driver.save_screenshot("results/jobroom_fill_field_error.png")
        traceback.print_exc()


def process_records(driver, wait, df, store):
    """Process each record from the dataframe.

    Args:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        df: Dataframe with records to process
        store: ApplicationStore instance
    """

    # Navigate to "Efforts to find work"
    driver.get(get_website_url() + "work-efforts")
    time.sleep(3)

    total_records = len(df) if hasattr(df, "__len__") else sum(1 for _ in df.iterrows())
    for index, row in df.iterrows():
        print(f"\nProcessing {index + 1}/{total_records}: {row.get('Role', 'N/A')}")

        driver.find_element(
            By.CSS_SELECTOR,
            ".add-work-effort-button",
        ).click()
        time.sleep(3)

        for field, selector in FIELD_SELECTORS.items():
            value = row.get(field)
            fill_field(driver, wait, field, selector, value, row=row)

        input("\nPress Enter to submit the form after reviewing the filled data...")

        success = store.update_row(
            page_id=row["id"],
            properties={
                "Tracked": {"checkbox": True},
            },
        )
        if success:
            print("   → Record processed")
        else:
            print("   → Failed to update tracker record. Please check the database.")


def _get_month_year_pairs(df):
    if df is None or df.empty:
        return []

    month_pairs = []
    for value in df.get("Applied date", []):
        if value is None:
            continue

        date_text = str(value).strip()
        if not date_text:
            continue

        date_parts = date_text.split("-")
        if len(date_parts) < 2:
            continue

        try:
            year = date_parts[0]
            month_num = int(date_parts[1])
        except ValueError:
            continue

        month_pairs.append((year, month_num))

    return list(dict.fromkeys(month_pairs))


def _expand_month_section(driver, df):
    """Expand the month section on the work-efforts page.

    Job-Room groups entries by month in collapsible sections. This finds
    and expands the section matching the reference month of the records.

    Args:
        driver: Selenium WebDriver instance
        df: Dataframe containing records (uses Applied date to determine month)
    """
    month_pairs = _get_month_year_pairs(df)
    if not month_pairs:
        return

    try:
        month_names = {
            1: "Januar",
            2: "Februar",
            3: "März",
            4: "April",
            5: "Mai",
            6: "Juni",
            7: "Juli",
            8: "August",
            9: "September",
            10: "Oktober",
            11: "November",
            12: "Dezember",
        }

        for year, month_num in month_pairs:
            month_name = month_names.get(month_num, "")
            if not month_name:
                continue
            _expand_month_section_for(driver, month_name, year)

    except (ValueError, IndexError, NoSuchElementException, WebDriverException) as e:
        print(f"   ⚠️ Error expanding month section: {e}")


def _expand_month_section_for(driver, month_name, year):
    section_xpath = (
        f"//button[contains(@class, 'collapsed')]"
        f"[contains(., '{month_name}') and contains(., '{year}')]"
        f" | "
        f"//a[contains(@class, 'collapsed')]"
        f"[contains(., '{month_name}') and contains(., '{year}')]"
        f" | "
        f"//div[contains(@class, 'collapsed')]"
        f"[contains(., '{month_name}') and contains(., '{year}')]"
    )

    sections = driver.find_elements(By.XPATH, section_xpath)
    if sections:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", sections[0]
        )
        time.sleep(0.5)
        driver.execute_script(EXECUTE_SCRIPT_CLICK, sections[0])
        time.sleep(2)
        print(f"   ✓ Expanded section: {month_name} {year}")
        return

    expanded_xpath = (
        f"//button[contains(., '{month_name}') and contains(., '{year}')]"
        f" | "
        f"//a[contains(., '{month_name}') and contains(., '{year}')]"
    )
    expanded = driver.find_elements(By.XPATH, expanded_xpath)
    if expanded:
        print(f"   ✓ Section already expanded: {month_name} {year}")
    else:
        print(f"   ⚠️ Could not find month section for {month_name} {year}")


def _format_absagegrund(update_date, update_details):
    try:
        date_parts = update_date.split("-")
        return f"{date_parts[2]}.{date_parts[1]}: {update_details}"
    except (IndexError, AttributeError):
        return f"{update_date}: {update_details}"


def _print_rejection_header(index, total, company, role, absagegrund):
    print(f"\n{'=' * 60}")
    print(f"Updating rejection {index + 1}/{total}: {company} - {role}")
    print(f"   Absagegrund: {absagegrund[:80]}...")
    print(f"{'=' * 60}")


def _process_rejected_entry(driver, wait, store, row, index, total):
    company = str(row.get("Company", ""))
    role = str(row.get("Role", ""))
    update_date = str(row.get("Last Update Date", ""))
    update_details = str(row.get("Update Details", ""))

    if not update_date or not update_details:
        print(
            f"\n⚠️  Skipping {company} - {role}: "
            "missing Last Update Date or Update Details"
        )
        return

    absagegrund = _format_absagegrund(update_date, update_details)
    _print_rejection_header(index, total, company, role, absagegrund)

    try:
        entry = _find_existing_entry(driver, company, role)
        if entry is None:
            _report_missing_entry(driver, index, company)
            return

        _update_rejected_entry(driver, wait, store, row, company, absagegrund, entry)
    except (NoSuchElementException, TimeoutException, WebDriverException) as exc:
        print(f"   ❌ Error updating {company}: {exc}")
        driver.save_screenshot(f"results/jobroom_update_error_{index}.png")
        traceback.print_exc()


def _report_missing_entry(driver, index, company):
    print(f"   ❌ Could not find entry for {company} on the page")
    driver.save_screenshot(f"results/jobroom_update_notfound_{index}.png")


def _update_rejected_entry(driver, wait, store, row, company, absagegrund, entry):
    driver.execute_script(SCROLL_INTO_VIEW_SCRIPT, entry)
    time.sleep(1)

    if not _set_status_rejected(driver, entry):
        return
    if not _fill_absagegrund(driver, wait, entry, absagegrund):
        return

    input(f"\n   Review entry for {company}. Press Enter to confirm and continue...")

    print(f"   ✅ Updated {company} to Absage")
    _update_notion_tracked(store, row["id"])


def _update_notion_tracked(store, page_id):
    success = store.update_row(
        page_id=page_id,
        properties={"Tracked": {"checkbox": True}},
    )
    if success:
        print("   → Record processed")
    else:
        print("   → Failed to update tracker record. Please check the database.")


def update_rejected_records(driver, wait, df, store):
    """Update existing entries that have been rejected.

    Finds entries on the current work-efforts page that are still marked as
    'Noch offen' and updates them to 'Absage' with the rejection reason.

    Only processes records where:
    - Stage == 'Rejected'
    - Tracked ==  False (not yet processed)
    - Last Update Date and Update Details are present

    The Absagegrund field is filled with: "<DD.MM>: <reason>"

    Args:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        df: Dataframe with rejected records to update
        store: ApplicationStore instance
    """
    driver.get(get_website_url() + "work-efforts")
    time.sleep(3)

    _expand_month_section(driver, df)

    for index, row in df.iterrows():
        _process_rejected_entry(driver, wait, store, row, index, len(df))


def _entry_text(entry):
    return entry.text.lower()


def _matches_role(entry, role):
    if not role:
        return True

    role_keyword = role.split()[0].lower()
    return role_keyword in _entry_text(entry)


def _find_entry_by_company(entries, company, role=None):
    lower_company = company.lower()
    for entry in entries:
        if lower_company in _entry_text(entry) and _matches_role(entry, role):
            return entry
    return None


def _find_entry_by_company_prefix(entries, company, role=None):
    first_word = company.split()[0].lower() if company else ""
    if not first_word:
        return None

    for entry in entries:
        if first_word in _entry_text(entry) and _matches_role(entry, role):
            return entry
    return None


def _find_exact_entry(entries, company, role):
    lower_company = company.lower()
    for entry in entries:
        if lower_company not in _entry_text(entry):
            continue
        if _matches_role(entry, role):
            return entry
    return None


def _get_entries(driver):
    try:
        return driver.find_elements(By.CSS_SELECTOR, ENTRY_SELECTOR)
    except (NoSuchElementException, WebDriverException) as exc:
        print(f"   ❌ Error finding entry rows: {exc}")
        return []


def _find_existing_entry(driver, company, role):
    """Find an existing entry on the work-efforts page.

    Job-Room renders each entry as an <alv-work-effort> component
    containing a div.alv-cells with company name and role text.

    Args:
        driver: Selenium WebDriver instance
        company: Company name to search for
        role: Role/position title to search for

    Returns:
        WebElement of the matching alv-work-effort component, or None
    """

    entries = _get_entries(driver)
    if not entries:
        print("   ⚠️ No entry rows found on page")
        return None

    for finder in (
        _find_exact_entry,
        _find_entry_by_company,
        _find_entry_by_company_prefix,
    ):
        entry = finder(entries, company, role)
        if entry:
            return entry

    print(f"   ⚠️ No matching entry found among {len(entries)} entries")
    return None


def _find_absage_label(entry):
    try:
        return entry.find_element(By.CSS_SELECTOR, "label[for$='-REJECTED']")
    except NoSuchElementException:
        return entry.find_element(By.XPATH, ".//label[contains(text(), 'Absage')]")


def _set_status_rejected(driver, entry):
    """Click the 'Absage' radio button within a specific entry.

    The radio button has an ID pattern: alv-radio-button-{N}-REJECTED
    and the label has for="alv-radio-button-{N}-REJECTED".

    Args:
        driver: Selenium WebDriver instance
        entry: The parent alv-work-effort WebElement
    """
    try:
        absage_label = _find_absage_label(entry)
        driver.execute_script(SCROLL_INTO_VIEW_SCRIPT, absage_label)
        time.sleep(0.5)
        driver.execute_script(EXECUTE_SCRIPT_CLICK, absage_label)
        print("   ✓ Set status to Absage")
        return True
    except (NoSuchElementException, WebDriverException) as exc:
        print(f"   ❌ Could not find Absage radio button: {exc}")
        traceback.print_exc()
        return False


def _is_absagegrund_candidate(element):
    el_id = element.get_attribute("id") or ""
    if any(x in el_id.lower() for x in ["date", "company", "street", "phone", "email"]):
        return False
    return element.is_displayed()


def _find_absagegrund_in_entry(entry):
    selectors = ["textarea", "input[type='text']"]

    for selector in selectors:
        elements = entry.find_elements(By.CSS_SELECTOR, selector)
        for el in elements:
            if _is_absagegrund_candidate(el):
                return el
    return None


def _find_absagegrund_fallback(wait):
    return wait.until(
        ec.presence_of_element_located(
            (
                By.XPATH,
                "//textarea[contains(@id, 'reason')] | "
                "//input[contains(@id, 'reason')] | "
                "//textarea[contains(@id, 'rejection')] | "
                "//input[contains(@id, 'rejection')]",
            )
        )
    )


def _fill_absagegrund(driver, wait, entry, absagegrund):
    """Fill the Absagegrund (rejection reason) text field.

    Args:
        driver: Selenium WebDriver instance
        wait: WebDriverWait instance
        entry: The parent alv-work-effort WebElement
        absagegrund: The formatted rejection reason string
    """
    time.sleep(1)  # Wait for the field to appear after radio click

    try:
        element = _find_absagegrund_in_entry(entry)
        if element is None:
            element = _find_absagegrund_fallback(wait)

        driver.execute_script(SCROLL_INTO_VIEW_SCRIPT, element)
        time.sleep(0.5)
        element.clear()
        element.send_keys(absagegrund)
        print(f"   ✓ Filled Absagegrund → {absagegrund[:60]}...")
        return True
    except (TimeoutException, NoSuchElementException, WebDriverException) as exc:
        print(f"   ❌ Could not fill Absagegrund field: {exc}")
        traceback.print_exc()
        return False


def handle_login(driver):
    """Handle session restoration or manual login.

    Args:
        driver: Selenium WebDriver instance

    Returns:
        Boolean indicating if logged in successfully
    """
    session_restored = load_session(driver)

    if session_restored:
        driver.get(get_website_url())
        time.sleep(5)
        print("✅ Today's session restored!")

        # Optional verification
        if any(x in driver.current_url.lower() for x in ["login", "auth", "saml"]):
            print("   ⚠️ Session didn't stay logged in. Forcing fresh login.")
            session_restored = False

    if not session_restored:
        driver.get(get_website_url())
        print("\n🔄 Starting fresh manual login (daily policy)...")

        try:
            driver.find_element(
                By.CSS_SELECTOR,
                ".btn.btn-primary.d-none.d-lg-block.ng-star-inserted",
            ).click()
            time.sleep(3)
        except NoSuchElementException as exc:
            print(f"   Could not find Login button - already on login page?: {exc}")

        try:
            driver.find_element(
                By.CSS_SELECTOR, "button[class*='idp-card small xtb-default']"
            ).click()
            time.sleep(3)
        except NoSuchElementException as exc:
            print(f"   Could not find AGOV button: {exc}")

        input("✅ Press Enter AFTER successful AGOV login and QR code scan...")
        save_session(driver)
        print("✅ Full session (cookies + storage) saved for future use!")

    return True

"""Non-interactive DOM capture of the Job-Room landing/login page.

Loads WEBSITE_URL headlessly, waits for Angular to render, then prints every
button / anchor / role=button (tag, visible text, classes, data attrs, aria).
Also walks into the login step if an obvious Login/Anmelden control is present.

Run:  mise exec -- python3 scripts/capture_login_dom_auto.py
"""

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from jobroom_helper.config import get_website_url


def dump(driver, stage):
    print(f"\n===== DOM DUMP [{stage}] url={driver.current_url}")
    els = driver.find_elements(
        By.CSS_SELECTOR, "button, a, [role='button'], input[type='submit']"
    )
    n = 0
    for el in els:
        try:
            disp = el.is_displayed()
            txt = (el.text or "").strip().replace("\n", " ")
            cls = el.get_attribute("class") or ""
            tag = el.tag_name
            dtc = (
                el.get_attribute("data-test")
                or el.get_attribute("data-cy")
                or el.get_attribute("data-testid")
                or ""
            )
            aria = el.get_attribute("aria-label") or ""
            val = el.get_attribute("value") or ""
            if not (txt or cls or dtc or aria or val):
                continue
            n += 1
            print(f"[{n:02d}] <{tag}> disp={disp} text={txt!r} value={val!r}")
            if cls:
                print(f"     class={cls!r}")
            if dtc:
                print(f"     data-test*={dtc!r}")
            if aria:
                print(f"     aria-label={aria!r}")
        except Exception as e:  # noqa: BLE001
            print("   (stale)", type(e).__name__)
    print(f"===== end [{stage}] — {n} candidates\n")


def main():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )
    try:
        driver.get(get_website_url())
        time.sleep(7)
        dump(driver, "landing")

        # Try to find & click a Login/Anmelden control, then dump the IdP page.
        candidates = driver.find_elements(
            By.XPATH,
            "//*[self::button or self::a][contains(translate(normalize-space(.),"
            "'LOGINANMELDECONNEXIONACCEDI','loginanmeldeconnexioneaccedi'),'login')"
            " or contains(translate(normalize-space(.),'ANMELDEN','anmelden'),"
            "'anmelden')]",
        )
        print(f"[login-candidate count] {len(candidates)}")
        for i, c in enumerate(candidates[:5]):
            try:
                print(
                    f"   login-cand[{i}] text={c.text.strip()!r} "
                    f"class={c.get_attribute('class')!r}"
                )
            except Exception:  # noqa: BLE001
                pass
        if candidates:
            try:
                candidates[0].click()
                time.sleep(6)
                dump(driver, "after-login-click")
            except Exception as e:  # noqa: BLE001
                print("   login click failed:", type(e).__name__, e)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

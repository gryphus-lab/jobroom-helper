"""One-off diagnostic: dump the live Job-Room login-page DOM so we can re-map
the Login and AGOV button selectors after Job-Room's Angular markup changed.

Run:  mise exec -- python3 scripts/capture_login_dom.py
Opens a VISIBLE Chrome, navigates to WEBSITE_URL, waits, then prints every
candidate button/anchor (tag, visible text, classes, key attrs). Leaves the
browser open until you press Enter so you can inspect / complete login manually.
"""

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from jobroom_helper.config import get_website_url


def dump(driver, stage):
    print(f"\n================= DOM DUMP [{stage}] | url={driver.current_url}")
    els = driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']")
    seen = 0
    for el in els:
        try:
            if not el.is_displayed():
                continue
            txt = (el.text or "").strip().replace("\n", " ")
            cls = el.get_attribute("class") or ""
            tag = el.tag_name
            dtc = el.get_attribute("data-test") or el.get_attribute("data-cy") or ""
            aria = el.get_attribute("aria-label") or ""
            href = el.get_attribute("href") or ""
            # only show things with some identity
            if not (txt or cls or dtc or aria):
                continue
            seen += 1
            print(f"[{seen:02d}] <{tag}> text={txt!r}")
            if cls:
                print(f"       class={cls!r}")
            if dtc:
                print(f"       data-test/cy={dtc!r}")
            if aria:
                print(f"       aria-label={aria!r}")
            if href:
                print(f"       href={href!r}")
        except Exception as e:  # noqa: BLE001
            print("   (stale/err)", type(e).__name__)
    print(f"================= end dump ({seen} visible candidates)\n")


def main():
    opts = Options()
    opts.add_argument("--start-maximized")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )
    try:
        driver.get(get_website_url())
        print("Loaded landing page. Waiting 6s for Angular to render...")
        time.sleep(6)
        dump(driver, "landing")

        input(
            "\n>>> If a Login/Anmelden button is visible, CLICK IT YOURSELF now, "
            "wait for the IdP page, then press Enter here to dump that page..."
        )
        time.sleep(2)
        dump(driver, "after-login-click (IdP / AGOV chooser)")

        input("\n>>> Press Enter to close the browser (or finish login first).")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

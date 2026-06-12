import os
from playwright.sync_api import sync_playwright

TARGET_URL = os.environ.get("GIS_AGENT_E2E_URL", "http://127.0.0.1:8000/")
VALID_USER = os.environ.get("GIS_AGENT_E2E_USER", "admin")
VALID_PASS = os.environ.get("GIS_AGENT_E2E_PASSWORD", "admin")

def check_error():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print(f"🚀 Investigating login failure on {TARGET_URL}...")

        try:
            page.goto(TARGET_URL)
            page.wait_for_selector("#username", timeout=10000)

            # Perform the login attempt
            page.fill("#username", VALID_USER)
            page.fill("#password", VALID_PASS)
            page.click("button[type='submit']")

            # We wait a bit for any error message to appear
            try:
                page.wait_for_selector(".login-error", timeout=5000)
                error_msg = page.inner_text(".login-error")
                print(f"❌ Found Error Message in UI: {error_msg}")
            except:
                print("⚠️ No '.login-error' element appeared on the page.")
                # Check if any error text is present anywhere in the body
                body_text = page.locator("body").inner_text()
                if "登录失败" in body_text:
                    print("ℹ️ Found '登录失败' (Login Failed) text in the page body.")
                else:
                    print("ℹ️ No specific error text found in the page body.")

            # Also check for any console errors or network failures
            page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
            page.on("pageerror", lambda exc: print(f"BROWSER PAGE ERROR: {exc}"))

        except Exception as e:
            print(f"❌ Investigation script error: {e}")
        finally:
            browser.close()
            print("🏁 Investigation finished.")

if __name__ == "__main__":
    check_error()

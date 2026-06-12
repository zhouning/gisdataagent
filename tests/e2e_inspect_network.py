import os
from playwright.sync_api import sync_playwright

TARGET_URL = os.environ.get("GIS_AGENT_E2E_URL", "http://127.0.0.1:8000/")
VALID_USER = os.environ.get("GIS_AGENT_E2E_USER", "admin")
VALID_PASS = os.environ.get("GIS_AGENT_E2E_PASSWORD", "admin")

def investigate_network():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Intercept network responses
        def handle_response(response):
            # We check for any URL that contains 'auth' or sounds like an API call
            if "auth" in response.url or "/api/" in response.url:
                try:
                    print(f"🌐 API Response caught: {response.url} [{response.status}]")
                    if response.status >= 400:
                        # We only print if there's content to avoid noise
                        text = response.text()
                        if text:
                            print(f"   Payload: {text}")
                except Exception as e:
                    pass

        page.on("response", handle_response)

        print(f"🚀 Investigating Network traffic on {TARGET_URL}...")

        try:
            page.goto(TARGET_URL)
            page.wait_for_selector("#username", timeout=10000)

            # Perform login
            page.fill("#username", VALID_USER)
            page.fill("#password", VALID_PASS)
            print("Attempting to click Login button...")
            page.click("button[type='submit']")

            # Wait for a few seconds to allow the network call and error message to process
            page.wait_for_timeout(5000)

        except Exception as e:
            print(f"❌ Script error: {e}")
        finally:
            browser.close()
            print("🏁 Investigation finished.")

if __name__ == "__main__":
    investigate_network()

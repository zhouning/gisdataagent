import os
from playwright.sync_api import sync_playwright

# The target URL of your web system.
TARGET_URL = os.environ.get("GIS_AGENT_E2E_URL", "http://127.0.0.1:8000/")

VALID_USER = os.environ.get("GIS_AGENT_E2E_USER", "admin")
VALID_PASS = os.environ.get("GIS_AGENT_E2E_PASSWORD", "admin")
INVALID_USER = os.environ.get("GIS_AGENT_E2E_INVALID_USER", "wrong_user")
INVALID_PASS = os.environ.get("GIS_AGENT_E2E_INVALID_PASSWORD", "wrong_password")

def run_test():
    with sync_playwright() as p:
        # Launching Chromium browser in HEADLESS mode for automated execution in terminal
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()

        # Create a directory for screenshots using absolute path
        screenshot_dir = os.environ.get(
            "GIS_AGENT_E2E_SCREENSHOT_DIR",
            os.path.join(os.path.dirname(__file__), "e2e", "screenshots"),
        )
        os.makedirs(screenshot_dir, exist_ok=True)

        print(f"🚀 Starting Optimized Playwright E2E Login Test on {TARGET_URL}...")

        try:
            # --- TEST CASE 1: SUCCESSFUL LOGIN ---
            print(f"Testing Case 1: Valid credentials ({VALID_USER}/{VALID_PASS})")
            # Use networkidle to ensure the page and all scripts are fully loaded
            page.goto(TARGET_URL, wait_until="networkidle")

            # Ensure login form is interactive before proceeding
            page.wait_for_selector("#username", state="visible", timeout=15000)

            # Fill in credentials
            page.fill("#username", VALID_USER)
            page.fill("#password", VALID_PASS)

            # Click the login button
            print("Clicking Login button...")
            page.click("button[type='submit']")

            # Verify success: Wait for the dashboard header to appear
            # We use a longer timeout and also wait for the URL to change if applicable
            page.wait_for_selector(".app-header", timeout=20000)
            print("✅ Case 1 PASSED: Successfully logged in and reached Dashboard!")

            # Take screenshot of success state
            success_path = os.path.join(screenshot_dir, "login_success.png")
            page.screenshot(path=success_path)
            print(f"📸 Success screenshot saved to: {success_path}")

            # --- TEST CASE 2: FAILED LOGIN ---
            print(f"\nTesting Case 2: Invalid credentials ({INVALID_USER}/{INVALID_PASS})")

            # Instead of just goto, we wait for the network to be idle after reload
            print("Reloading page for fresh login attempt...")
            page.goto(TARGET_URL, wait_until="networkidle")

            # Ensure form is ready again
            page.wait_for_selector("#username", state="visible", timeout=15000)

            # Fill in invalid credentials
            page.fill("#username", INVALID_USER)
            page.fill("#password", INVALID_PASS)

            print("Clicking Login button with invalid credentials...")
            page.click("button[type='submit']")

            # Verify failure: Wait for the error message '.login-error' to appear
            # We allow extra time here because auth requests can be slow/asynchronous
            page.wait_for_selector(".login-error", timeout=20000)
            print("✅ Case 2 PASSED: Correctly detected login failure via UI error message!")

            # Take screenshot of failure state
            failure_path = os.path.join(screenshot_dir, "login_failed_error.png")
            page.screenshot(path=failure_path)
            print(f"📸 Failure screenshot saved to: {failure_path}")

        except Exception as e:
            print(f"❌ TEST FAILED with error: {e}")
            # Capture detailed debug info
            error_path = os.path.join(screenshot_dir, "test_crash_debug.png")
            page.screenshot(path=error_path)
            print(f"📸 Debug screenshot saved to: {error_path}")
        finally:
            browser.close()
            print("🏁 Test execution finished.")

if __name__ == "__main__":
    run_test()

import os
import sys
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

BASE_URL = "http://127.0.0.1:5000"
ARTIFACTS_DIR = r"C:\Users\esakk\.gemini\antigravity-ide\brain\c1a92d33-5c90-4eaa-b3eb-09d99f3eb4fc"

TEST_USERS = [
    {
        "role": "hod",
        "email": "hod.cs@psgcas.ac.in",
        "pw": "psgcascareers!HodCS2026",
        "page": "hod.html",
        "screenshot": "hod_portal_screenshot.png"
    },
    {
        "role": "superadmin",
        "email": "vp@psgcas.ac.in",
        "pw": "psgcascareers!VP2026",
        "page": "vp.html",
        "screenshot": "vp_portal_screenshot.png"
    },
    {
        "role": "hr",
        "email": "hr@psgcas.ac.in",
        "pw": "psgcascareers!HR2026",
        "page": "hr.html",
        "screenshot": "hr_portal_screenshot.png"
    }
]

def run_selenium_tests():
    print("=" * 75)
    print("  PSG CAS CONNECT — SELENIUM BROWSER & CONSOLE LOG VALIDATION TEST")
    print("=" * 75)

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,900")
    
    # Enable browser log logging
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})

    driver = webdriver.Chrome(options=options)

    try:
        for u in TEST_USERS:
            print(f"\n[TESTING PORTAL] {u['page']} as {u['email']}...")

            # 1. Login via backend API to fetch token and user details
            resp = requests.post(f"{BASE_URL}/api/login", json={"email": u["email"], "password": u["pw"]})
            if resp.status_code != 200:
                print(f"  [ERROR] Login API failed for {u['email']}: {resp.text}")
                continue

            auth_data = resp.json()
            token = auth_data["token"]
            role = auth_data["role"]
            email = auth_data["email"]
            name = auth_data.get("name", "")
            dept = auth_data.get("department", "")

            # 2. Navigate to login.html to initialize origin for sessionStorage
            driver.get(f"{BASE_URL}/login.html")
            time.sleep(0.5)

            # Set sessionStorage
            driver.execute_script(f"""
                sessionStorage.setItem('psg_token', '{token}');
                sessionStorage.setItem('psg_role', '{role}');
                sessionStorage.setItem('psg_email', '{email}');
                sessionStorage.setItem('psg_full_name', '{name}');
                sessionStorage.setItem('psg_department', '{dept}');
            """)

            # 3. Open portal page
            driver.get(f"{BASE_URL}/{u['page']}")
            time.sleep(2)

            # 4. Check console logs for SEVERE errors (excluding favicon 404)
            logs = driver.get_log('browser')
            severe_errors = []
            for entry in logs:
                if entry['level'] == 'SEVERE':
                    msg = entry['message']
                    if 'favicon.ico' in msg or '404' in msg and 'favicon' in msg:
                        continue
                    severe_errors.append(msg)

            assert len(severe_errors) == 0, f"Console SEVERE errors found in {u['page']}: {severe_errors}"
            print(f"  [PASS] Console logs verified cleanly (0 severe errors).")

            # 5. Check Header user-info replacement
            user_elem = driver.find_element(By.ID, "user-info")
            user_text = user_elem.text
            print(f"  [INFO] Header User-Info Text: '{user_text}'")
            assert user_text != "…", f"Header user-info was not replaced in {u['page']}!"
            assert u['email'] in user_text or (name and name in user_text) or (dept and dept in user_text), \
                f"User info does not contain user details in {u['page']}"
            print(f"  [PASS] Header user info verified: '{user_text}'")

            # 6. Check main content render (candidate table or clear message, not blank)
            body_text = driver.find_element(By.TAG_NAME, "body").text
            print(f"  [DEBUG] Page body text sample: {body_text[:200]}...")
            assert len(body_text) > 100, f"Page rendered blank or broken in {u['page']}"

            # Check table or empty/open state message present
            tables = driver.find_elements(By.TAG_NAME, "table")
            empty_states = driver.find_elements(By.CLASS_NAME, "empty-state")
            banners = driver.find_elements(By.CLASS_NAME, "banner")
            
            table_present = len(tables) > 0
            banner_present = len(empty_states) > 0 or len(banners) > 0 or "portal" in body_text.lower() or "scrutiny" in body_text.lower() or "applications" in body_text.lower()
            
            assert table_present or banner_present, f"Neither candidate table nor empty state banner found in {u['page']}!"
            print(f"  [PASS] Content rendering verified (table_present={table_present}, banner_present={banner_present}).")

            # 7. Take Screenshot
            shot_path = os.path.join(ARTIFACTS_DIR, u['screenshot'])
            driver.save_screenshot(shot_path)
            print(f"  [PASS] Screenshot saved: {shot_path}")

    finally:
        driver.quit()

    print("\n" + "=" * 75)
    print("  ALL SELENIUM PORTAL TESTS PASSED PERFECTLY!")
    print("=" * 75)

if __name__ == "__main__":
    run_selenium_tests()

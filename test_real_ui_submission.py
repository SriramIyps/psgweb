import json
import time
import os
import io
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client
from pypdf import PdfReader

def run_test():
    # Load env vars
    supabase_url = os.environ.get("SUPABASE_URL") or "https://cadwandjjhakhyilavet.supabase.co"
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k == "SUPABASE_URL": supabase_url = v
                    if k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY") and not supabase_key: supabase_key = v

    sb = create_client(supabase_url, supabase_key)

    # 1. Save previous window settings
    print("--- 1. SAVING PREVIOUS APPLICATION WINDOW SETTINGS ---")
    orig_settings = {}
    try:
        res = sb.table("app_settings").select("key, value").execute()
        for r in (res.data or []):
            orig_settings[r["key"]] = r["value"]
    except Exception as e:
        print("Warning: could not fetch existing app_settings:", e)

    # Open application window for test run
    sb.table("app_settings").upsert([
        {"key": "applications_open", "value": "true"},
        {"key": "open_date", "value": "2020-01-01"},
        {"key": "close_date", "value": "2030-01-01"}
    ], on_conflict="key").execute()

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_window_size(1280, 1024)

    test_email = f"real_ui_cand_{int(time.time())}@psgcas.ac.in"
    test_pass = "Password123!"

    try:
        print(f"\n--- 2. CREATING TEST CANDIDATE: {test_email} ---")
        user_id = None
        for attempt in range(3):
            try:
                user_res = sb.auth.admin.create_user({
                    "email": test_email,
                    "password": test_pass,
                    "email_confirm": True,
                    "user_metadata": { "role": "candidate", "full_name": "Dr. Test Candidate" }
                })
                user_id = user_res.user.id
                break
            except Exception as e:
                print(f"create_user attempt {attempt+1} failed:", e)
                time.sleep(2)

        assert user_id, "Failed to create candidate user after 3 attempts."
        print("Candidate created, user_id:", user_id)

        # Login via API
        driver.get("http://127.0.0.1:5000/login.html")
        login_script = f"""
            const res = await fetch('/api/login', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ email: '{test_email}', password: '{test_pass}' }})
            }});
            const data = await res.json();
            if (res.ok) {{
                sessionStorage.setItem('psg_token', data.token);
                sessionStorage.setItem('psg_role', data.role);
                sessionStorage.setItem('psg_email', data.email);
                return data;
            }}
            return {{ error: data.error }};
        """
        login_res = driver.execute_script(login_script)
        cand_token = login_res.get("token")
        assert cand_token, f"Login failed: {login_res}"
        print("Candidate logged in via API successfully.")

        driver.get("http://127.0.0.1:5000/login.html")
        driver.execute_script(f"""
            sessionStorage.setItem('psg_token', '{cand_token}');
            sessionStorage.setItem('psg_role', 'candidate');
            sessionStorage.setItem('psg_email', '{test_email}');
        """)
        time.sleep(0.5)
        driver.get("http://127.0.0.1:5000/apply.html")
        time.sleep(1)

        interceptor_js = """
        if (!window.__fetch_intercepted) {
            window.__fetch_intercepted = true;
            window.__captured_requests = [];
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                let url = args[0];
                let options = args[1] || {};
                let method = options.method || 'GET';
                let bodyKeys = [];
                let is_submitted_val = null;
                
                if (options.body) {
                    if (typeof options.body === 'string') {
                        try {
                            let parsed = JSON.parse(options.body);
                            bodyKeys = Object.keys(parsed);
                            if ('is_submitted' in parsed) is_submitted_val = parsed.is_submitted;
                        } catch(e) {
                            bodyKeys = ['raw_string'];
                        }
                    } else if (options.body instanceof FormData) {
                        for (let [k, v] of options.body.entries()) {
                            bodyKeys.push(k);
                            if (k === 'is_submitted') is_submitted_val = v;
                        }
                    }
                }
                
                const entry = { type: 'fetch', method: method, url: String(url), payload_keys: bodyKeys, is_submitted: is_submitted_val, status: null, response_body: null };
                window.__captured_requests.push(entry);
                
                try {
                    const res = await origFetch.apply(this, args);
                    entry.status = res.status;
                    const clone = res.clone();
                    entry.response_body = await clone.text();
                    return res;
                } catch(err) {
                    entry.status = 'ERROR: ' + err.message;
                    throw err;
                }
            };
        }
        """
        driver.execute_script(interceptor_js)

        print("\n--- 3. POPULATING APPLICATION FORM & RESEARCH ROWS ---")
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.querySelectorAll('#id_department option').length > 1;")
            )
        except Exception as ex:
            print(f"DEBUG: Current URL: {driver.current_url}")
            print(f"DEBUG: Page Title: {driver.title}")
            dept_len = driver.execute_script("return document.querySelectorAll('#id_department option').length")
            print(f"DEBUG: Dept options count: {dept_len}")
            tok = driver.execute_script("return sessionStorage.getItem('psg_token')")
            print(f"DEBUG: SessionStorage token: {tok}")
            logs = driver.get_log('browser')
            print(f"DEBUG: Browser logs: {logs}")
            raise ex
        time.sleep(0.5)

        driver.execute_script("""
            function setVal(id, val) {
                let el = document.getElementById(id);
                if (el) el.value = val;
            }
            setVal('id_position', 'Assistant Professor');
            setVal('id_department', 'Computer Science');
            setVal('id_name', 'Dr. Test Candidate');
            setVal('id_dob', '1990-05-15');
            setVal('id_gender', 'Male');
            setVal('id_mother_tongue', 'English');
            setVal('id_religion', 'Indian');
            setVal('id_community', 'OC');
            setVal('id_category', 'FC');
            setVal('id_father_name', 'Father Name');
            setVal('id_marital_status', 'Single');
            setVal('id_aadhaar_no', '999988887777');
            setVal('id_pan_no', 'ABCDE9999F');
            setVal('id_mobile_no', '9876543210');
            setVal('id_email', '""" + test_email + """');
            setVal('id_native_address', '123 Tech Park Road');
            setVal('id_native_city', 'Coimbatore');
            setVal('id_native_state', 'Tamil Nadu');
            setVal('id_native_country', 'India');
            setVal('id_native_pincode', '641014');
            setVal('id_local_address', '123 Tech Park Road');
            setVal('id_local_city', 'Coimbatore');
            setVal('id_local_state', 'Tamil Nadu');
            setVal('id_local_country', 'India');
            setVal('id_local_pincode', '641014');
            setVal('id_pay_expected', '1000000');
            setVal('id_join_time', 'Immediate');
            setVal('id_name_1', 'Ref Person 1');
            setVal('id_designation_1', 'Professor');
            setVal('id_mobile_1', '9123456780');
            setVal('id_email_1', 'ref1@example.com');
            setVal('id_address_1', 'Ref 1 Address');
            setVal('id_name_2', 'Ref Person 2');
            setVal('id_designation_2', 'Dean');
            setVal('id_mobile_2', '9123456781');
            setVal('id_email_2', 'ref2@example.com');
            setVal('id_address_2', 'Ref 2 Address');
            setVal('id_already_attended', 'No');
            setVal('id_huk', 'Website');
        """)

        # Add 1 publication
        driver.find_element(By.ID, "add-pub").click()
        time.sleep(0.3)
        driver.execute_script("""
            let pub = document.querySelector('.pub-item');
            if (pub) {
                let typeSel = pub.querySelector('.pub-type');
                if (typeSel) typeSel.value = 'Journal article';
                let scopeSel = pub.querySelector('.pub-scope');
                if (scopeSel) scopeSel.value = 'International';
                let idxWrap = pub.querySelector('.pub-idx-wrap');
                if (idxWrap) idxWrap.style.display = 'block';
                let idxSel = pub.querySelector('.pub-idx');
                if (idxSel) idxSel.value = 'SCI';
                pub.querySelector('.pub-title').value = 'Quantum Machine Learning in Healthcare';
                pub.querySelector('.pub-pub').value = 'IEEE Transactions on Neural Networks';
                pub.querySelector('.pub-year').value = '2025';
            }
        """)

        # Add 1 patent
        driver.find_element(By.ID, "add-pat").click()
        time.sleep(0.3)
        driver.execute_script("""
            let pat = document.querySelector('.pat-item');
            if (pat) {
                pat.querySelector('.pat-title').value = 'Fault-Tolerant Quantum Circuit Patent';
                pat.querySelector('.pat-status').value = 'Published';
                pat.querySelector('.pat-num').value = 'PAT-2026-888';
                pat.querySelector('.pat-year').value = '2026';
            }
        """)

        # Add 1 consultancy
        driver.find_element(By.ID, "add-con").click()
        time.sleep(0.3)
        driver.execute_script("""
            let con = document.querySelector('.con-item');
            if (con) {
                con.querySelector('.con-client').value = 'Global AI Solutions Ltd';
                con.querySelector('.con-title').value = 'High-Performance ML Pipeline Consultancy';
                con.querySelector('.con-year').value = '2025';
                con.querySelector('.con-amt').value = '250000';
            }
        """)

        # Add 1 project
        driver.find_element(By.ID, "add-prj").click()
        time.sleep(0.3)
        driver.execute_script("""
            let prj = document.querySelector('.prj-item');
            if (prj) {
                prj.querySelector('.prj-title').value = 'Autonomous AI Agent Security Framework';
                prj.querySelector('.prj-agency').value = 'DST-SERB';
                prj.querySelector('.prj-type').value = 'Major';
                prj.querySelector('.prj-role').value = 'PI';
            }
        """)

        print("\n--- 4. CLICKING SAVE DRAFT ---")
        driver.execute_script("window.__captured_requests = [];")
        save_draft_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Save Draft')]")
        save_draft_btn.click()

        alert_accepted = False
        for _ in range(20):
            try:
                alert = driver.switch_to.alert
                print("Captured browser alert after Save Draft:", alert.text)
                alert.accept()
                alert_accepted = True
                break
            except Exception:
                time.sleep(0.5)

        if not alert_accepted:
            print("No alert presented after Save Draft.")

        time.sleep(1)
        draft_reqs = driver.execute_script("return window.__captured_requests || [];")
        print("Save Draft captured requests:")
        for r in draft_reqs:
            print(f"Method: {r['method']} | URL: {r['url']} | Status: {r['status']}")
            print(f"Payload Keys: {r['payload_keys']}")
            print(f"is_submitted: {r['is_submitted']}")
            print(f"Response Body: {r['response_body']}")

        # Ensure interceptor is present before submit
        driver.execute_script(interceptor_js)

        print("\n--- 5. CLICKING SUBMIT APPLICATION ---")
        driver.execute_script("window.__captured_requests = [];")
        
        # Print invalid form elements and mandatory field values
        mandatory_vals = driver.execute_script("""
            let f = document.getElementById('apply-form');
            let decl = document.getElementById('id_tac');
            if (decl) decl.checked = true;
            return {
                position: f.position?.value,
                department: f.department?.value,
                name: f.name?.value,
                email: f.email?.value,
                mobile_no: f.mobile_no?.value
            };
        """)
        print("MANDATORY FORM VALUES BEFORE SUBMIT:", mandatory_vals)

        driver.execute_script("saveApplication(true);")
        time.sleep(5)

        submit_reqs = driver.execute_script("return window.__captured_requests || [];")
        print("Submit Application captured requests:")
        for r in submit_reqs:
            print(f"Method: {r['method']} | URL: {r['url']} | Status: {r['status']}")
            print(f"Payload Keys: {r['payload_keys']}")
            print(f"is_submitted: {r['is_submitted']}")
            print(f"Response Body: {r['response_body']}")

        err_msg = driver.execute_script("return document.getElementById('form-error-banner')?.textContent || '';")
        print("Form Error Banner text:", err_msg)

        print("\n--- 6. QUERYING DATABASE FOR VERIFICATION ---")
        app_res = sb.table("applications").select("id, status, is_locked, submitted_at, app_uuid").eq("user_id", user_id).execute()
        assert app_res.data, "No application found in database for candidate!"
        app_row = app_res.data[0]
        app_id = app_row["id"]
        
        db_status = app_row.get("status")
        db_is_locked = app_row.get("is_locked")
        db_submitted_at = app_row.get("submitted_at")

        print("DATABASE VALUES FOR SUBMITTED APPLICATION:")
        print(f"Application ID: {app_id}")
        print(f"App Reference UUID: {app_row.get('app_uuid')}")
        print(f"status: {db_status}")
        print(f"is_locked: {db_is_locked}")
        print(f"submitted_at: {db_submitted_at}")

        assert db_status == "Submitted", f"Expected status 'Submitted', got '{db_status}'"
        assert db_is_locked is True, f"Expected is_locked True, got {db_is_locked}"
        assert db_submitted_at is not None, "Expected submitted_at to be populated"

        # Query child research tables
        pubs = sb.table("app_publications").select("*").eq("application_id", app_id).execute().data or []
        pats = sb.table("app_patents").select("*").eq("application_id", app_id).execute().data or []
        cons = sb.table("app_consultancy").select("*").eq("application_id", app_id).execute().data or []
        prjs = sb.table("app_projects").select("*").eq("application_id", app_id).execute().data or []

        print("\nRESEARCH TABLE ROW COUNTS IN DATABASE:")
        print(f"app_publications row count: {len(pubs)}")
        print(f"app_patents row count: {len(pats)}")
        print(f"app_consultancy row count: {len(cons)}")
        print(f"app_projects row count: {len(prjs)}")

        assert len(pubs) >= 1, "app_publications table has 0 rows!"
        assert len(pats) >= 1, "app_patents table has 0 rows!"
        assert len(cons) >= 1, "app_consultancy table has 0 rows!"
        assert len(prjs) >= 1, "app_projects table has 0 rows!"

        print("\n--- 7. DOWNLOADING PDF AND EXTRACTING TEXT ---")
        pdf_res = requests.get(
            f"http://127.0.0.1:5000/api/applications/{app_id}/pdf",
            headers={"Authorization": f"Bearer {cand_token}"}
        )
        assert pdf_res.status_code == 200, f"PDF fetch failed with status {pdf_res.status_code}: {pdf_res.text}"
        
        pdf_reader = PdfReader(io.BytesIO(pdf_res.content))
        pdf_text = "\n".join([page.extract_text() for page in pdf_reader.pages])
        print("PDF extracted text preview (first 500 chars):")
        print(pdf_text[:500])

        assert "Quantum Machine Learning in Healthcare" in pdf_text, "Publication title missing from PDF text!"
        assert "Fault-Tolerant Quantum Circuit Patent" in pdf_text, "Patent title missing from PDF text!"
        assert "High-Performance ML Pipeline Consultancy" in pdf_text, "Consultancy title missing from PDF text!"
        assert "Autonomous AI Agent Security Framework" in pdf_text, "Project title missing from PDF text!"
        print("All 4 research rows verified in PDF text successfully.")

        print("\n--- 8. ATTEMPTING RE-SAVE ON LOCKED APPLICATION (MUST FAIL WITH 403) ---")
        re_save = requests.post(
            "http://127.0.0.1:5000/api/my-application",
            headers={"Authorization": f"Bearer {cand_token}"},
            data={"name": "Attempt Edit", "is_submitted": "false"}
        )
        print(f"Re-save response status: {re_save.status_code}, body: {re_save.text}")
        assert re_save.status_code == 403, f"Expected 403 Forbidden on locked application edit, got {re_save.status_code}"

        re_research = requests.post(
            f"http://127.0.0.1:5000/api/applications/{app_id}/research",
            headers={"Authorization": f"Bearer {cand_token}"},
            json={"publications": []}
        )
        print(f"Re-research response status: {re_research.status_code}, body: {re_research.text}")
        assert re_research.status_code == 403, f"Expected 403 Forbidden on locked research edit, got {re_research.status_code}"
        print("Re-save rejected with 403 Forbidden as expected.")

        print("\n[SUCCESS] All verification steps passed cleanly!")

    finally:
        driver.quit()
        # Restore window settings
        print("\n--- RESTORING PREVIOUS APPLICATION WINDOW SETTINGS ---")
        for k, v in orig_settings.items():
            sb.table("app_settings").upsert({"key": k, "value": v}, on_conflict="key").execute()

if __name__ == "__main__":
    run_test()

import json
import time
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client

def run_diagnosis():
    # Load env vars
    supabase_url = os.environ.get("SUPABASE_URL") or "https://mock.supabase.co"
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
    
    # Read .env if present
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k == "SUPABASE_URL": supabase_url = v
                    if k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY") and not supabase_key: supabase_key = v

    sb = create_client(supabase_url, supabase_key)
    
    # Set application window open
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

    test_email = f"diag_cand_{int(time.time())}@psgcas.ac.in"
    test_pass = "Password123!"

    print(f"--- 1. REGISTER & LOGIN FOR {test_email} ---")
    driver.get("http://127.0.0.1:5000/login.html")
    
    # Register candidate directly or via API
    try:
        user_res = sb.auth.admin.create_user({
            "email": test_email,
            "password": test_pass,
            "email_confirm": True,
            "user_metadata": { "role": "candidate", "full_name": "Diag Candidate" }
        })
        print("Candidate created successfully:", user_res.user.id)
    except Exception as e:
        print("Error creating candidate:", e)

    # Log in via API to get token
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
    print("API Login Result:", login_res)

    driver.get("http://127.0.0.1:5000/apply.html")
    time.sleep(1)

    # Interceptor script to record fetch/XHR
    interceptor_js = """
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
    """
    
    driver.get("http://127.0.0.1:5000/apply.html")
    time.sleep(1)
    driver.execute_script(interceptor_js)

    print("\n--- 2. FILLING CANDIDATE FORM & RESEARCH ROWS ---")
    WebDriverWait(driver, 10).until(
        lambda d: d.execute_script("return document.querySelectorAll('#id_department option').length > 1;")
    )
    time.sleep(0.5)
    driver.execute_script("""
        function setVal(id, val) {
            let el = document.getElementById(id);
            if (el) el.value = val;
        }
        setVal('id_position', 'Assistant Professor');
        setVal('id_department', 'Computer Science');
        setVal('id_name', 'Diag Candidate');
        setVal('id_dob', '1990-01-01');
        setVal('id_gender', 'Male');
        setVal('id_mother_tongue', 'Tamil');
        setVal('id_religion', 'Hindu');
        setVal('id_community', 'OC');
        setVal('id_category', 'FC');
        setVal('id_father_name', 'Father Name');
        setVal('id_marital_status', 'Single');
        setVal('id_aadhaar_no', '123456789012');
        setVal('id_pan_no', 'ABCDE1234F');
        setVal('id_mobile_no', '9876543210');
        setVal('id_email', '""" + test_email + """');
        setVal('id_native_address', 'Native Address 123');
        setVal('id_native_city', 'Coimbatore');
        setVal('id_native_state', 'Tamil Nadu');
        setVal('id_native_country', 'India');
        setVal('id_native_pincode', '641014');
        setVal('id_local_address', 'Local Address 123');
        setVal('id_local_city', 'Coimbatore');
        setVal('id_local_state', 'Tamil Nadu');
        setVal('id_local_country', 'India');
        setVal('id_local_pincode', '641014');
    """)

    # Add 1 publication, patent, consultancy, project
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
            pub.querySelector('.pub-title').value = 'AI Research Paper 2026';
            pub.querySelector('.pub-pub').value = 'IEEE Transactions';
            pub.querySelector('.pub-year').value = '2025';
        }
    """)

    driver.find_element(By.ID, "add-pat").click()
    time.sleep(0.3)
    driver.execute_script("""
        let pat = document.querySelector('.pat-item');
        if (pat) {
            pat.querySelector('.pat-title').value = 'Novel Neural Architecture Patent';
            pat.querySelector('.pat-status').value = 'Published';
            pat.querySelector('.pat-num').value = 'PAT-2025-999';
            pat.querySelector('.pat-year').value = '2025';
        }
    """)

    driver.find_element(By.ID, "add-con").click()
    time.sleep(0.3)
    driver.execute_script("""
        let con = document.querySelector('.con-item');
        if (con) {
            con.querySelector('.con-client').value = 'TechCorp Inc';
            con.querySelector('.con-title').value = 'Enterprise AI Consultancy';
            con.querySelector('.con-year').value = '2025';
            con.querySelector('.con-amt').value = '150000';
        }
    """)

    driver.find_element(By.ID, "add-prj").click()
    time.sleep(0.3)
    driver.execute_script("""
        let prj = document.querySelector('.prj-item');
        if (prj) {
            prj.querySelector('.prj-title').value = 'Grant for Quantum Computing';
            prj.querySelector('.prj-agency').value = 'DST-SERB';
            prj.querySelector('.prj-type').value = 'Major';
            prj.querySelector('.prj-role').value = 'PI';
        }
    """)

    print("\n--- 3. CLICKING SAVE DRAFT ---")
    driver.execute_script("window.__captured_requests = [];") # clear log before draft click
    save_draft_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Save Draft')]")
    save_draft_btn.click()
    time.sleep(2)

    draft_reqs = driver.execute_script("return window.__captured_requests;")
    print("DRAFT SAVE CAPTURED REQUESTS:")
    for r in draft_reqs:
        print(f"Method: {r['method']} | URL: {r['url']} | Status: {r['status']}")
        print(f"Payload Keys: {r['payload_keys']}")
        print(f"is_submitted: {r['is_submitted']}")
        print(f"Response Body: {r['response_body']}")
        print("-" * 50)
    
    val_msg = driver.execute_script("return document.getElementById('form-error-banner')?.textContent || '';")
    print("Page Error Banner after Save Draft:", val_msg)

    print("\n--- 4. CLICKING SUBMIT ---")
    driver.execute_script("window.__captured_requests = [];") # clear log before submit click
    submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Submit Application')]")
    
    # Check declaration if present
    decl = driver.find_elements(By.ID, "id_declaration")
    if decl and not decl[0].is_selected():
        decl[0].click()

    submit_btn.click()
    time.sleep(2)

    submit_reqs = driver.execute_script("return window.__captured_requests;")
    print("SUBMIT CAPTURED REQUESTS:")
    for r in submit_reqs:
        print(f"Method: {r['method']} | URL: {r['url']} | Status: {r['status']}")
        print(f"Payload Keys: {r['payload_keys']}")
        print(f"is_submitted: {r['is_submitted']}")
        print(f"Response Body: {r['response_body']}")
        print("-" * 50)

    val_msg_submit = driver.execute_script("return document.getElementById('form-error-banner')?.textContent || '';")
    print("Page Error Banner after Submit:", val_msg_submit)

    driver.quit()

if __name__ == "__main__":
    run_diagnosis()

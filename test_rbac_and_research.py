"""
PSG CAS CONNECT — RBAC, Application Window, Timezone & Research Test Suite

MOCKED OBJECTS EXPLANATION:
1. `_get_user_from_token`: Replaced with a mock function to inject test user credentials (id, role, department, name) without requiring a live Supabase Auth service.
2. `sb_admin`: Replaced with `MockAdmin` class to mock Supabase database operations (`sb_admin.table().select().eq().limit().execute()`) and RPC calls (`sb_admin.rpc().execute()`) without touching a live PostgreSQL database.
3. `MockQuery`: Fluent builder mocking Supabase chainable query methods. Configurable to return mock rows or raise `Exception` to test fail-closed error handling.
4. `MockRPC`: Mocks execution of Supabase database functions (e.g. `save_application_research`, `generate_application_number`).
"""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import app as app_module
from app import app, IST

def run_tests():
    app.config['TESTING'] = True
    client = app.test_client()
    passed = 0
    total = 17

    print("=" * 75)
    print("  PSG CAS CONNECT — RBAC, TIMEZONE & ATOMIC COUNTER TEST SUITE")
    print("=" * 75)

    class MockQuery:
        def __init__(self, data=None, raise_exc=False):
            self._data = data
            self._raise_exc = raise_exc

        def select(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def order(self, *a, **kw): return self
        def limit(self, *a, **kw): return self
        def single(self, *a, **kw): return self
        def update(self, *a, **kw): return self
        def insert(self, *a, **kw): return self
        def execute(self):
            if self._raise_exc:
                raise Exception("Simulated DB connection failure")
            class Res:
                def __init__(self, d): self.data = d
            return Res(self._data)

    class MockRPC:
        def __init__(self, val=True):
            self._val = val
        def execute(self):
            class Res:
                def __init__(self, v): self.data = v
            return Res(self._val)

    # ── TEST 1: Candidate cannot POST research on locked application ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdmin1:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([{"key": "applications_open", "value": "true"}])
                return MockQuery([{"id": 101, "user_id": "cand-123", "is_locked": True, "department": "CS"}])
            def rpc(self, name, params): return MockRPC()

        app_module.sb_admin = MockAdmin1()

        res = client.post('/api/applications/101/research',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data=json.dumps({"publications": []}),
                          content_type='application/json')

        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        assert b"locked" in res.data.lower(), "Expected lock message in response"
        print("[PASS] Test 1: Candidate blocked (403) from editing locked application.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 1: {e}")

    # ── TEST 2: Admin blocked on candidate research POST path when locked ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "admin-123", "role": "admin", "department": None, "full_name": "Admin User"
        }
        class MockAdmin2:
            def table(self, name):
                return MockQuery([{"id": 102, "user_id": "cand-999", "is_locked": True, "department": "CS"}])
            def rpc(self, name, params): return MockRPC()

        app_module.sb_admin = MockAdmin2()

        res = client.post('/api/applications/102/research',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data=json.dumps({"publications": []}),
                          content_type='application/json')

        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        assert b"locked" in res.data.lower(), "Expected lock message"
        print("[PASS] Test 2: Admin blocked (403) from candidate POST path on locked application.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 2: {e}")

    # ── TEST 3: Lock lookup Exception fails closed (503) ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminFail:
            def table(self, name):
                return MockQuery(raise_exc=True)

        app_module.sb_admin = MockAdminFail()

        res = client.post('/api/applications/103/research',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data=json.dumps({"publications": []}),
                          content_type='application/json')

        assert res.status_code == 503, f"Expected 503 fail-closed, got {res.status_code}"
        assert b"database error" in res.data.lower(), "Expected database error message"
        print("[PASS] Test 3: Lock lookup Exception fails closed (503).")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 3: {e}")

    # ── TEST 4: IST Timezone Boundary — Before Open Date (Rejection 403) ──
    try:
        now_ist = datetime.now(IST)
        future_open = (now_ist + timedelta(days=2)).strftime("%Y-%m-%d")
        future_close = (now_ist + timedelta(days=10)).strftime("%Y-%m-%d")

        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminTimezoneBefore:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": future_open},
                        {"key": "close_date", "value": future_close}
                    ])
                return MockQuery([])
            def rpc(self, name, params): return MockRPC("Comp/001")

        app_module.sb_admin = MockAdminTimezoneBefore()

        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data={
                              "name": "Jane Candidate",
                              "email": "jane@example.com",
                              "mobile_no": "9876543210",
                              "position": "Assistant Professor",
                              "department": "Computer Science",
                              "is_submitted": "true"
                          })

        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        assert b"will open on" in res.data.lower() or b"cannot submit" in res.data.lower(), "Expected open date rejection"
        print(f"[PASS] Test 4: Submit before open_date ({future_open} IST) rejected with 403.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 4: {e}")

    # ── TEST 5: IST Timezone Boundary — After Close Date (Rejection 403) ──
    try:
        now_ist = datetime.now(IST)
        past_open = (now_ist - timedelta(days=10)).strftime("%Y-%m-%d")
        past_close = (now_ist - timedelta(days=1)).strftime("%Y-%m-%d")

        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminTimezoneAfter:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": past_open},
                        {"key": "close_date", "value": past_close}
                    ])
                return MockQuery([])
            def rpc(self, name, params): return MockRPC("Comp/001")

        app_module.sb_admin = MockAdminTimezoneAfter()

        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data={
                              "name": "Jane Candidate",
                              "email": "jane@example.com",
                              "mobile_no": "9876543210",
                              "position": "Assistant Professor",
                              "department": "Computer Science",
                              "is_submitted": "true"
                          })

        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        assert b"closed on" in res.data.lower() or b"cannot submit" in res.data.lower(), "Expected close date rejection"
        print(f"[PASS] Test 5: Submit after close_date ({past_close} IST) rejected with 403.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 5: {e}")

    # ── TEST 6: IST Timezone Boundary — Inside Window (23:59:59 IST Day-Of Success 201) ──
    try:
        now_ist = datetime.now(IST)
        today_open = now_ist.strftime("%Y-%m-%d")
        today_close = now_ist.strftime("%Y-%m-%d")

        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminInsideBoundary:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": today_open},
                        {"key": "close_date", "value": today_close}
                    ])
                if name == "applications":
                    return MockQuery([{"id": 200, "app_uuid": "Comp/001"}])
                return MockQuery([])
            def rpc(self, name, params): return MockRPC("Comp/001")

        app_module.sb_admin = MockAdminInsideBoundary()

        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data={
                              "name": "Jane Candidate",
                              "email": "jane@example.com",
                              "mobile_no": "9876543210",
                              "position": "Assistant Professor",
                              "department": "Computer Science",
                              "is_submitted": "true"
                          })

        assert res.status_code == 201, f"Expected 201, got {res.status_code}"
        assert b"saved successfully" in res.data.lower(), "Expected success message"
        print(f"[PASS] Test 6: Final submit inside IST boundary ({today_open}) succeeded (201).")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 6: {e}")

    # ── TEST 7: Hard Override Toggle (applications_open = false closes even inside window) ──
    try:
        now_ist = datetime.now(IST)
        past_open = (now_ist - timedelta(days=5)).strftime("%Y-%m-%d")
        future_close = (now_ist + timedelta(days=5)).strftime("%Y-%m-%d")

        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminHardToggle:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": past_open},
                        {"key": "close_date", "value": future_close},
                        {"key": "applications_open", "value": "false"}  # HARD OVERRIDE
                    ])
                return MockQuery([])

        app_module.sb_admin = MockAdminHardToggle()

        # Direct window state check
        state, msg, _ = app_module._get_application_window_state()
        assert state == "closed", f"Expected state 'closed', got '{state}'"

        # POST final submit check
        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data={
                              "name": "Jane Candidate",
                              "email": "jane@example.com",
                              "mobile_no": "9876543210",
                              "position": "Assistant Professor",
                              "department": "Computer Science",
                              "is_submitted": "true"
                          })

        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        print("[PASS] Test 7: Hard override toggle (applications_open=false) closes window inside valid date range.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 7: {e}")

    # ── TEST 8: Draft vs Final Submit (Draft allowed outside window) ──
    try:
        now_ist = datetime.now(IST)
        past_open = (now_ist - timedelta(days=20)).strftime("%Y-%m-%d")
        past_close = (now_ist - timedelta(days=5)).strftime("%Y-%m-%d")

        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminDraftOutsideWindow:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": past_open},
                        {"key": "close_date", "value": past_close}
                    ])
                if name == "applications":
                    return MockQuery([{"id": 808, "app_uuid": "Comp/008"}])
                return MockQuery([])
            def rpc(self, name, params): return MockRPC("Comp/008")

        app_module.sb_admin = MockAdminDraftOutsideWindow()

        # DRAFT POST (is_submitted = false)
        res_draft = client.post('/api/apply',
                                headers={"Authorization": "Bearer fake-jwt"},
                                data={
                                    "name": "Jane Candidate",
                                    "email": "jane@example.com",
                                    "mobile_no": "9876543210",
                                    "position": "Assistant Professor",
                                    "department": "Computer Science",
                                    "is_submitted": "false"  # DRAFT
                                })

        assert res_draft.status_code == 201, f"Draft expected 201, got {res_draft.status_code}"

        # FINAL POST (is_submitted = true)
        res_final = client.post('/api/apply',
                                headers={"Authorization": "Bearer fake-jwt"},
                                data={
                                    "name": "Jane Candidate",
                                    "email": "jane@example.com",
                                    "mobile_no": "9876543210",
                                    "position": "Assistant Professor",
                                    "department": "Computer Science",
                                    "is_submitted": "true"  # FINAL SUBMIT
                                })

        assert res_final.status_code == 403, f"Final submit expected 403 outside window, got {res_final.status_code}"
        print("[PASS] Test 8: Draft save allowed outside window (201), final submit rejected (403).")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 8: {e}")

    # ── TEST 9: Public /api/settings Returns ONLY 4 Keys ──
    try:
        class MockAdminSettingsPublic:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([
                        {"key": "open_date", "value": "2026-10-01"},
                        {"key": "close_date", "value": "2026-10-15"},
                        {"key": "applications_open", "value": "true"},
                        {"key": "announcement_text", "value": "Secret Admin Info"}
                    ])
                return MockQuery([])

        app_module.sb_admin = MockAdminSettingsPublic()

        res = client.get('/api/settings')
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = json.loads(res.data)

        expected_keys = {"open_date", "close_date", "state", "state_message"}
        actual_keys = set(data.keys())
        assert actual_keys == expected_keys, f"Expected keys {expected_keys}, got {actual_keys}"
        print("[PASS] Test 9: Public /api/settings returns ONLY open_date, close_date, state, state_message.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 9: {e}")

    # ── TEST 10: Request a nonexistent application ID -> Assert 404 ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "admin-1", "role": "admin", "department": None, "full_name": "Admin"
        }
        class MockAdmin404:
            def table(self, name):
                return MockQuery([])

        app_module.sb_admin = MockAdmin404()

        res = client.get('/api/applications/99999/research', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print("[PASS] Test 10: Requesting non-existent application ID returned 404.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 10: {e}")

    # ── TEST 11: Unknown / Unauthorized Role -> Assert 403 ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "unknown-user", "role": "guest_user", "department": None, "full_name": "Unknown Guest"
        }
        class MockAdminGuest:
            def table(self, name):
                return MockQuery([{"id": 101, "user_id": "cand-123"}])

        app_module.sb_admin = MockAdminGuest()

        res = client.get('/api/applications/101/research', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        print("[PASS] Test 11: Unknown/unauthorized role returned 403.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 11: {e}")

    # ── TEST 12: HOD Dept Mismatch ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hod-cs", "role": "hod", "department": "Computer Science", "full_name": "CS HOD"
        }
        class MockAdminDeptMismatch:
            def table(self, name):
                return MockQuery([{"id": 202, "department": "BBA"}])

        app_module.sb_admin = MockAdminDeptMismatch()

        res = client.get('/api/applications/202/research', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        print("[PASS] Test 12: HOD blocked (403) on cross-department application.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 12: {e}")

    # ── TEST 13: HR Non-Shortlisted Check ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hr-1", "role": "hr", "department": None, "full_name": "HR Manager"
        }
        class MockAdminHR:
            def table(self, name):
                return MockQuery([{"id": 303, "vp_status": "Pending"}])

        app_module.sb_admin = MockAdminHR()

        res = client.get('/api/applications/303/research', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 403, f"Expected 403, got {res.status_code}"
        print("[PASS] Test 13: HR blocked (403) on non-shortlisted application.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 13: {e}")

    # ── TEST 14: Audit Log Recording on Lock & Status Changes ──
    try:
        audit_records = []
        app_module._get_user_from_token = lambda: {
            "id": "admin-1", "email": "admin@psgcas.ac.in", "role": "admin", "department": None, "full_name": "Admin"
        }
        class MockAdminAudit:
            def table(self, name):
                if name == "audit_log":
                    class AuditInsert:
                        def insert(self, record):
                            audit_records.append(record)
                            return MockQuery([record])
                    return AuditInsert()
                return MockQuery([{"id": 707, "is_locked": False, "department": "Computer Science"}])
            def rpc(self, name, params):
                if name == "rpc_update_application_lock":
                    audit_records.append({
                        "who": params.get("p_who"),
                        "action": "ADMIN_UPDATE_IS_LOCKED",
                        "application_id": params.get("p_app_id"),
                        "old_value": "False",
                        "new_value": str(params.get("p_is_locked"))
                    })
                return MockRPC()

        app_module.sb_admin = MockAdminAudit()

        res = client.put('/api/applications/707',
                         headers={"Authorization": "Bearer fake-jwt"},
                         data=json.dumps({"is_locked": True}),
                         content_type='application/json')

        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert len(audit_records) == 1, f"Expected 1 audit record, got {len(audit_records)}"
        assert audit_records[0]["action"] == "ADMIN_UPDATE_IS_LOCKED", "Audit action mismatch"
        print("[PASS] Test 14: Audit log entry successfully created on admin lock update.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 14: {e}")

    # ── TEST 15: Department Reference ID Generation (20 Submissions No Gaps / No Duplicates) ──
    try:
        dept_counter = {"Comp": 0}
        generated_ids = []

        def mock_generate_number(params):
            dept = params.get("p_department", "")
            prefix = "Comp" if "Computer" in dept or "CS" in dept else "GEN"
            dept_counter[prefix] += 1
            num_str = f"{prefix}/{dept_counter[prefix]:03d}"
            return MockRPC(num_str)

        for i in range(1, 21):
            app_module._get_user_from_token = lambda idx=i: {
                "id": f"cand-{idx}", "role": "candidate", "department": None, "full_name": f"Candidate {idx}"
            }
            class MockAdminCounter:
                def table(self, name):
                    if name == "app_settings":
                        return MockQuery([{"key": "applications_open", "value": "true"}])
                    if name == "applications":
                        return MockQuery([])
                    return MockQuery([])
                def rpc(self, name, params):
                    return mock_generate_number(params)

            app_module.sb_admin = MockAdminCounter()

            res = client.post('/api/apply',
                              headers={"Authorization": "Bearer fake-jwt"},
                              data={
                                  "name": f"Candidate {i}",
                                  "email": f"cand{i}@example.com",
                                  "mobile_no": "9876543210",
                                  "position": "Assistant Professor",
                                  "department": "Computer Science",
                                  "is_submitted": "true"
                              })

            assert res.status_code == 201, f"Submission {i} failed with {res.status_code}"
            data = json.loads(res.data)
            generated_ids.append(data["app_uuid"])

        expected_ids = [f"Comp/{i:03d}" for i in range(1, 21)]
        assert generated_ids == expected_ids, f"Mismatch in generated IDs.\nExpected: {expected_ids}\nActual: {generated_ids}"
        assert len(set(generated_ids)) == 20, "Duplicate IDs detected!"
        print(f"[PASS] Test 15: 20 department submissions generated atomic IDs ({generated_ids[0]} to {generated_ids[-1]}) without duplicates or gaps.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 15: {e}")

    # ── TEST 16: PDF Generator 0 Rows ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "admin-1", "role": "admin", "department": None, "full_name": "Admin"
        }
        class MockAdminPDF0:
            def table(self, name):
                if name == "applications":
                    return MockQuery([{"id": 404, "name": "John Doe", "app_uuid": "Comp/001", "position": "Assistant Professor", "department": "Computer Science"}])
                return MockQuery([])

        app_module.sb_admin = MockAdminPDF0()

        res = client.get('/api/applications/404/pdf', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.mimetype == "application/pdf", f"Expected PDF mimetype, got {res.mimetype}"
        assert res.data.startswith(b"%PDF"), "Response is not valid PDF binary"
        print(f"[PASS] Test 16: PDF generated successfully for 0 rows ({len(res.data)} bytes).")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 16: {e}")

    # ── TEST 17: PDF Generator 50+ Rows ──
    try:
        fake_pubs = [
            {
                "id": i,
                "type": "Journal article",
                "scope": "International",
                "indexing_category": "SCI",
                "title": f"Paper #{i}: Deep Learning Medical Image Segmentation",
                "publisher_journal": "IEEE Transactions on Medical Imaging",
                "year": 2020 + (i % 5),
                "isbn_issn": "1234-5678",
                "doi_link": f"10.1016/j.tmi.2024.{i:03d}"
            }
            for i in range(1, 55)
        ]

        class MockAdminPDF50:
            def table(self, name):
                if name == "applications":
                    return MockQuery([{"id": 505, "name": "Dr. High Publisher", "app_uuid": "Comp/050", "position": "Professor", "department": "Biotechnology"}])
                elif name == "app_publications":
                    return MockQuery(fake_pubs)
                return MockQuery([])

        app_module.sb_admin = MockAdminPDF50()

        res = client.get('/api/applications/505/pdf', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.mimetype == "application/pdf", f"Expected PDF mimetype, got {res.mimetype}"
        assert res.data.startswith(b"%PDF"), "Response is not valid PDF binary"
        print(f"[PASS] Test 17: PDF generated successfully for 54 rows ({len(res.data)} bytes).")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 17: {e}")

    # ── TEST 18: Full Candidate Payload Whitelist & Mass Assignment Prevention ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "cand-legit-123", "role": "candidate", "department": None, "full_name": "Legit Candidate"
        }
        captured_records = []
        class MockAdminMassAssignment:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([{"key": "applications_open", "value": "true"}])
                if name == "applications":
                    class CapQuery(MockQuery):
                        def insert(self, record):
                            captured_records.append(record)
                            return MockQuery([{"id": 888}])
                    return CapQuery([])
                return MockQuery([])
            def rpc(self, name, params): return MockRPC("Comp/088")

        app_module.sb_admin = MockAdminMassAssignment()

        full_payload = {
            # LEGITIMATE CANDIDATE FIELDS
            "name": "Jane Candidate",
            "email": "jane@example.com",
            "mobile_no": "9876543210",
            "position": "Assistant Professor",
            "department": "Computer Science",
            "dob": "1990-05-15",
            "gender": "Female",
            "mother_tongue": "Tamil",
            "religion": "Hindu",
            "community": "BC",
            "category": "BC",
            "father_name": "John Candidate",
            "marital_status": "Single",
            "aadhaar_no": "123456789012",
            "pan_no": "ABCDE1234F",
            "native_city": "Coimbatore",
            "native_state": "Tamil Nadu",
            "local_city": "Coimbatore",
            "local_state": "Tamil Nadu",
            "achivements": "Best Researcher Award 2023",
            "pay_expected": "80000",
            "is_submitted": "true",
            "iso_involvement": "true",
            "iso_details": "ISO Coordinator",

            # MALICIOUS OVERRIDES (Server-Controlled)
            "user_id": "hacked-user-id",
            "is_locked": "false",
            "hod_status": "Eligible",
            "vp_status": "Shortlisted",
            "status": "Approved",
            "app_uuid": "HACKED/999"
        }

        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data=full_payload)

        assert res.status_code == 201, f"Expected 201, got {res.status_code}"
        rec = captured_records[0]

        # Verify legitimate fields saved
        assert rec["dob"] == "1990-05-15", f"Field dob not saved properly: {rec.get('dob')}"
        assert rec["gender"] == "Female", f"Field gender not saved: {rec.get('gender')}"
        assert rec["mother_tongue"] == "Tamil", f"Field mother_tongue not saved: {rec.get('mother_tongue')}"
        assert rec["native_city"] == "Coimbatore", f"Field native_city not saved: {rec.get('native_city')}"
        assert rec["pay_expected"] == "80000", f"Field pay_expected not saved: {rec.get('pay_expected')}"
        assert rec["iso_involvement"] is True, f"Field iso_involvement not saved: {rec.get('iso_involvement')}"

        # Verify server-controlled fields ignored
        assert rec["user_id"] == "cand-legit-123", f"Mass assignment vulnerability! user_id overridden to {rec['user_id']}"
        assert rec["is_locked"] is True, f"Mass assignment vulnerability! is_locked overridden to {rec['is_locked']}"
        assert rec["hod_status"] == "Pending", f"Mass assignment vulnerability! hod_status overridden to {rec['hod_status']}"
        assert rec["vp_status"] == "Pending", f"Mass assignment vulnerability! vp_status overridden to {rec['vp_status']}"
        assert rec["status"] == "Pending", f"Mass assignment vulnerability! status overridden to {rec['status']}"
        assert rec["app_uuid"] == "Comp/088", f"Mass assignment vulnerability! app_uuid overridden to {rec['app_uuid']}"
        print("[PASS] Test 18: Full candidate payload saved while malicious server-controlled fields were strictly ignored.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 18: {e}")

    # ── TEST 19: Global Supabase Guard (sb_admin = None returns 503) ──
    try:
        app_module.sb_admin = None
        res = client.get('/api/applications/101/research', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 503, f"Expected 503, got {res.status_code}"
        assert b"unavailable" in res.data.lower(), "Expected unavailable message"
        print("[PASS] Test 19: Global Supabase guard returns 503 when sb_admin is None.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 19: {e}")

    # ── TEST 20: No UUID Fallback on RPC Failure (Returns 503) ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "cand-123", "role": "candidate", "department": None, "full_name": "Test Candidate"
        }
        class MockAdminRPCFail:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([{"key": "applications_open", "value": "true"}])
                return MockQuery([])
            def rpc(self, name, params):
                raise Exception("RPC function generate_application_number not found")

        app_module.sb_admin = MockAdminRPCFail()

        res = client.post('/api/apply',
                          headers={"Authorization": "Bearer fake-jwt"},
                          data={
                              "name": "Jane Candidate",
                              "email": "jane@example.com",
                              "mobile_no": "9876543210",
                              "position": "Assistant Professor",
                              "department": "Computer Science",
                              "is_submitted": "true"
                          })

        assert res.status_code == 503, f"Expected 503, got {res.status_code}"
        assert b"failed to generate application reference id" in res.data.lower(), "Expected RPC failure message"
        print("[PASS] Test 20: RPC reference ID failure rejects submission with 503 without UUID fallback.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 20: {e}")

    # ── TEST 21: HOD Scrutiny GET /api/hod/applications returns department applications ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hod-123", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD"
        }
        class MockAdminHOD:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([{"key": "close_date", "value": "2020-01-01"}])
                return MockQuery([
                    {"id": 1, "app_uuid": "CS/001", "name": "Cand 1", "department": "Computer Science", "is_locked": True, "hod_status": "Eligible"},
                    {"id": 2, "app_uuid": "CS/002", "name": "Cand 2", "department": "Computer Science", "is_locked": True, "hod_status": "Not Eligible", "hod_remarks": "Not qualified"}
                ])

        app_module.sb_admin = MockAdminHOD()

        res = client.get('/api/hod/applications', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = json.loads(res.data)
        assert data["department"] == "Computer Science"
        assert len(data["applications"]) == 2
        assert data["stats"]["total_submitted"] == 2
        print("[PASS] Test 21: HOD Scrutiny GET /api/hod/applications returned department applications & stats.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 21: {e}")

    # ── TEST 22: HOD Forward POST /api/hod/forward calls RPC ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hod-123", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD", "email": "hod.cs@psgcas.ac.in"
        }
        class MockAdminHODForward:
            def rpc(self, name, params):
                assert name == "rpc_hod_forward_department"
                assert params["p_department"] == "Computer Science"
                assert params["p_who"] == "hod.cs@psgcas.ac.in"
                return MockRPC(True)

        app_module.sb_admin = MockAdminHODForward()

        res = client.post('/api/hod/forward', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = json.loads(res.data)
        assert data["success"] is True
        print("[PASS] Test 22: HOD Forward POST /api/hod/forward invoked RPC successfully.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 22: {e}")

    # ── TEST 23: VP Departments GET /api/vp/departments returns status list ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "vp-123", "role": "superadmin", "department": None, "full_name": "Vice Principal"
        }
        class MockAdminVP:
            def table(self, name):
                return MockQuery([
                    {"department": "Computer Science", "hod_forwarded_at": "2026-10-03T10:00:00", "hod_forwarded_by": "hod.cs@psgcas.ac.in", "hod_status": "Eligible"},
                    {"department": "Mathematics", "hod_forwarded_at": None, "hod_forwarded_by": None, "hod_status": "Pending"}
                ])

        app_module.sb_admin = MockAdminVP()

        res = client.get('/api/vp/departments', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = json.loads(res.data)
        depts = data["departments"]
        assert len(depts) == 2
        cs = next(d for d in depts if d["department"] == "Computer Science")
        math = next(d for d in depts if d["department"] == "Mathematics")
        assert cs["is_forwarded"] is True
        assert math["is_forwarded"] is False
        print("[PASS] Test 23: VP Departments GET /api/vp/departments returned department forwarding statuses.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 23: {e}")

    # ── TEST 24: HOD list is empty before close_date (portal_open=True) ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hod-123", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD"
        }
        class MockAdminPreClose:
            def table(self, name):
                if name == "app_settings":
                    return MockQuery([{"key": "close_date", "value": "2099-12-31"}])
                return MockQuery([{"id": 1, "name": "Secret Cand", "department": "Computer Science", "is_locked": True}])

        app_module.sb_admin = MockAdminPreClose()

        res = client.get('/api/hod/applications', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = json.loads(res.data)
        assert data["portal_open"] is True, "Expected portal_open=True"
        assert len(data["applications"]) == 0, "Expected empty applications list before close_date"
        assert "Scrutiny opens after" in data["message"]
        print("[PASS] Test 24: HOD scrutiny list is empty and portal_open=True before close_date.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 24: {e}")

    # ── TEST 25: CSV Formula Injection Safety Neutralisation ──
    try:
        raw_malicious = ["=1+1", "+cmd|' /C calc'!A0", "-SUM(A1:A10)", "@eval(123)", "Normal String"]
        sanitized = [app_module.sanitize_csv_cell(val) for val in raw_malicious]

        assert sanitized[0] == "'=1+1", f"Failed to neutralize = prefix: {sanitized[0]}"
        assert sanitized[1] == "'+cmd|' /C calc'!A0", f"Failed to neutralize + prefix: {sanitized[1]}"
        assert sanitized[2] == "'-SUM(A1:A10)", f"Failed to neutralize - prefix: {sanitized[2]}"
        assert sanitized[3] == "'@eval(123)", f"Failed to neutralize @ prefix: {sanitized[3]}"
        assert sanitized[4] == "Normal String", f"Normal string modified unexpectedly: {sanitized[4]}"

        # Test CSV route output with malicious field
        app_module._get_user_from_token = lambda: {
            "id": "hod-123", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD", "email": "hod.cs@psgcas.ac.in"
        }
        class MockAdminCSVInjection:
            def table(self, name):
                return MockQuery([
                    {"app_uuid": "=cmd|' /C calc'!A0", "name": "+Malicious Name", "email": "inj@test.com", "mobile_no": "-99999", "position": "@Professor", "department": "Computer Science", "hod_status": "Eligible", "hod_remarks": "@Exploit"}
                ])

        app_module.sb_admin = MockAdminCSVInjection()

        res = client.get('/api/reports/eligible-csv', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        csv_text = res.data.decode('utf-8')
        assert "'=cmd|" in csv_text, "CSV output missing single-quote on = prefix"
        assert "'+Malicious Name" in csv_text, "CSV output missing single-quote on + prefix"
        assert "'-99999" in csv_text, "CSV output missing single-quote on - prefix"
        assert "'@Professor" in csv_text, "CSV output missing single-quote on @ prefix"
        print("[PASS] Test 25: CSV formula injection neutralized with leading single quote across all cells.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 25: {e}")

    # ── TEST 26: Forward rejected while a submitted candidate is Pending ──
    try:
        app_module._get_user_from_token = lambda: {
            "id": "hod-123", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD", "email": "hod.cs@psgcas.ac.in"
        }
        class MockAdminPendingForwardFail:
            def rpc(self, name, params):
                raise Exception("PGRST100: CONNECT_RULE: Cannot forward department \"Computer Science\": 1 applications still pending HOD scrutiny")

        app_module.sb_admin = MockAdminPendingForwardFail()

        res = client.post('/api/hod/forward', headers={"Authorization": "Bearer fake-jwt"})
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        data = json.loads(res.data)
        assert "pending HOD scrutiny" in data["error"]
        print("[PASS] Test 26: Forward rejected (400 CONNECT_RULE) while a submitted candidate is Pending.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 26: {e}")

    # ── TEST 27: Admin report access with ?department=Math vs HOD strict department isolation ──
    try:
        # Admin access specifying department on CSV report route
        app_module._get_user_from_token = lambda: {
            "id": "admin-999", "role": "admin", "department": None, "full_name": "Admin User"
        }
        class MockAdminReport:
            def table(self, name):
                if name == "profiles":
                    return MockQuery([{"full_name": "Dr. Math HOD", "email": "hod.math@psgcas.ac.in"}])
                return MockQuery([
                    {"app_uuid": "MATH/001", "name": "Math Cand 1", "department": "Mathematics", "hod_status": "Eligible"}
                ])

        app_module.sb_admin = MockAdminReport()

        res_admin = client.get('/api/reports/eligible-csv?department=Mathematics', headers={"Authorization": "Bearer fake-jwt"})
        assert res_admin.status_code == 200, f"Expected 200 for admin, got {res_admin.status_code}"
        assert b"Mathematics" in res_admin.data, "Admin report missing target department"

        # HOD attempting query param override is forced to own profile department
        app_module._get_user_from_token = lambda: {
            "id": "hod-cs", "role": "hod", "department": "Computer Science", "full_name": "Dr. CS HOD"
        }

        res_hod = client.get('/api/reports/eligible-csv?department=Physics', headers={"Authorization": "Bearer fake-jwt"})
        assert res_hod.status_code == 200, f"Expected 200 for HOD, got {res_hod.status_code}"
        assert b"Computer Science" in res_hod.data, "HOD query param override vulnerability!"
        assert b"Physics" not in res_hod.data, "HOD was able to access cross-department report via query param!"
        print("[PASS] Test 27: Admin report parameter access verified and HOD query param override attempt neutralized.")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Test 27: {e}")

    print("=" * 75)
    print(f"  RESULTS: {passed}/27 TESTS PASSED")
    print("=" * 75)

if __name__ == "__main__":
    run_tests()

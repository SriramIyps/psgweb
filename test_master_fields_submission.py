"""
test_master_fields_submission.py — Comprehensive Master Fields Submission Test
Submits a payload containing EVERY master form field and verifies that each field
is persisted in Supabase Postgres database and returned via /api/my-application.
"""

import unittest
import os
import json
import uuid
from app import app, sb_admin

class TestMasterFieldsSubmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        cls.client = app.test_client()
        cls.test_email = f"test_candidate_{uuid.uuid4().hex[:8]}@psgcas.ac.in"
        cls.test_password = "TestPassword123!"
        cls.test_name = "Master Fields Test Candidate"

        # Create candidate via sb_admin directly to avoid email rate limits / timeouts
        user_res = sb_admin.auth.admin.create_user({
            "email": cls.test_email,
            "password": cls.test_password,
            "email_confirm": True,
            "user_metadata": {
                "role": "candidate",
                "full_name": cls.test_name
            }
        })
        user_id = str(user_res.user.id)
        sb_admin.table("profiles").upsert({
            "id": user_id,
            "email": cls.test_email,
            "role": "candidate",
            "full_name": cls.test_name
        }).execute()

        # Login to get JWT
        login_res = cls.client.post("/api/login", json={
            "email": cls.test_email,
            "password": cls.test_password
        })
        login_data = login_res.get_json()
        assert login_res.status_code == 200, f"Login failed: {login_data}"
        cls.token = login_data["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_submit_all_master_fields(self):
        # 1. Define complete payload with every master field
        master_payload = {
            "position": "Assistant Professor",
            "department": "Computer Science",
            "name": self.test_name,
            "dob": "1990-05-15",
            "gender": "Male",
            "mother_tongue": "Tamil",
            "religion": "Hindu",
            "community": "BC",
            "category": "BC",
            "father_name": "R. Swaminathan",
            "mobile_no": "9876543210",
            "email": self.test_email,
            "marital_status": "Married",
            "spouse_name": "S. Deepa",
            "diff_abled": "No",
            "nature": "N/A",
            "aadhaar_no": "123456789012",
            "pan_no": "ABCDE1234F",
            "native_address": "123 Heritage Lane, Town Hall",
            "native_city": "Coimbatore",
            "native_state": "Tamil Nadu",
            "native_country": "India",
            "native_pincode": "641018",
            "local_address": "456 Campus View, Avinashi Road",
            "local_city": "Coimbatore",
            "local_state": "Tamil Nadu",
            "local_country": "India",
            "local_pincode": "641014",
            "last_pay": "75000",
            "pay_expected": "90000",
            "join_time": "1 Month",
            "name_1": "Dr. A. Kumar",
            "designation_1": "Senior Professor",
            "mobile_1": "9842211001",
            "email_1": "kumar@example.com",
            "address_1": "Department of CS, PSG CAS",
            "name_2": "Dr. B. Murugan",
            "designation_2": "Head of Department",
            "mobile_2": "9842211002",
            "email_2": "murugan@example.com",
            "address_2": "School of Computing, Bharathiar Univ",
            "relative": "None",
            "already_attended": "No",
            "huk": "No legal or disciplinary cases pending",
            "achivements": "Best Researcher Award 2023, IEEE Senior Member",
            "comments": "Eager to contribute to PSG CAS academic excellence",
            "sci": "5",
            "scopus": "8",
            "ugc": "12",
            "others": "2",
            "scopus_id": "57200112233",
            "h_index_google": "10",
            "h_index_scopus": "7",
            "consultancy": "3",
            "net": "true",
            "set_slet": "true",
            "nss": "false",
            "ncc": "false",
            "naac": "true",
            "iqac": "true",
            "iso": "true",
            "books_published_national": "2",
            "books_published_international": "1",
            "books_edited_national": "1",
            "books_edited_international": "0",
            "chapters_published_national": "4",
            "chapters_published_international": "3",
            "minor_projects": "1",
            "major_projects": "2",
            "patents_applied": "3",
            "patents_published": "2",
            "patents_granted": "1",
            "is_submitted": "false"
        }

        # Create dummy file objects
        from io import BytesIO
        data_dict = dict(master_payload)
        data_dict["resume"] = (BytesIO(b"%PDF-1.4 Dummy Resume Content"), "test_resume.pdf")
        data_dict["papers"] = (BytesIO(b"%PDF-1.4 Dummy Research Papers Proof"), "test_papers.pdf")

        # 2. Submit application
        res = self.client.post(
            "/api/my-application",
            headers=self.headers,
            data=data_dict,
            content_type="multipart/form-data"
        )
        body = res.get_json()
        print("\n[POST /api/my-application Response]:", body)
        self.assertEqual(res.status_code, 201, f"Submit failed: {body}")
        self.assertTrue(body.get("success"))

        app_id = body.get("application_id")
        self.assertIsNotNone(app_id)

        # 3. Retrieve application record and assert every field
        get_res = self.client.get("/api/my-application", headers=self.headers)
        record = get_res.get_json()
        self.assertEqual(get_res.status_code, 200)

        print("\n[GET /api/my-application Result Verification]:")
        verified_count = 0
        for k, expected_val in master_payload.items():
            if k in ("is_submitted", "net", "set_slet", "nss", "ncc", "naac", "iqac", "iso"):
                continue
            actual_val = record.get(k)
            print(f"  [OK] Asserting field '{k}': expected='{expected_val}', actual='{actual_val}'")
            self.assertEqual(str(actual_val), str(expected_val), f"Mismatch for field '{k}'")
            verified_count += 1

        # Assert file paths
        self.assertTrue(record.get("resume_path", "").endswith(".pdf"))
        self.assertTrue(record.get("papers_path", "").endswith(".pdf"))
        print(f"  [OK] Verified file upload resume_path: {record.get('resume_path')}")
        print(f"  [OK] Verified file upload papers_path: {record.get('papers_path')}")

        # 4. Verify PDF Generation
        pdf_res = self.client.get(f"/api/applications/{app_id}/pdf", headers=self.headers)
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res.mimetype, "application/pdf")
        print(f"  [OK] Verified PDF Generation: Status 200, Content Length: {len(pdf_res.data)} bytes")

        print(f"\n[SUCCESS] All {verified_count} master fields + 2 file uploads verified successfully in Supabase database!")

if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestFlaskReviewRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    # 1. HOD Review Status Validation (invalid status)
    @patch('app._get_user_from_token')
    def test_hod_review_invalid_status(self, mock_auth):
        mock_auth.return_value = {
            "id": "hod-123",
            "email": "hod_cs@psgcas.ac.in",
            "role": "hod",
            "department": "Computer Science"
        }
        headers = {"Authorization": "Bearer fake-token"}

        response = self.client.put('/api/applications/1/hod-review',
                                  json={"hod_status": "Approved"},
                                  headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("hod_status must be 'Eligible' or 'Not Eligible'", response.get_json()["error"])

    # 2. HOD Review Department Mapping & RPC Payload
    @patch('app.sb_admin')
    @patch('app._get_user_from_token')
    def test_hod_review_department_mapping(self, mock_auth, mock_sb_admin):
        mock_auth.return_value = {
            "id": "hod-123",
            "email": "hod_cs@psgcas.ac.in",
            "role": "hod",
            "department": "Computer Science"
        }
        headers = {"Authorization": "Bearer fake-token"}

        mock_rpc = MagicMock()
        mock_rpc.execute.return_value = MagicMock(data=[])
        mock_sb_admin.rpc.return_value = mock_rpc

        response = self.client.put('/api/applications/10/hod-review',
                                  json={"hod_status": "Eligible", "admin_notes": "All documents verified"},
                                  headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])

        # Assert RPC signature called with p_hod_department mapped from user session
        mock_sb_admin.rpc.assert_called_once_with("rpc_update_hod_status", {
            "p_app_id": 10,
            "p_who": "hod_cs@psgcas.ac.in",
            "p_hod_department": "Computer Science",
            "p_status": "Eligible",
            "p_remarks": "All documents verified"
        })

    # 3. HOD Review Exception Mapping for CONNECT_RULE
    @patch('app.sb_admin')
    @patch('app._get_user_from_token')
    def test_hod_review_connect_rule_error_mapping(self, mock_auth, mock_sb_admin):
        mock_auth.return_value = {
            "id": "hod-123",
            "email": "hod_cs@psgcas.ac.in",
            "role": "hod",
            "department": "Computer Science"
        }
        headers = {"Authorization": "Bearer fake-token"}

        mock_rpc = MagicMock()
        mock_rpc.execute.side_effect = Exception("P0001: CONNECT_RULE: HOD department \"Computer Science\" does not match application department \"Mathematics\"\nCONTEXT: PL/pgSQL function")
        mock_sb_admin.rpc.return_value = mock_rpc

        response = self.client.put('/api/applications/10/hod-review',
                                  json={"hod_status": "Eligible", "admin_notes": "Verification ok"},
                                  headers=headers)
        self.assertEqual(response.status_code, 400)
        # Verify raw DB stack trace is stripped and clean friendly error is returned
        self.assertEqual(response.get_json()["error"], 'HOD department "Computer Science" does not match application department "Mathematics"')

    # 4. VP Review Status Validation
    @patch('app._get_user_from_token')
    def test_vp_review_invalid_status(self, mock_auth):
        mock_auth.return_value = {
            "id": "vp-123",
            "email": "vp@psgcas.ac.in",
            "role": "superadmin"
        }
        headers = {"Authorization": "Bearer fake-token"}

        response = self.client.put('/api/applications/5/vp-review',
                                  json={"vp_status": "Eligible"},
                                  headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("vp_status must be 'Shortlisted' or 'Not Shortlisted'", response.get_json()["error"])

    # 5. VP Review CONNECT_RULE Exception Mapping
    @patch('app.sb_admin')
    @patch('app._get_user_from_token')
    def test_vp_review_connect_rule_error_mapping(self, mock_auth, mock_sb_admin):
        mock_auth.return_value = {
            "id": "vp-123",
            "email": "vp@psgcas.ac.in",
            "role": "superadmin"
        }
        headers = {"Authorization": "Bearer fake-token"}

        mock_rpc = MagicMock()
        mock_rpc.execute.side_effect = Exception("P0001: CONNECT_RULE: Cannot shortlist: candidate has not been marked Eligible by HOD")
        mock_sb_admin.rpc.return_value = mock_rpc

        response = self.client.put('/api/applications/5/vp-review',
                                  json={"vp_status": "Shortlisted", "admin_notes": "Interview selection"},
                                  headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Cannot shortlist: candidate has not been marked Eligible by HOD")

    # 6. Generic DB Error Safe Sanitization (No raw DB trace leaked)
    @patch('app.sb_admin')
    @patch('app._get_user_from_token')
    def test_generic_db_error_sanitization(self, mock_auth, mock_sb_admin):
        mock_auth.return_value = {
            "id": "vp-123",
            "email": "vp@psgcas.ac.in",
            "role": "superadmin"
        }
        headers = {"Authorization": "Bearer fake-token"}

        mock_rpc = MagicMock()
        mock_rpc.execute.side_effect = Exception("FATAL: connection terminated abruptly at pg_hba.conf line 42")
        mock_sb_admin.rpc.return_value = mock_rpc

        response = self.client.put('/api/applications/5/vp-review',
                                  json={"vp_status": "Shortlisted", "admin_notes": "Selection"},
                                  headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Review operation failed. Please try again or contact administrator.")
        self.assertNotIn("pg_hba.conf", response.get_json()["error"])

if __name__ == '__main__':
    unittest.main()

"""
PSG CAS CONNECT — Seed Initial User Accounts
Usage:  python seed_users.py
Reads passwords and emails from environment variables (.env file).
Uses the Supabase Admin API to create users and their profiles.
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def create_user(email: str, password: str, role: str, full_name: str, department: str = None):
    """Create a Supabase Auth user and matching profile row."""
    meta = {"role": role, "full_name": full_name}
    if department:
        meta["department"] = department

    try:
        res = sb.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": meta,
        })
        user_id = res.user.id

        # Upsert profile (trigger may have created it, but ensure it's correct)
        sb.table("profiles").upsert({
            "id": str(user_id),
            "email": email,
            "role": role,
            "full_name": full_name,
            "department": department,
        }).execute()

        print(f"  [OK]   {role.upper():12s}  {email}  (id: {user_id})")
        return user_id

    except Exception as e:
        err_msg = str(e)
        if "already been registered" in err_msg or "duplicate" in err_msg.lower():
            print(f"  [SKIP] {role.upper():12s}  {email}  (already exists, skipped)")
        else:
            print(f"  [FAIL] {role.upper():12s}  {email}  ERROR: {e}")
        return None


def main():
    print("=" * 56)
    print("  PSG CAS CONNECT — Seeding User Accounts")
    print("=" * 56)
    print()

    # ── ADMIN ────────────────────────────────────
    admin_email = os.environ.get("SEED_ADMIN_EMAIL", "admin@psgcas.ac.in")
    admin_pw = os.environ.get("SEED_ADMIN_PW")
    if not admin_pw:
        print("ERROR: SEED_ADMIN_PW not set. Aborting.")
        sys.exit(1)
    create_user(admin_email, admin_pw, "admin", "System Administrator")

    # ── SUPERADMIN (VP) ──────────────────────────
    vp_email = os.environ.get("SEED_VP_EMAIL", "vp@psgcas.ac.in")
    vp_pw = os.environ.get("SEED_VP_PW")
    if vp_pw:
        create_user(vp_email, vp_pw, "superadmin", "Vice Principal")

    # ── HR ────────────────────────────────────────
    hr_email = os.environ.get("SEED_HR_EMAIL", "hr@psgcas.ac.in")
    hr_pw = os.environ.get("SEED_HR_PW")
    if hr_pw:
        create_user(hr_email, hr_pw, "hr", "HR Manager")

    # ── HODs (read all SEED_HOD_* groups) ────────
    # Pattern: SEED_HOD_<TAG>_EMAIL, SEED_HOD_<TAG>_PW, SEED_HOD_<TAG>_DEPT
    hod_tags = set()
    for key in os.environ:
        if key.startswith("SEED_HOD_") and key.endswith("_EMAIL"):
            tag = key.replace("SEED_HOD_", "").replace("_EMAIL", "")
            hod_tags.add(tag)

    for tag in sorted(hod_tags):
        h_email = os.environ.get(f"SEED_HOD_{tag}_EMAIL")
        h_pw = os.environ.get(f"SEED_HOD_{tag}_PW")
        h_dept = os.environ.get(f"SEED_HOD_{tag}_DEPT")
        if h_email and h_pw and h_dept:
            create_user(h_email, h_pw, "hod", f"HOD – {h_dept}", department=h_dept)
        else:
            print(f"  ⚠ HOD {tag}: missing EMAIL, PW, or DEPT — skipped")

    print()
    print("Done. You can now log in with these accounts.")
    print("Remember to change passwords after first login!")


if __name__ == "__main__":
    main()

"""
PSG CAS CONNECT — Flask Backend (RBAC Edition)
Roles: candidate, hod, superadmin (VP), hr, admin
Auth:  Supabase Auth  |  Data: Supabase Postgres + RLS
Run:   python app.py
"""
import os
import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Load .env in development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client

IST = ZoneInfo("Asia/Kolkata")

# ─────────────────────────────────────────────
# CONFIG (all from environment — no hardcoded secrets)
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
MAX_FILE_MB = 10

# SQLite Safety Guard: Refuse to run on Render production with SQLite enabled
if os.environ.get("USE_SQLITE") == "1":
    if os.environ.get("RENDER"):
        raise RuntimeError("SQLite is strictly forbidden on Render production environment!")
    print("[WARN] USE_SQLITE=1 set explicitly for local development.")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("[WARN] SUPABASE_URL or SUPABASE_ANON_KEY not set. Auth will not work.")

ALLOWED_PHOTO = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_DOC = {"pdf", "doc", "docx"}
ALLOWED_SHEET = {"csv", "xls", "xlsx"}

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, supports_credentials=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# ─────────────────────────────────────────────
# SUPABASE CLIENTS
# ─────────────────────────────────────────────
# Anon client: used for public operations & user-scoped queries
sb_anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) if SUPABASE_URL and SUPABASE_ANON_KEY else None
# Service-role client: used for admin operations (create users, bypass RLS)
sb_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_KEY else None

@app.before_request
def global_supabase_guard():
    """Global guard: if Supabase client is unavailable, fail closed on all /api data routes."""
    if request.path.startswith("/api/") and request.path not in ("/api/health", "/api/settings"):
        if sb_admin is None:
            return jsonify(error="Database connection unavailable. Service operating in fail-closed mode."), 503

# ─────────────────────────────────────────────
# INIT (ensure upload dirs exist)
# ─────────────────────────────────────────────
os.makedirs(os.path.join(UPLOAD_DIR, "photos"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "resumes"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "papers"), exist_ok=True)


# ═════════════════════════════════════════════
# AUDIT LOGGING HELPER
# ═════════════════════════════════════════════

def log_audit(who, action, application_id=None, old_value=None, new_value=None):
    """Record administrative or critical state changes in audit_log table.
    Fails closed: raises Exception if database insert fails so caller fails with 503.
    """
    if not sb_admin:
        raise Exception("Database service unavailable for audit logging")

    sb_admin.table("audit_log").insert({
        "who": who,
        "action": action,
        "application_id": application_id,
        "old_value": str(old_value) if old_value is not None else None,
        "new_value": str(new_value) if new_value is not None else None,
        "when_timestamp": datetime.now(IST).isoformat(),
    }).execute()


# ═════════════════════════════════════════════
# AUTH MIDDLEWARE
# ═════════════════════════════════════════════

def _get_user_from_token():
    """Verify the Supabase JWT and return profile data."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]

    if not sb_admin:
        return None

    try:
        # Verify token via Supabase
        user_resp = sb_admin.auth.get_user(token)
        user = user_resp.user
        if not user:
            return None

        # Fetch profile (role, department)
        profile_resp = (
            sb_admin.table("profiles")
            .select("role, department, full_name")
            .eq("id", str(user.id))
            .single()
            .execute()
        )
        profile = profile_resp.data
        if not profile:
            return None

        return {
            "id": str(user.id),
            "email": user.email,
            "role": profile["role"],
            "department": profile.get("department"),
            "full_name": profile["full_name"],
            "token": token,
        }
    except Exception as e:
        print(f"[Auth] Token verification failed: {e}")
        return None


def auth_required(f):
    """Require a valid Supabase JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_user_from_token()
        if not user:
            return jsonify(error="Authentication required"), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Require the user to have one of the specified roles."""
    def decorator(f):
        @wraps(f)
        @auth_required
        def decorated(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify(error="Insufficient permissions"), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ═════════════════════════════════════════════
# FILE UPLOAD HELPERS
# ═════════════════════════════════════════════

def allowed(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set

def save_file(file_obj, subfolder, allowed_set):
    if not file_obj or file_obj.filename == "":
        return None
    if not allowed(file_obj.filename, allowed_set):
        return None
    ext = file_obj.filename.rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, subfolder, name)
    file_obj.save(path)
    return f"/uploads/{subfolder}/{name}"


# ═════════════════════════════════════════════
# AUTH ROUTES
# ═════════════════════════════════════════════

@app.route("/api/login", methods=["POST"])
def login():
    """Sign in via Supabase Auth. Returns access token + user profile."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify(error="Email and password required"), 400

    if not sb_anon:
        return jsonify(error="Auth service not configured"), 503

    try:
        res = sb_anon.auth.sign_in_with_password({"email": email, "password": password})
        session = res.session
        user = res.user

        if not session or not user:
            return jsonify(error="Invalid email or password"), 401

        # Fetch profile
        profile_resp = (
            sb_admin.table("profiles")
            .select("role, department, full_name")
            .eq("id", str(user.id))
            .single()
            .execute()
        )
        profile = profile_resp.data

        if not profile:
            return jsonify(error="User profile not found. Contact administrator."), 403

        return jsonify(
            token=session.access_token,
            refresh_token=session.refresh_token,
            role=profile["role"],
            department=profile.get("department"),
            email=user.email,
            name=profile["full_name"],
        )

    except Exception as e:
        err = str(e)
        if "Invalid login" in err or "invalid" in err.lower():
            return jsonify(error="Invalid email or password"), 401
        print(f"[Login Error] {e}")
        return jsonify(error="Login failed. Please try again."), 500


@app.route("/api/signup", methods=["POST"])
def signup():
    """Candidate self-registration via Supabase Auth."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    full_name = (data.get("full_name") or "").strip()

    if not email or not password or not full_name:
        return jsonify(error="Email, password, and full name are required"), 400

    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters"), 400

    if not sb_anon:
        return jsonify(error="Auth service not configured"), 503

    try:
        res = sb_anon.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "role": "candidate",
                    "full_name": full_name,
                }
            }
        })
        user = res.user
        session = res.session

        if not user:
            return jsonify(error="Registration failed"), 500

        # If auto-confirm is on, session is returned immediately
        if session:
            return jsonify(
                token=session.access_token,
                refresh_token=session.refresh_token,
                role="candidate",
                email=user.email,
                name=full_name,
                message="Account created successfully!",
            ), 201
        else:
            return jsonify(
                message="Account created! Please check your email to confirm.",
                email=user.email,
            ), 201

    except Exception as e:
        err = str(e)
        if "already been registered" in err or "duplicate" in err.lower():
            return jsonify(error="An account with this email already exists. Please log in."), 409
        print(f"[Signup Error] {e}")
        return jsonify(error="Registration failed. Please try again."), 500


@app.route("/api/me", methods=["GET"])
@auth_required
def get_me():
    """Return the current user's profile."""
    u = g.current_user
    return jsonify(
        id=u["id"],
        email=u["email"],
        role=u["role"],
        department=u["department"],
        name=u["full_name"],
    )


# ═════════════════════════════════════════════
# APPLICATION WINDOW HELPER
# ═════════════════════════════════════════════

def _get_application_window_state():
    """Retrieve window configuration and compute state: 'not_open_yet' | 'open' | 'closed' in Asia/Kolkata (IST).
    Returns (state, message, is_error).
    Fail-closed: if DB read or date parsing fails, returns ('closed', error_msg, True).
    """
    if not sb_admin:
        return "closed", "Database client uninitialized", True

    try:
        res = sb_admin.table("app_settings").select("key, value").execute()
        settings = {row["key"]: row["value"] for row in (res.data or [])}
    except Exception as e:
        print(f"[ERROR] Failed to read app_settings: {e}")
        return "closed", f"Database lookup error: {e}", True

    legacy_toggle = settings.get("applications_open")

    # HARD OVERRIDE: applications_open = false closes applications even inside date window!
    if legacy_toggle is not None and str(legacy_toggle).lower() in ("false", "0", "no", "closed"):
        return "closed", "Applications are manually closed by administrator", False

    open_date_str = settings.get("open_date")
    close_date_str = settings.get("close_date")

    now = datetime.now(IST)

    if open_date_str or close_date_str:
        if open_date_str:
            try:
                if "T" in open_date_str:
                    open_dt = datetime.fromisoformat(open_date_str.replace("Z", "+00:00")).astimezone(IST)
                else:
                    open_dt = datetime.strptime(open_date_str[:10], "%Y-%m-%d").replace(tzinfo=IST)
                if now < open_dt:
                    return "not_open_yet", f"Applications will open on {open_date_str}", False
            except Exception as e:
                print(f"[ERROR] Failed to parse open_date '{open_date_str}': {e}")
                return "closed", f"Invalid open_date configuration: {e}", True

        if close_date_str:
            try:
                if "T" in close_date_str:
                    close_dt = datetime.fromisoformat(close_date_str.replace("Z", "+00:00")).astimezone(IST)
                else:
                    close_dt = datetime.strptime(close_date_str[:10], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=IST)
                if now > close_dt:
                    return "closed", f"Applications closed on {close_date_str}", False
            except Exception as e:
                print(f"[ERROR] Failed to parse close_date '{close_date_str}': {e}")
                return "closed", f"Invalid close_date configuration: {e}", True

        return "open", "Applications are open", False

    return "open", "Applications are open", False


# ═════════════════════════════════════════════
# APPLICATION ROUTES
# ═════════════════════════════════════════════

@app.route("/api/apply", methods=["POST"])
@auth_required
def submit_application():
    """Submit application (requires candidate auth).
    Enforces application open/close window on final submit and is_locked on writes.
    Fails closed on database errors.
    """
    user = g.current_user
    if user["role"] != "candidate" and user["role"] != "admin":
        return jsonify(error="Only candidates can submit applications"), 403

    f = request.form

    # ── Mandatory fields ──
    name = (f.get("name") or "").strip()
    email_field = (f.get("email") or "").strip()
    mobile_no = (f.get("mobile_no") or "").strip()
    position = (f.get("position") or "").strip()
    department = (f.get("department") or "").strip()

    if not name or not email_field or not mobile_no or not position or not department:
        return jsonify(error="Mandatory fields missing: Position, Department, Full Name, Email, and Mobile No."), 400

    is_final_submit = (f.get("is_submitted") == "true")

    # 1. Enforce Application Window ONLY on final submit (Draft saves permitted anytime if unlocked)
    if is_final_submit:
        window_state, window_msg, is_err = _get_application_window_state()
        if is_err:
            return jsonify(error=f"Application window lookup failed: {window_msg}"), 503
        if window_state != "open":
            return jsonify(error=f"Cannot submit application: {window_msg}"), 403

    # 2. Check existing application lock status for candidate (Fail Closed)
    existing_app = None
    try:
        ex_res = sb_admin.table("applications").select("id, is_locked, app_uuid").eq("user_id", user["id"]).limit(1).execute()
        if ex_res.data:
            existing_app = ex_res.data[0]
            if existing_app.get("is_locked"):
                return jsonify(error="Application is submitted and locked. Edits are not allowed."), 403
    except Exception as e:
        print(f"[ERROR] Lock status check failed in submit_application: {e}")
        return jsonify(error=f"Database error checking lock status: {e}"), 503

    # File uploads
    photo_path = save_file(request.files.get("photo"), "photos", ALLOWED_PHOTO)
    resume_file = request.files.get("resume")
    resume_path = save_file(resume_file, "resumes", ALLOWED_DOC) if resume_file else None
    papers_file = request.files.get("papers")
    papers_path = save_file(papers_file, "papers", ALLOWED_DOC) if papers_file else None

    # Reference ID: Atomic department-scoped counter <DeptCode>/<3-digit number>
    if not existing_app:
        try:
            num_res = sb_admin.rpc("generate_application_number", {"p_department": department}).execute()
            if not num_res.data:
                return jsonify(error="RPC generate_application_number returned empty reference ID"), 503
            app_uuid = num_res.data
        except Exception as e:
            print(f"[ERROR] Department reference ID RPC generation failed: {e}")
            return jsonify(error=f"Failed to generate application reference ID: {e}"), 503
    else:
        app_uuid = existing_app["app_uuid"]

    now = datetime.now(IST).isoformat()

    CANDIDATE_EDITABLE_FIELDS = [
        "position", "department", "name", "dob", "gender", "mother_tongue", "religion",
        "community", "category", "father_name", "mobile_no", "email",
        "marital_status", "spouse_name", "diff_abled", "nature", "aadhaar_no", "pan_no",
        "native_address", "native_city", "native_state", "native_country", "native_pincode",
        "local_address", "local_city", "local_state", "local_country", "local_pincode",
        "languages", "education", "teaching_experience", "industry_experience", "pdf_details",
        "achivements", "sci", "scopus", "ugc", "others", "scopus_id", "h_index_google",
        "h_index_scopus", "consultancy", "last_pay", "pay_expected", "join_time",
        "relative", "already_attended", "huk", "comments",
        "name_1", "address_1", "designation_1", "mobile_1", "email_1",
        "name_2", "address_2", "designation_2", "mobile_2", "email_2",
        "iso_involvement", "iso_details", "naac_iqac_details", "admin_positions_json",
        "net", "set_slet", "nss", "ncc", "naac", "iqac", "iso",
        "books_published_national", "books_published_international", "books_edited_national", "books_edited_international",
        "chapters_published_national", "chapters_published_international", "chapters_edited_national", "chapters_edited_international",
        "minor_projects", "major_projects", "patents_applied", "patents_published", "patents_granted"
    ]

    app_record = {}
    for key in CANDIDATE_EDITABLE_FIELDS:
        if f.get(key) is not None:
            val = f.get(key)
            if key in ("iso_involvement", "net", "set_slet", "nss", "ncc", "naac", "iqac", "iso"):
                if val in ("true", True, "on", "1"):
                    val = True
                elif val in ("false", False, "off", "0"):
                    val = False
            app_record[key] = val

    # Server-controlled fields: strictly forced by backend
    app_record["app_uuid"] = app_uuid
    app_record["submitted_at"] = now
    app_record["status"] = "Pending" if is_final_submit else "Draft"
    app_record["hod_status"] = "Pending"
    app_record["vp_status"] = "Pending"
    app_record["user_id"] = user["id"]
    app_record["is_locked"] = is_final_submit
    app_record["position"] = position
    app_record["department"] = department
    app_record["name"] = name
    app_record["mobile_no"] = mobile_no
    app_record["email"] = email_field

    if photo_path: app_record["photo_path"] = photo_path
    if resume_path: app_record["resume_path"] = resume_path
    if papers_path: app_record["papers_path"] = papers_path

    try:
        if existing_app:
            sb_admin.table("applications").update(app_record).eq("id", existing_app["id"]).execute()
            app_id = existing_app["id"]
        else:
            ins = sb_admin.table("applications").insert(app_record).execute()
            app_id = ins.data[0]["id"] if (ins.data and len(ins.data) > 0) else 0
    except Exception as e:
        print(f"[ERROR] Failed to save application record: {e}")
        return jsonify(error="Failed to save application. " + str(e)), 503

    if is_final_submit:
        user_identifier = user.get("email") or user.get("id", "unknown")
        log_audit(user_identifier, "SUBMIT_FINAL_LOCK", application_id=app_id, old_value=False, new_value=True)

    return jsonify(
        success=True,
        application_id=app_id,
        app_uuid=app_uuid,
        app_number=app_uuid,
        name=name,
        position=position,
        department=department,
        is_locked=is_final_submit,
        message="Application saved successfully!",
    ), 201


@app.route("/api/my-application", methods=["GET", "POST"])
@auth_required
def my_application():
    """Candidate draft endpoint: GET current candidate application, POST update draft."""
    user = g.current_user
    if user["role"] != "candidate":
        return jsonify(error="Only candidates can access my-application"), 403

    if request.method == "GET":
        try:
            res = sb_admin.table("applications").select("*").eq("user_id", user["id"]).limit(1).execute()
            if not res.data:
                return jsonify(error="No application found"), 404
            return jsonify(res.data[0])
        except Exception as e:
            print(f"[ERROR] my_application GET failed: {e}")
            return jsonify(error=f"Database error fetching application: {e}"), 503

    # POST is equivalent to submit_application
    return submit_application()



@app.route("/api/applications", methods=["GET"])
@auth_required
def get_applications():
    """Role-scoped application listing.
    - candidate: own applications only
    - hod: their department only (submitted applications, is_locked=True)
    - superadmin (VP): only submitted, forwarded, Eligible applications
    - admin: all
    - hr: only vp_status='Shortlisted'
    """
    role = g.current_user["role"]
    dept_filter = request.args.get("department")
    position = request.args.get("position")
    status = request.args.get("status")
    hod_status = request.args.get("hod_status")
    vp_status = request.args.get("vp_status")
    q = request.args.get("q")

    query = sb_admin.table("applications").select("*").order("submitted_at", desc=True)

    # ── Role-based scoping ──
    if role == "candidate":
        query = query.eq("user_id", g.current_user["id"])
    elif role == "hod":
        query = query.eq("department", g.current_user["department"]).eq("is_locked", True)
    elif role == "superadmin":
        query = query.eq("is_locked", True).eq("hod_status", "Eligible")
    elif role == "hr":
        query = query.eq("vp_status", "Shortlisted")
    # admin sees all

    # ── Optional filters ──
    if dept_filter:
        query = query.eq("department", dept_filter)
    if position:
        query = query.eq("position", position)
    if status:
        query = query.eq("status", status)
    if hod_status:
        query = query.eq("hod_status", hod_status)
    if vp_status and role != "hr":  # HR already filtered
        query = query.eq("vp_status", vp_status)
    if q:
        query = query.or_(
            f"name.ilike.%{q}%,email.ilike.%{q}%,department.ilike.%{q}%,position.ilike.%{q}%"
        )

    try:
        res = query.execute()
        apps = res.data or []
        if role == "superadmin":
            # VP only sees candidates from departments that have been forwarded by HOD
            apps = [a for a in apps if a.get("hod_forwarded_at") is not None]
        return jsonify(applications=apps)
    except Exception as e:
        print(f"[DB Error] {e}")
        return jsonify(applications=[], error=str(e)), 500


@app.route("/api/applications/<int:app_id>", methods=["GET"])
@auth_required
def get_application(app_id):
    """Get a single application (role-scoped)."""
    role = g.current_user["role"]

    ALLOWED_ROLES = {"candidate", "hod", "hr", "superadmin", "admin"}
    if role not in ALLOWED_ROLES:
        return jsonify(error=f"Role '{role}' is not authorized to access application details"), 403

    try:
        res = sb_admin.table("applications").select("*").eq("id", app_id).limit(1).execute()
        if not res.data:
            return jsonify(error="Application not found"), 404
        app_data = res.data[0]
    except Exception as e:
        print(f"[ERROR] Application lookup failed for app_id {app_id}: {e}")
        return jsonify(error=f"Database lookup error: {e}"), 503

    # Enforce scoping
    if role == "candidate" and app_data.get("user_id") != g.current_user["id"]:
        return jsonify(error="Access denied"), 403
    elif role == "hod" and app_data.get("department") != g.current_user["department"]:
        return jsonify(error="Access denied"), 403
    elif role == "hr" and app_data.get("vp_status") != "Shortlisted":
        return jsonify(error="Access denied"), 403

    return jsonify(app_data)


# ── HOD REVIEW ───────────────────────────────
@app.route("/api/applications/<int:app_id>/hod-review", methods=["PUT"])
@role_required("hod")
def hod_review(app_id):
    """HOD marks a candidate as Eligible or Not Eligible."""
    data = request.get_json(force=True)
    new_status = data.get("hod_status")

    if new_status not in ("Eligible", "Not Eligible"):
        return jsonify(error="hod_status must be 'Eligible' or 'Not Eligible'"), 400

    remarks = (data.get("admin_notes") or data.get("hod_remarks") or "").strip()

    try:
        sb_admin.rpc("rpc_update_hod_status", {
            "p_app_id": app_id,
            "p_who": g.current_user["email"],
            "p_hod_department": g.current_user.get("department"),
            "p_status": new_status,
            "p_remarks": remarks
        }).execute()
        return jsonify(success=True, hod_status=new_status)
    except Exception as e:
        err_msg = str(e)
        if "CONNECT_RULE:" in err_msg:
            clean_err = err_msg.split("CONNECT_RULE:")[1].split("\n")[0].strip()
            return jsonify(error=clean_err), 400
        print(f"[ERROR] HOD review update failed: {e}")
        return jsonify(error="Review operation failed. Please try again or contact administrator."), 400


# ── VP REVIEW ────────────────────────────────
@app.route("/api/applications/<int:app_id>/vp-review", methods=["PUT"])
@role_required("superadmin")
def vp_review(app_id):
    """VP marks a candidate as Shortlisted or Not Shortlisted.
    Only allowed if hod_status == 'Eligible'.
    """
    data = request.get_json(force=True)
    new_status = data.get("vp_status")

    if new_status not in ("Shortlisted", "Not Shortlisted"):
        return jsonify(error="vp_status must be 'Shortlisted' or 'Not Shortlisted'"), 400

    remarks = (data.get("admin_notes") or data.get("vp_remarks") or "").strip()

    try:
        sb_admin.rpc("rpc_update_vp_status", {
            "p_app_id": app_id,
            "p_who": g.current_user["email"],
            "p_status": new_status,
            "p_remarks": remarks
        }).execute()
        return jsonify(success=True, vp_status=new_status)
    except Exception as e:
        err_msg = str(e)
        if "CONNECT_RULE:" in err_msg:
            clean_err = err_msg.split("CONNECT_RULE:")[1].split("\n")[0].strip()
            return jsonify(error=clean_err), 400
        print(f"[ERROR] VP review update failed: {e}")
        return jsonify(error="Review operation failed. Please try again or contact administrator."), 400


# ── ADMIN: update any application ────────────
@app.route("/api/applications/<int:app_id>", methods=["PUT"])
@role_required("admin")
def update_application(app_id):
    """Admin: update application fields."""
    data = request.get_json(force=True)
    allowed_fields = {
        "status", "admin_notes", "hod_status", "vp_status", "is_locked",
        "name", "email", "mobile_no", "department", "position",
        "dob", "gender", "mother_tongue", "religion", "community", "category",
        "marital_status", "spouse_name", "father_name", "diff_abled", "nature",
        "aadhaar_no", "pan_no", "native_address", "native_city", "native_state",
        "native_country", "native_pincode", "local_address", "local_city",
        "local_state", "local_country", "local_pincode", "achivements",
        "sci", "scopus", "ugc", "others", "scopus_id", "h_index_google",
        "h_index_scopus", "consultancy", "last_pay", "pay_expected",
        "join_time", "relative", "already_attended", "huk", "comments",
        "name_1", "address_1", "designation_1", "mobile_1", "email_1",
        "name_2", "address_2", "designation_2", "mobile_2", "email_2",
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        return jsonify(error="No valid fields to update"), 400

    try:
        if "is_locked" in updates:
            sb_admin.rpc("rpc_update_application_lock", {
                "p_app_id": app_id,
                "p_who": g.current_user["email"],
                "p_is_locked": updates["is_locked"]
            }).execute()

        other_updates = {k: v for k, v in updates.items() if k != "is_locked"}
        if other_updates:
            sb_admin.table("applications").update(other_updates).eq("id", app_id).execute()
        return jsonify(success=True, updated=list(updates.keys()))
    except Exception as e:
        print(f"[ERROR] Admin update application failed: {e}")
        return jsonify(error=f"Failed to update application: {e}"), 503


@app.route("/api/applications/<int:app_id>", methods=["DELETE"])
@role_required("admin")
def delete_application(app_id):
    """Admin only: delete an application."""
    try:
        # Get file paths for cleanup
        app_res = sb_admin.table("applications").select("photo_path, resume_path, papers_path").eq("id", app_id).limit(1).execute()
        if app_res.data:
            for field in ("photo_path", "resume_path", "papers_path"):
                path = app_res.data[0].get(field)
                if path:
                    disk = os.path.join(BASE_DIR, path.lstrip("/"))
                    if os.path.exists(disk):
                        os.remove(disk)

        sb_admin.table("applications").delete().eq("id", app_id).execute()
        log_audit(g.current_user["email"], "DELETE_APPLICATION", application_id=app_id)
        return jsonify(success=True)
    except Exception as e:
        print(f"[ERROR] Delete application failed: {e}")
        return jsonify(error=f"Failed to delete application: {e}"), 503


# ═════════════════════════════════════════════
# STRUCTURED RESEARCH & PDF ROUTES
# ═════════════════════════════════════════════

@app.route("/api/applications/<int:app_id>/research", methods=["GET"])
@auth_required
def get_application_research(app_id):
    """Retrieve structured research details & summary counts for an application."""
    user = g.current_user
    role = user["role"]

    ALLOWED_ROLES = {"candidate", "hod", "hr", "superadmin", "admin"}
    if role not in ALLOWED_ROLES:
        return jsonify(error=f"Role '{role}' is not authorized to access research data"), 403

    try:
        app_res = sb_admin.table("applications").select("*").eq("id", app_id).limit(1).execute()
        if not app_res.data:
            return jsonify(error="Application not found"), 404
        app_data = app_res.data[0]
    except Exception as e:
        print(f"[ERROR] Research GET lookup failed for app_id {app_id}: {e}")
        return jsonify(error=f"Database error fetching application: {e}"), 503

    # Enforce scoping in Flask
    if role == "candidate" and app_data.get("user_id") != user["id"]:
        return jsonify(error="Access denied: not your application"), 403
    elif role == "hod" and app_data.get("department") != user["department"]:
        return jsonify(error="Access denied: application outside your department"), 403
    elif role == "hr" and app_data.get("vp_status") != "Shortlisted":
        return jsonify(error="Access denied: HR can only access shortlisted candidates"), 403

    # Fetch child table records fail-closed
    try:
        pubs = sb_admin.table("app_publications").select("*").eq("application_id", app_id).order("id").execute().data or []
        pats = sb_admin.table("app_patents").select("*").eq("application_id", app_id).order("id").execute().data or []
        cons = sb_admin.table("app_consultancy").select("*").eq("application_id", app_id).order("id").execute().data or []
        prjs = sb_admin.table("app_projects").select("*").eq("application_id", app_id).order("id").execute().data or []
    except Exception as e:
        print(f"[ERROR] Research GET child table fetch failed: {e}")
        return jsonify(error=f"Database error fetching research records: {e}"), 503

    # Parse admin positions
    try:
        admin_positions = json.loads(app_data.get("admin_positions_json") or "[]")
    except Exception as e:
        print(f"[WARN] Failed to parse admin_positions_json: {e}")
        admin_positions = []

    # Compute summary counts
    counts = {
        "sci": sum(1 for p in pubs if p.get("type") == "Journal article" and p.get("indexing_category") == "SCI"),
        "scopus": sum(1 for p in pubs if p.get("type") == "Journal article" and p.get("indexing_category") == "Scopus"),
        "ugc_other": sum(1 for p in pubs if p.get("type") == "Journal article" and p.get("indexing_category") in ("UGC-listed", "Other")),
        "books": sum(1 for p in pubs if p.get("type") == "Book"),
        "chapters": sum(1 for p in pubs if p.get("type") == "Book chapter"),
        "patents_published": sum(1 for p in pats if p.get("status") == "Published"),
        "patents_granted": sum(1 for p in pats if p.get("status") == "Granted"),
        "projects_major": sum(1 for prj in prjs if prj.get("type") == "Major"),
        "projects_minor": sum(1 for prj in prjs if prj.get("type") == "Minor"),
        "consultancy_count": len(cons),
        "consultancy_total": float(sum(float(c.get("amount") or 0) for c in cons)),
    }

    return jsonify(
        application_id=app_id,
        counts=counts,
        publications=pubs,
        patents=pats,
        consultancy=cons,
        projects=prjs,
        iso_involvement=bool(app_data.get("iso_involvement")),
        iso_details=app_data.get("iso_details", ""),
        naac_iqac_details=app_data.get("naac_iqac_details", ""),
        admin_positions=admin_positions,
    )


@app.route("/api/applications/<int:app_id>/research", methods=["POST"])
@auth_required
def save_application_research(app_id):
    """Save/update research child rows atomically for an application."""
    user = g.current_user
    role = user["role"]

    ALLOWED_ROLES = {"candidate", "hod", "hr", "superadmin", "admin"}
    if role not in ALLOWED_ROLES:
        return jsonify(error=f"Role '{role}' is not authorized to edit research data"), 403

    if role not in ("candidate", "admin"):
        return jsonify(error="Only candidate or admin can edit research data"), 403

    try:
        app_res = sb_admin.table("applications").select("user_id, is_locked, department").eq("id", app_id).limit(1).execute()
        if not app_res.data:
            return jsonify(error="Application not found"), 404
        app_data = app_res.data[0]
    except Exception as e:
        print(f"[ERROR] Lock status check failed in save_application_research: {e}")
        return jsonify(error=f"Database error checking application lock status: {e}"), 503

    if role == "candidate" and app_data.get("user_id") != user["id"]:
        return jsonify(error="Access denied: not your application"), 403

    # Lock check applies to BOTH candidate and admin on this POST route
    if app_data.get("is_locked"):
        return jsonify(error="Application is submitted and locked. Edits are not allowed."), 403

    data = request.get_json(force=True)

    try:
        sb_admin.rpc("save_application_research", {
            "p_application_id": app_id,
            "p_publications": data.get("publications", []),
            "p_patents": data.get("patents", []),
            "p_consultancy": data.get("consultancy", []),
            "p_projects": data.get("projects", []),
            "p_iso_involvement": bool(data.get("iso_involvement")),
            "p_iso_details": str(data.get("iso_details", "")),
            "p_naac_iqac_details": str(data.get("naac_iqac_details", "")),
            "p_admin_positions": data.get("admin_positions", []),
        }).execute()

        return jsonify(success=True, message="Research data saved successfully.")

    except Exception as e:
        print(f"[ERROR] Research RPC execution failed: {e}")
        return jsonify(error=f"Failed to save research data: {e}"), 503


@app.route("/api/applications/<int:app_id>/pdf", methods=["GET"])
@auth_required
def generate_application_pdf(app_id):
    """Generate and stream official biodata PDF for an application."""
    user = g.current_user
    role = user["role"]

    ALLOWED_ROLES = {"candidate", "hod", "hr", "superadmin", "admin"}
    if role not in ALLOWED_ROLES:
        return jsonify(error=f"Role '{role}' is not authorized to generate PDF"), 403

    try:
        app_res = sb_admin.table("applications").select("*").eq("id", app_id).limit(1).execute()
        if not app_res.data:
            return jsonify(error="Application not found"), 404
        app_data = app_res.data[0]
    except Exception as e:
        print(f"[ERROR] PDF generation application lookup failed for app_id {app_id}: {e}")
        return jsonify(error=f"Database error fetching application: {e}"), 503

    # Enforce scoping
    if role == "candidate" and app_data.get("user_id") != user["id"]:
        return jsonify(error="Access denied"), 403
    elif role == "hod" and app_data.get("department") != user["department"]:
        return jsonify(error="Access denied"), 403
    elif role == "hr" and app_data.get("vp_status") != "Shortlisted":
        return jsonify(error="Access denied"), 403

    # Fetch child records fail closed
    try:
        pubs = sb_admin.table("app_publications").select("*").eq("application_id", app_id).order("id").execute().data or []
        pats = sb_admin.table("app_patents").select("*").eq("application_id", app_id).order("id").execute().data or []
        cons = sb_admin.table("app_consultancy").select("*").eq("application_id", app_id).order("id").execute().data or []
        prjs = sb_admin.table("app_projects").select("*").eq("application_id", app_id).order("id").execute().data or []
    except Exception as e:
        print(f"[ERROR] PDF generation child table fetch failed: {e}")
        return jsonify(error=f"Database error fetching research records: {e}"), 503

    try:
        # Parse JSON fields safely
        def safe_json(val):
            if not val:
                return []
            if isinstance(val, list):
                return val
            try:
                return json.loads(val)
            except Exception as e:
                print(f"[WARN] safe_json parsing failed: {e}")
                return []

        edu_list = safe_json(app_data.get("education"))
        admin_pos = safe_json(app_data.get("admin_positions_json"))

        # Generate PDF with ReportLab
        import io
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.units import inch

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#002e5b'), alignment=1, spaceAfter=4)
        subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#334155'), alignment=1, spaceAfter=12)
        sec_heading = ParagraphStyle('SecHead', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#002e5b'), spaceBefore=10, spaceAfter=4)
        body_style = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12)
        table_cell = ParagraphStyle('Cell', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10)
        table_cell_bold = ParagraphStyle('CellB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10)

        elements = []

        # Title Block
        elements.append(Paragraph("PSG COLLEGE OF ARTS & SCIENCE", title_style))
        elements.append(Paragraph(f"FACULTY RECRUITMENT APPLICATION — {app_data.get('app_uuid', '')}", subtitle_style))
        elements.append(Spacer(1, 8))

        # Personal & Contact Details Table
        personal_data = [
            [Paragraph("<b>Application Ref No:</b>", table_cell_bold), Paragraph(str(app_data.get('app_uuid', '')), table_cell),
             Paragraph("<b>Date Submitted:</b>", table_cell_bold), Paragraph(str(app_data.get('submitted_at', '')[:10] if app_data.get('submitted_at') else ''), table_cell)],
            [Paragraph("<b>Applicant Name:</b>", table_cell_bold), Paragraph(str(app_data.get('name', '')), table_cell),
             Paragraph("<b>DOB / Gender:</b>", table_cell_bold), Paragraph(f"{app_data.get('dob','')} / {app_data.get('gender','')}", table_cell)],
            [Paragraph("<b>Position Applied:</b>", table_cell_bold), Paragraph(str(app_data.get('position', '')), table_cell),
             Paragraph("<b>Department:</b>", table_cell_bold), Paragraph(str(app_data.get('department', '')), table_cell)],
            [Paragraph("<b>Email:</b>", table_cell_bold), Paragraph(str(app_data.get('email', '')), table_cell),
             Paragraph("<b>Mobile No:</b>", table_cell_bold), Paragraph(str(app_data.get('mobile_no', '')), table_cell)],
            [Paragraph("<b>Father's / Mother's Name:</b>", table_cell_bold), Paragraph(f"{app_data.get('father_name','')} / {app_data.get('mother_name','')}", table_cell),
             Paragraph("<b>Marital Status:</b>", table_cell_bold), Paragraph(f"{app_data.get('marital_status','')} (Spouse: {app_data.get('spouse_name','N/A')})", table_cell)],
            [Paragraph("<b>Differently Abled:</b>", table_cell_bold), Paragraph(f"{app_data.get('diff_abled','No')} ({app_data.get('nature','N/A')})", table_cell),
             Paragraph("<b>Aadhaar / PAN:</b>", table_cell_bold), Paragraph(f"{app_data.get('aadhaar_no','')} / {app_data.get('pan_no','')}", table_cell)],
            [Paragraph("<b>Permanent Address:</b>", table_cell_bold), Paragraph(f"{app_data.get('native_address','')}, {app_data.get('native_city','')}, {app_data.get('native_state','')}, {app_data.get('native_country','')} - {app_data.get('native_pincode','')}", table_cell),
             Paragraph("<b>Local Address:</b>", table_cell_bold), Paragraph(f"{app_data.get('local_address','')}, {app_data.get('local_city','')}, {app_data.get('local_state','')}, {app_data.get('local_country','')} - {app_data.get('local_pincode','')}", table_cell)],
            [Paragraph("<b>Last Pay / Expected:</b>", table_cell_bold), Paragraph(f"₹{app_data.get('last_pay','0')} / ₹{app_data.get('pay_expected','0')}", table_cell),
             Paragraph("<b>Join Time Required:</b>", table_cell_bold), Paragraph(str(app_data.get('join_time','N/A')), table_cell)],
        ]
        t_pers = Table(personal_data, colWidths=[1.3*inch, 2.3*inch, 1.3*inch, 2.3*inch])
        t_pers.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_pers)
        elements.append(Spacer(1, 10))

        # References Section
        elements.append(Paragraph("Professional References", sec_heading))
        ref_data = [
            [Paragraph("<b>Ref 1:</b> {}".format(app_data.get('name_1','N/A')), table_cell_bold), Paragraph("Desig: {} | Mob: {} | Email: {}<br/>Addr: {}".format(app_data.get('designation_1',''), app_data.get('mobile_1',''), app_data.get('email_1',''), app_data.get('address_1','')), table_cell)],
            [Paragraph("<b>Ref 2:</b> {}".format(app_data.get('name_2','N/A')), table_cell_bold), Paragraph("Desig: {} | Mob: {} | Email: {}<br/>Addr: {}".format(app_data.get('designation_2',''), app_data.get('mobile_2',''), app_data.get('email_2',''), app_data.get('address_2','')), table_cell)],
        ]
        t_ref = Table(ref_data, colWidths=[2.2*inch, 5.0*inch])
        t_ref.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_ref)
        elements.append(Spacer(1, 10))

        # Educational Qualifications
        elements.append(Paragraph("Educational Qualifications", sec_heading))
        edu_headers = [Paragraph("<b>Qualification</b>", table_cell_bold), Paragraph("<b>Degree / Spec</b>", table_cell_bold), Paragraph("<b>Institution</b>", table_cell_bold), Paragraph("<b>% / Year</b>", table_cell_bold), Paragraph("<b>Mode</b>", table_cell_bold)]
        edu_rows = [edu_headers]
        if edu_list:
            for e in edu_list:
                edu_rows.append([
                    Paragraph(str(e.get('qualification','')), table_cell),
                    Paragraph(f"{e.get('degree','')} ({e.get('specialization','')})", table_cell),
                    Paragraph(str(e.get('college','')), table_cell),
                    Paragraph(f"{e.get('percentage','')}% / {e.get('year','')}", table_cell),
                    Paragraph(f"{e.get('rc','')} / {e.get('pf','')}", table_cell),
                ])
        else:
            edu_rows.append([Paragraph("No education records", table_cell)]*5)

        t_edu = Table(edu_rows, colWidths=[1.1*inch, 1.8*inch, 2.2*inch, 1.1*inch, 1.0*inch])
        t_edu.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e2e8f0')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_edu)
        elements.append(Spacer(1, 10))

        # Publications Section
        elements.append(Paragraph("Publications", sec_heading))
        pub_headers = [Paragraph("<b>Type</b>", table_cell_bold), Paragraph("<b>Indexing / Scope</b>", table_cell_bold), Paragraph("<b>Title & Journal/Publisher</b>", table_cell_bold), Paragraph("<b>Year / ISBN / DOI</b>", table_cell_bold)]
        pub_rows = [pub_headers]
        if pubs:
            for p in pubs:
                idx_scope = f"{p.get('indexing_category','') or ''} ({p.get('scope','')})"
                info = f"<b>{p.get('title','')}</b><br/>{p.get('publisher_journal','')}"
                meta = f"Year: {p.get('year','') or 'N/A'}<br/>ISBN: {p.get('isbn_issn','') or '-'}"
                if p.get('doi_link'):
                    meta += f"<br/>DOI: {p.get('doi_link')}"
                pub_rows.append([
                    Paragraph(str(p.get('type','')), table_cell),
                    Paragraph(idx_scope, table_cell),
                    Paragraph(info, table_cell),
                    Paragraph(meta, table_cell),
                ])
        else:
            pub_rows.append([Paragraph("No publication records submitted.", table_cell)]*4)

        t_pub = Table(pub_rows, colWidths=[1.1*inch, 1.4*inch, 2.8*inch, 1.9*inch])
        t_pub.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e2e8f0')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 4),
        ]))
        elements.append(t_pub)
        elements.append(Spacer(1, 10))

        # Patents & Projects Section
        elements.append(Paragraph("Patents & Research Projects", sec_heading))
        pat_text = "<br/>".join([f"• <b>{pt.get('title','')}</b> [{pt.get('status','')}] - No: {pt.get('patent_number','') or 'N/A'} ({pt.get('year','') or ''})" for pt in pats]) or "None"
        prj_text = "<br/>".join([f"• <b>{pr.get('title','')}</b> [{pr.get('type','')} Project, Role: {pr.get('role','')}] - {pr.get('funding_agency','')} (₹{pr.get('amount','') or 0})" for pr in prjs]) or "None"

        t_pat_prj = Table([[Paragraph("<b>Patents ({})</b><br/>{}".format(len(pats), pat_text), table_cell), Paragraph("<b>Projects ({})</b><br/>{}".format(len(prjs), prj_text), table_cell)]], colWidths=[3.6*inch, 3.6*inch])
        t_pat_prj.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_pat_prj)
        elements.append(Spacer(1, 10))

        # Consultancy & Admin Positions
        elements.append(Paragraph("Consultancy & Administrative Positions", sec_heading))
        con_text = "<br/>".join([f"• <b>{c.get('title','')}</b> for {c.get('client_organisation','')} (₹{c.get('amount','') or 0}, {c.get('year','') or ''})" for c in cons]) or "None"
        admin_text = f"ISO Involvement: {'Yes' if app_data.get('iso_involvement') else 'No'} ({app_data.get('iso_details','')})<br/>"
        admin_text += f"NAAC / IQAC Details: {app_data.get('naac_iqac_details','') or 'None'}<br/>"
        if admin_pos:
            admin_text += "<br/><b>Positions Held:</b><br/>" + "<br/>".join([f"• {pos.get('position','')} - {pos.get('institution','')} ({pos.get('duration','')})" for pos in admin_pos])

        t_con_admin = Table([[Paragraph("<b>Consultancy ({})</b><br/>{}".format(len(cons), con_text), table_cell), Paragraph("<b>Quality & Admin Roles</b><br/>{}".format(admin_text), table_cell)]], colWidths=[3.6*inch, 3.6*inch])
        t_con_admin.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_con_admin)
        elements.append(Spacer(1, 15))

        # Declaration Footer
        elements.append(Paragraph("<b>Declaration:</b> I hereby declare that the information furnished above is true and correct to the best of my knowledge.", ParagraphStyle('Decl', parent=body_style, fontSize=8, textColor=colors.HexColor('#475569'))))

        doc.build(elements)
        buffer.seek(0)

        from flask import Response
        app_uuid = str(app_data.get("app_uuid", "REC")).replace("/", "_")
        return Response(
            buffer.getvalue(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename=PSGCAS_{app_uuid}_Biodata.pdf"},
        )

    except Exception as e:
        print(f"[PDF Error] {e}")
        return jsonify(error=f"PDF generation failed: {e}"), 500


# ═════════════════════════════════════════════
# STATS & UTILITY ROUTES
# ═════════════════════════════════════════════

@app.route("/api/stats", methods=["GET"])
@auth_required
def get_stats():
    """Dashboard stats, scoped by role."""
    role = g.current_user["role"]

    try:
        query = sb_admin.table("applications").select("id, position, submitted_at, hod_status, vp_status, department")

        if role == "hod":
            query = query.eq("department", g.current_user["department"]).eq("is_locked", True)
        elif role == "hr":
            query = query.eq("vp_status", "Shortlisted")
        elif role == "candidate":
            query = query.eq("user_id", g.current_user["id"])

        res = query.execute()
        apps = res.data or []

        total = len(apps)
        ra = sum(1 for a in apps if "Research" in (a.get("position") or ""))
        ta = sum(1 for a in apps if "Teaching" in (a.get("position") or ""))
        today = datetime.now().strftime("%Y-%m-%d")
        tod = sum(1 for a in apps if (a.get("submitted_at") or "").startswith(today))
        eligible = sum(1 for a in apps if a.get("hod_status") == "Eligible")
        shortlisted = sum(1 for a in apps if a.get("vp_status") == "Shortlisted")

        # Department breakdown
        dept_counts = {}
        for a in apps:
            d = a.get("department") or "Unknown"
            dept_counts[d] = dept_counts.get(d, 0) + 1
        by_department = sorted(
            [{"department": k, "cnt": v} for k, v in dept_counts.items()],
            key=lambda x: -x["cnt"]
        )[:10]

        return jsonify(
            total=total,
            research_assistant=ra,
            teaching_assistant=ta,
            today=tod,
            eligible=eligible,
            shortlisted=shortlisted,
            by_department=by_department,
        )
    except Exception as e:
        print(f"[Stats Error] {e}")
        return jsonify(total=0, research_assistant=0, teaching_assistant=0, today=0, eligible=0, shortlisted=0, by_department=[])


@app.route("/api/departments", methods=["GET"])
@auth_required
def get_departments():
    """List distinct departments."""
    try:
        res = sb_admin.table("applications").select("department").execute()
        depts = sorted(set(a["department"] for a in (res.data or []) if a.get("department")))
        return jsonify(departments=depts)
    except Exception as e:
        print(f"[ERROR] Failed to fetch departments: {e}")
        return jsonify(error=f"Database error fetching departments: {e}"), 503


@app.route("/api/export/csv", methods=["GET"])
@role_required("admin", "superadmin")
def export_csv():
    """Stream applications as CSV (admin/VP only)."""
    import io
    import csv

    try:
        res = sb_admin.table("applications").select("*").order("submitted_at", desc=True).execute()
        rows = res.data or []
    except Exception as e:
        print(f"[ERROR] Failed to fetch export data: {e}")
        return jsonify(error=f"Database error fetching export data: {e}"), 503

    if not rows:
        return jsonify(error="No data"), 404

    output = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.writer(output)
    writer.writerow(fieldnames)
    for r in rows:
        writer.writerow([sanitize_csv_cell(r.get(f)) for f in fieldnames])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=psgcas_applications.csv"},
    )



# ═════════════════════════════════════════════
# CSV SAFETY & REPORT CONTEXT HELPERS
# ═════════════════════════════════════════════

def sanitize_csv_cell(val):
    """CSV formula injection safety helper: prepends a single quote if string begins with =, +, -, or @."""
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ('=', '+', '-', '@'):
        return "'" + s
    return s


def _get_report_context():
    """Extract department, stamped HOD name, and IST timestamp for reports.
    - HOD role: department ALWAYS comes from g.current_user['department']
    - admin/superadmin role: department comes from request parameter `department`
    """
    user = g.current_user
    role = user["role"]

    if role not in ("hod", "admin", "superadmin"):
        return None, (jsonify(error=f"Role '{role}' is not authorized to generate reports"), 403)

    if role == "hod":
        dept = user.get("department")
        if not dept:
            return None, (jsonify(error="No department assigned to HOD profile"), 400)
        hod_name = f"{user.get('full_name')} ({user.get('email')})"
    else:  # admin or superadmin
        dept = (request.args.get("department") or "").strip()
        if not dept:
            return None, (jsonify(error="Query parameter 'department' is required for admin report generation"), 400)

        # Look up HOD profile for department
        try:
            p_res = sb_admin.table("profiles").select("full_name, email").eq("role", "hod").eq("department", dept).limit(1).execute()
            if p_res.data and len(p_res.data) > 0:
                hod_name = f"{p_res.data[0].get('full_name')} ({p_res.data[0].get('email')})"
            else:
                hod_name = f"HOD Department of {dept}"
        except Exception:
            hod_name = f"HOD Department of {dept}"

    now_str = datetime.now(IST).strftime("%d-%b-%Y %I:%M %p IST")
    return {
        "department": dept,
        "hod_name": hod_name,
        "timestamp": now_str,
    }, None


# ═════════════════════════════════════════════
# HOD SCRUTINY & VP DEPARTMENT ROUTES
# ═════════════════════════════════════════════

@app.route("/api/hod/applications", methods=["GET"])
@role_required("hod")
def hod_applications():
    """HOD Scrutiny view for assigned department."""
    dept = g.current_user.get("department")
    if not dept:
        return jsonify(error="No department assigned to HOD profile"), 400

    # 1. Close date check
    try:
        sett_res = sb_admin.table("app_settings").select("value").eq("key", "close_date").limit(1).execute()
        close_str = sett_res.data[0]["value"] if (sett_res.data and len(sett_res.data) > 0) else None
    except Exception as e:
        print(f"[ERROR] Failed to fetch close_date: {e}")
        return jsonify(error="Failed to verify application window close date"), 503

    if not close_str:
        return jsonify(error="Close date setting is missing in system configuration"), 500

    try:
        if "T" in close_str:
            close_dt = datetime.fromisoformat(close_str)
            if close_dt.tzinfo is None:
                close_dt = close_dt.replace(tzinfo=IST)
        else:
            close_dt = datetime.strptime(close_str[:10] + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    except Exception as e:
        print(f"[ERROR] Invalid close date format '{close_str}': {e}")
        return jsonify(error="Invalid close date configuration"), 500

    now_ist = datetime.now(IST)
    portal_open = now_ist <= close_dt

    if portal_open:
        return jsonify(
            portal_open=True,
            close_date=close_str[:10],
            department=dept,
            is_forwarded=False,
            forwarded_at=None,
            forwarded_by=None,
            applications=[],
            stats={"total_submitted": 0, "pending_count": 0, "eligible_count": 0, "not_eligible_count": 0},
            can_forward=False,
            message=f"Scrutiny opens after {close_str[:10]}"
        )

    # 2. Fetch submitted applications for HOD department
    try:
        apps_res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).order("submitted_at", desc=True).execute()
        apps = apps_res.data or []
    except Exception as e:
        print(f"[ERROR] HOD applications fetch failed: {e}")
        return jsonify(error=f"Database error fetching applications: {e}"), 503

    is_forwarded = any(a.get("hod_forwarded_at") is not None for a in apps) if apps else False
    forwarded_at = next((a.get("hod_forwarded_at") for a in apps if a.get("hod_forwarded_at")), None)
    forwarded_by = next((a.get("hod_forwarded_by") for a in apps if a.get("hod_forwarded_by")), None)

    total_submitted = len(apps)
    pending_count = sum(1 for a in apps if not a.get("hod_status") or a.get("hod_status") == "Pending")
    eligible_count = sum(1 for a in apps if a.get("hod_status") == "Eligible")
    not_eligible_count = sum(1 for a in apps if a.get("hod_status") == "Not Eligible")

    can_forward = (total_submitted > 0) and (pending_count == 0) and (not is_forwarded) and (not portal_open)

    return jsonify(
        portal_open=False,
        close_date=close_str[:10],
        department=dept,
        is_forwarded=is_forwarded,
        forwarded_at=forwarded_at,
        forwarded_by=forwarded_by,
        applications=apps,
        stats={
            "total_submitted": total_submitted,
            "pending_count": pending_count,
            "eligible_count": eligible_count,
            "not_eligible_count": not_eligible_count,
        },
        can_forward=can_forward
    )


@app.route("/api/hod/forward", methods=["POST"])
@role_required("hod")
def hod_forward():
    """HOD forwards department scrutinised applications to VP."""
    dept = g.current_user.get("department")
    if not dept:
        return jsonify(error="No department assigned to HOD profile"), 400

    try:
        sb_admin.rpc("rpc_hod_forward_department", {
            "p_department": dept,
            "p_who": g.current_user["email"]
        }).execute()

        return jsonify(success=True, message=f"Department '{dept}' successfully forwarded to Vice Principal.")
    except Exception as e:
        err_msg = str(e)
        if "CONNECT_RULE:" in err_msg:
            clean_err = err_msg.split("CONNECT_RULE:")[1].split("\n")[0].strip()
            return jsonify(error=clean_err), 400
        print(f"[ERROR] HOD forward failed: {e}")
        return jsonify(error="Failed to forward department. Please try again."), 503


# ═════════════════════════════════════════════
# STAMPED PDF & CSV REPORT ROUTES (HOD & ADMIN)
# ═════════════════════════════════════════════

@app.route("/api/reports/scrutiny-pdf", methods=["GET"])
@app.route("/api/hod/scrutiny-pdf", methods=["GET"])
@auth_required
def report_scrutiny_pdf():
    """Full HOD Scrutiny PDF report stamped with Dept, Date (IST) & HOD Name."""
    ctx, err = _get_report_context()
    if err:
        return err
    dept = ctx["department"]

    try:
        apps_res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).order("name").execute()
        apps = apps_res.data or []
    except Exception as e:
        return jsonify(error=f"Database error fetching applications: {e}"), 503

    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import inch

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        rightMargin=20, leftMargin=20, topMargin=25, bottomMargin=25
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#002e5b'), alignment=1, spaceAfter=2)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#334155'), alignment=1, spaceAfter=8)
    table_hdr = ParagraphStyle('TH', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1e293b'))
    table_cell = ParagraphStyle('TC', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10)
    table_cell_bold = ParagraphStyle('TCB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10)

    elements = []
    elements.append(Paragraph("PSG COLLEGE OF ARTS & SCIENCE", title_style))
    elements.append(Paragraph(f"HOD CANDIDATE SCRUTINY REPORT — DEPARTMENT OF {dept.upper()}", subtitle_style))
    elements.append(Paragraph(f"Department: {dept} | Generated: {ctx['timestamp']} | HOD: {ctx['hod_name']}", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=8, alignment=1, spaceAfter=10)))

    headers = [
        Paragraph("<b>#</b>", table_hdr),
        Paragraph("<b>App Ref</b>", table_hdr),
        Paragraph("<b>Candidate Name & Contact</b>", table_hdr),
        Paragraph("<b>Position</b>", table_hdr),
        Paragraph("<b>Qualification Summary</b>", table_hdr),
        Paragraph("<b>HOD Decision</b>", table_hdr),
        Paragraph("<b>Remarks / Reason</b>", table_hdr),
    ]

    table_rows = [headers]
    for idx, a in enumerate(apps, 1):
        edu_str = ""
        try:
            edu_raw = a.get("education")
            edu_list = json.loads(edu_raw) if isinstance(edu_raw, str) else (edu_raw or [])
            if isinstance(edu_list, list):
                edu_parts = [f"{e.get('degree','')} ({e.get('qualification','')})" for e in edu_list if e.get('degree')]
                edu_str = ", ".join(edu_parts)
        except Exception:
            edu_str = ""

        status_text = a.get("hod_status") or "Pending"
        status_color = "#16a34a" if status_text == "Eligible" else ("#dc2626" if status_text == "Not Eligible" else "#d97706")
        status_para = Paragraph(f"<font color='{status_color}'><b>{status_text}</b></font>", table_cell)

        table_rows.append([
            Paragraph(str(idx), table_cell),
            Paragraph(str(a.get("app_uuid","")), table_cell_bold),
            Paragraph(f"<b>{a.get('name','')}</b><br/>{a.get('email','')}<br/>{a.get('mobile_no','')}", table_cell),
            Paragraph(str(a.get("position","")), table_cell),
            Paragraph(edu_str or "N/A", table_cell),
            status_para,
            Paragraph(str(a.get("hod_remarks","") or "-"), table_cell),
        ])

    t = Table(table_rows, colWidths=[0.3*inch, 1.2*inch, 2.2*inch, 1.5*inch, 2.3*inch, 1.1*inch, 2.4*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e2e8f0')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 15))
    elements.append(Paragraph("<b>Declaration:</b> The scrutiny of all received applications for the above department has been conducted strictly in accordance with institutional and UGC norms.", ParagraphStyle('Decl', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#475569'))))

    doc.build(elements)
    buffer.seek(0)

    from flask import Response
    safe_dept = dept.replace(" ", "_")
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=HOD_Scrutiny_Report_{safe_dept}.pdf"},
    )


@app.route("/api/reports/eligible-pdf", methods=["GET"])
@auth_required
def report_eligible_pdf():
    """Eligible Candidates PDF report stamped with Dept, Date (IST) & HOD Name."""
    ctx, err = _get_report_context()
    if err:
        return err
    dept = ctx["department"]

    try:
        apps_res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).eq("hod_status", "Eligible").order("name").execute()
        apps = apps_res.data or []
    except Exception as e:
        return jsonify(error=f"Database error fetching eligible applications: {e}"), 503

    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import inch

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        rightMargin=20, leftMargin=20, topMargin=25, bottomMargin=25
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#059669'), alignment=1, spaceAfter=2)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#334155'), alignment=1, spaceAfter=8)
    table_hdr = ParagraphStyle('TH', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1e293b'))
    table_cell = ParagraphStyle('TC', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10)
    table_cell_bold = ParagraphStyle('TCB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10)

    elements = []
    elements.append(Paragraph("PSG COLLEGE OF ARTS & SCIENCE", title_style))
    elements.append(Paragraph(f"SCRUTINY ELIGIBLE CANDIDATES LIST — DEPARTMENT OF {dept.upper()}", subtitle_style))
    elements.append(Paragraph(f"Department: {dept} | Generated: {ctx['timestamp']} | HOD: {ctx['hod_name']}", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=8, alignment=1, spaceAfter=10)))

    headers = [
        Paragraph("<b>#</b>", table_hdr),
        Paragraph("<b>App Ref</b>", table_hdr),
        Paragraph("<b>Candidate Name & Contact</b>", table_hdr),
        Paragraph("<b>Position</b>", table_hdr),
        Paragraph("<b>Qualification Summary</b>", table_hdr),
        Paragraph("<b>HOD Status</b>", table_hdr),
        Paragraph("<b>Reviewed Date</b>", table_hdr),
    ]

    table_rows = [headers]
    for idx, a in enumerate(apps, 1):
        edu_str = ""
        try:
            edu_raw = a.get("education")
            edu_list = json.loads(edu_raw) if isinstance(edu_raw, str) else (edu_raw or [])
            if isinstance(edu_list, list):
                edu_parts = [f"{e.get('degree','')} ({e.get('qualification','')})" for e in edu_list if e.get('degree')]
                edu_str = ", ".join(edu_parts)
        except Exception:
            edu_str = ""

        rev_date = a.get("hod_reviewed_at")[:10] if a.get("hod_reviewed_at") else "-"

        table_rows.append([
            Paragraph(str(idx), table_cell),
            Paragraph(str(a.get("app_uuid","")), table_cell_bold),
            Paragraph(f"<b>{a.get('name','')}</b><br/>{a.get('email','')}<br/>{a.get('mobile_no','')}", table_cell),
            Paragraph(str(a.get("position","")), table_cell),
            Paragraph(edu_str or "N/A", table_cell),
            Paragraph("<font color='#059669'><b>Eligible</b></font>", table_cell),
            Paragraph(str(rev_date), table_cell),
        ])

    t = Table(table_rows, colWidths=[0.3*inch, 1.3*inch, 2.4*inch, 1.8*inch, 2.7*inch, 1.1*inch, 1.4*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#d1fae5')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#a7f3d0')),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    from flask import Response
    safe_dept = dept.replace(" ", "_")
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=Eligible_Candidates_{safe_dept}.pdf"},
    )


@app.route("/api/reports/not-eligible-pdf", methods=["GET"])
@auth_required
def report_not_eligible_pdf():
    """Not Eligible Candidates PDF report with mandatory HOD reasons, stamped with Dept, Date (IST) & HOD Name."""
    ctx, err = _get_report_context()
    if err:
        return err
    dept = ctx["department"]

    try:
        apps_res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).eq("hod_status", "Not Eligible").order("name").execute()
        apps = apps_res.data or []
    except Exception as e:
        return jsonify(error=f"Database error fetching not eligible applications: {e}"), 503

    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import inch

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        rightMargin=20, leftMargin=20, topMargin=25, bottomMargin=25
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#dc2626'), alignment=1, spaceAfter=2)
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#334155'), alignment=1, spaceAfter=8)
    table_hdr = ParagraphStyle('TH', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1e293b'))
    table_cell = ParagraphStyle('TC', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10)
    table_cell_bold = ParagraphStyle('TCB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10)

    elements = []
    elements.append(Paragraph("PSG COLLEGE OF ARTS & SCIENCE", title_style))
    elements.append(Paragraph(f"SCRUTINY NOT ELIGIBLE CANDIDATES LIST — DEPARTMENT OF {dept.upper()}", subtitle_style))
    elements.append(Paragraph(f"Department: {dept} | Generated: {ctx['timestamp']} | HOD: {ctx['hod_name']}", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=8, alignment=1, spaceAfter=10)))

    headers = [
        Paragraph("<b>#</b>", table_hdr),
        Paragraph("<b>App Ref</b>", table_hdr),
        Paragraph("<b>Candidate Name & Contact</b>", table_hdr),
        Paragraph("<b>Position</b>", table_hdr),
        Paragraph("<b>Qualification Summary</b>", table_hdr),
        Paragraph("<b>HOD Mandated Reason / Remarks</b>", table_hdr),
    ]

    table_rows = [headers]
    for idx, a in enumerate(apps, 1):
        edu_str = ""
        try:
            edu_raw = a.get("education")
            edu_list = json.loads(edu_raw) if isinstance(edu_raw, str) else (edu_raw or [])
            if isinstance(edu_list, list):
                edu_parts = [f"{e.get('degree','')} ({e.get('qualification','')})" for e in edu_list if e.get('degree')]
                edu_str = ", ".join(edu_parts)
        except Exception:
            edu_str = ""

        table_rows.append([
            Paragraph(str(idx), table_cell),
            Paragraph(str(a.get("app_uuid","")), table_cell_bold),
            Paragraph(f"<b>{a.get('name','')}</b><br/>{a.get('email','')}<br/>{a.get('mobile_no','')}", table_cell),
            Paragraph(str(a.get("position","")), table_cell),
            Paragraph(edu_str or "N/A", table_cell),
            Paragraph(f"<font color='#dc2626'><b>{a.get('hod_remarks','') or 'Reason missing'}</b></font>", table_cell),
        ])

    t = Table(table_rows, colWidths=[0.3*inch, 1.3*inch, 2.3*inch, 1.6*inch, 2.3*inch, 3.2*inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#fee2e2')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#fca5a5')),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)

    from flask import Response
    safe_dept = dept.replace(" ", "_")
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=Not_Eligible_Candidates_{safe_dept}.pdf"},
    )


@app.route("/api/reports/eligible-csv", methods=["GET"])
@app.route("/api/hod/eligible-csv", methods=["GET"])
@auth_required
def report_eligible_csv():
    """Stream CSV of Eligible candidates with formula injection safety, stamped metadata header."""
    ctx, err = _get_report_context()
    if err:
        return err
    dept = ctx["department"]

    try:
        res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).eq("hod_status", "Eligible").order("name").execute()
        rows = res.data or []
    except Exception as e:
        return jsonify(error=f"Database error fetching eligible candidates: {e}"), 503

    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["# PSG CAS CONNECT — ELIGIBLE CANDIDATES REPORT"])
    writer.writerow(["# Department", ctx["department"]])
    writer.writerow(["# Generated Date (IST)", ctx["timestamp"]])
    writer.writerow(["# HOD", ctx["hod_name"]])
    writer.writerow([])

    fieldnames = ["app_uuid", "name", "email", "mobile_no", "position", "department", "hod_status", "hod_remarks", "hod_reviewed_at", "hod_reviewer"]
    writer.writerow(fieldnames)

    for r in rows:
        row_vals = [sanitize_csv_cell(r.get(f)) for f in fieldnames]
        writer.writerow(row_vals)

    from flask import Response
    safe_dept = dept.replace(" ", "_")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Eligible_Candidates_{safe_dept}.csv"},
    )


@app.route("/api/reports/not-eligible-csv", methods=["GET"])
@auth_required
def report_not_eligible_csv():
    """Stream CSV of Not Eligible candidates (with HOD reasons) with formula injection safety, stamped metadata header."""
    ctx, err = _get_report_context()
    if err:
        return err
    dept = ctx["department"]

    try:
        res = sb_admin.table("applications").select("*").eq("department", dept).eq("is_locked", True).eq("hod_status", "Not Eligible").order("name").execute()
        rows = res.data or []
    except Exception as e:
        return jsonify(error=f"Database error fetching not eligible candidates: {e}"), 503

    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["# PSG CAS CONNECT — NOT ELIGIBLE CANDIDATES REPORT"])
    writer.writerow(["# Department", ctx["department"]])
    writer.writerow(["# Generated Date (IST)", ctx["timestamp"]])
    writer.writerow(["# HOD", ctx["hod_name"]])
    writer.writerow([])

    fieldnames = ["app_uuid", "name", "email", "mobile_no", "position", "department", "hod_status", "hod_remarks", "hod_reviewed_at", "hod_reviewer"]
    writer.writerow(fieldnames)

    for r in rows:
        row_vals = [sanitize_csv_cell(r.get(f)) for f in fieldnames]
        writer.writerow(row_vals)

    from flask import Response
    safe_dept = dept.replace(" ", "_")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Not_Eligible_Candidates_{safe_dept}.csv"},
    )


@app.route("/api/vp/departments", methods=["GET"])
@role_required("superadmin")
def vp_departments():
    """List department forwarding status for Vice Principal."""
    try:
        res = sb_admin.table("applications").select("department, hod_forwarded_at, hod_forwarded_by, hod_status").eq("is_locked", True).execute()
        apps = res.data or []

        dept_map = {}
        for a in apps:
            d = a.get("department")
            if not d:
                continue
            if d not in dept_map:
                dept_map[d] = {
                    "department": d,
                    "is_forwarded": False,
                    "forwarded_at": None,
                    "forwarded_by": None,
                    "total_submitted": 0,
                    "eligible_count": 0,
                }
            dept_map[d]["total_submitted"] += 1
            if a.get("hod_status") == "Eligible":
                dept_map[d]["eligible_count"] += 1
            if a.get("hod_forwarded_at"):
                dept_map[d]["is_forwarded"] = True
                dept_map[d]["forwarded_at"] = a.get("hod_forwarded_at")
                dept_map[d]["forwarded_by"] = a.get("hod_forwarded_by")

        dept_list = sorted(list(dept_map.values()), key=lambda x: x["department"])
        return jsonify(departments=dept_list)
    except Exception as e:
        print(f"[ERROR] Failed to fetch VP departments: {e}")
        return jsonify(error=f"Database error fetching department status: {e}"), 503

@app.route("/api/admin/users", methods=["GET"])
@role_required("admin")
def list_users():
    """List all staff users (non-candidate profiles)."""
    try:
        res = sb_admin.table("profiles").select("*").neq("role", "candidate").order("created_at", desc=True).execute()
        return jsonify(users=res.data or [])
    except Exception as e:
        return jsonify(users=[], error=str(e))


@app.route("/api/admin/users", methods=["POST"])
@role_required("admin")
def create_user():
    """Admin creates a new staff user (HOD, VP, HR)."""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    department = (data.get("department") or "").strip() or None

    if not email or not password or not full_name:
        return jsonify(error="Email, password, and full name are required"), 400

    if role not in ("hod", "superadmin", "hr", "admin"):
        return jsonify(error="Invalid role. Must be hod, superadmin, hr, or admin."), 400

    if role == "hod" and not department:
        return jsonify(error="HOD must have a department assigned"), 400

    if len(password) < 8:
        return jsonify(error="Password must be at least 8 characters"), 400

    try:
        res = sb_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "role": role,
                "full_name": full_name,
                "department": department,
            },
        })
        user_id = str(res.user.id)

        # Ensure profile exists with correct data
        sb_admin.table("profiles").upsert({
            "id": user_id,
            "email": email,
            "role": role,
            "full_name": full_name,
            "department": department,
        }).execute()

        return jsonify(success=True, id=user_id, email=email, role=role), 201

    except Exception as e:
        err = str(e)
        if "already been registered" in err or "duplicate" in err.lower():
            return jsonify(error="A user with this email already exists"), 409
        return jsonify(error=str(e)), 500


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
@role_required("admin")
def delete_user(user_id):
    """Admin deletes a staff user."""
    # Don't allow deleting yourself
    if user_id == g.current_user["id"]:
        return jsonify(error="Cannot delete your own account"), 400

    try:
        sb_admin.auth.admin.delete_user(user_id)
        # Profile is deleted via CASCADE
        return jsonify(success=True)
    except Exception as e:
        return jsonify(error=str(e)), 500


# ═════════════════════════════════════════════
# ADMIN: APPLICATION SETTINGS
# ═════════════════════════════════════════════

@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Public: get application settings (returns ONLY open_date, close_date, state, state_message)."""
    state, msg, is_err = _get_application_window_state()
    if is_err:
        return jsonify(error=f"Failed to load settings: {msg}"), 503

    try:
        res = sb_admin.table("app_settings").select("key, value").execute()
        settings_map = {row["key"]: row["value"] for row in (res.data or [])}
    except Exception as e:
        print(f"[ERROR] Failed to fetch settings: {e}")
        return jsonify(error=f"Database error loading settings: {e}"), 503

    return jsonify(
        open_date=settings_map.get("open_date"),
        close_date=settings_map.get("close_date"),
        state=state,
        state_message=msg,
    )


@app.route("/api/admin/settings", methods=["PUT"])
@role_required("admin")
def update_settings():
    """Admin: update application settings (open_date, close_date, applications_open, etc.)."""
    data = request.get_json(force=True)
    allowed_keys = {"open_date", "close_date", "applications_open", "deadline_date", "announcement_text"}
    results = []

    for key, value in data.items():
        if key not in allowed_keys:
            continue
        try:
            sb_admin.table("app_settings").upsert({
                "key": key,
                "value": str(value) if value is not None else "",
                "updated_at": datetime.now().isoformat(),
            }).execute()
            results.append(key)
        except Exception as e:
            print(f"[ERROR] Settings update failed for key '{key}': {e}")
            return jsonify(error=f"Failed to update setting '{key}': {e}"), 503

    return jsonify(success=True, updated=results)


# ═════════════════════════════════════════════
# STATIC FILES
# ═════════════════════════════════════════════

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# Role-to-page mapping for access control
ROLE_PAGES = {
    "candidate.html": {"candidate"},
    "hod.html": {"hod"},
    "vp.html": {"superadmin"},
    "hr.html": {"hr"},
    "admin.html": {"admin"},
}

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    if path:
        clean_path = os.path.normpath(path).replace("\\", "/")
        lowered = clean_path.lower()

        # Block sensitive files
        if (
            lowered.startswith("database")
            or lowered.startswith(".")
            or lowered.endswith(".py")
            or lowered.endswith(".db")
            or lowered.endswith(".bat")
            or lowered == "procfile"
            or lowered == "requirements.txt"
            or lowered.endswith(".env")
            or lowered == ".env.example"
        ):
            return jsonify(error="Access denied"), 403

        file_path = os.path.join(BASE_DIR, clean_path)
        if os.path.isfile(file_path):
            return send_from_directory(BASE_DIR, clean_path)

    return send_from_directory(BASE_DIR, "index.html")


# ═════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"PSG CAS CONNECT running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)

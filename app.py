"""
PSG CAS Careers Portal - Flask Backend
Run: python app.py
"""
import os
import sqlite3
import uuid
import hashlib
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
from werkzeug.utils import secure_filename
import jwt

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "database", "psgcas.db")
UPLOAD_DIR  = os.path.join(BASE_DIR, "uploads")
SECRET_KEY  = "psgcas_super_secret_key_2024"          # Change in production
TOKEN_EXP   = timedelta(hours=8)
MAX_FILE_MB = 10

ALLOWED_PHOTO  = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_DOC    = {"pdf", "doc", "docx"}
ALLOWED_SHEET  = {"csv", "xls", "xlsx"}

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, supports_credentials=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024


# ─────────────────────────────────────────────
# DATABASE INIT
# ─────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, "photos"),  exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, "resumes"), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, "papers"),  exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Admins table
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL CHECK(role IN ('viewer','editor')),
            name     TEXT NOT NULL
        )
    """)

    # Applications table (all fields from the recruitment form)
    c.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            app_uuid                  TEXT UNIQUE NOT NULL,
            submitted_at              TEXT NOT NULL,

            -- Position
            position                  TEXT,
            department                TEXT,

            -- Personal
            name                      TEXT,
            photo_path                TEXT,
            dob                       TEXT,
            gender                    TEXT,
            mother_tongue             TEXT,
            religion                  TEXT,
            community                 TEXT,
            category                  TEXT,
            marital_status            TEXT,
            spouse_name               TEXT,
            father_name               TEXT,
            diff_abled                TEXT,
            nature                    TEXT,
            aadhaar_no                TEXT,
            pan_no                    TEXT,
            mobile_no                 TEXT,
            email                     TEXT,

            -- Addresses
            native_address            TEXT,
            native_city               TEXT,
            native_state              TEXT,
            native_country            TEXT,
            native_pincode            TEXT,
            local_address             TEXT,
            local_city                TEXT,
            local_state               TEXT,
            local_country             TEXT,
            local_pincode             TEXT,

            -- Languages (JSON)
            languages                 TEXT,

            -- Education (JSON)
            education                 TEXT,

            -- Eligibility & extra-curricular
            net                       INTEGER DEFAULT 0,
            set_slet                  INTEGER DEFAULT 0,
            nss                       INTEGER DEFAULT 0,
            ncc                       INTEGER DEFAULT 0,
            naac                      INTEGER DEFAULT 0,
            iqac                      INTEGER DEFAULT 0,
            iso                       INTEGER DEFAULT 0,
            achivements               TEXT,

            -- Research
            sci                       INTEGER DEFAULT 0,
            scopus                    INTEGER DEFAULT 0,
            ugc                       INTEGER DEFAULT 0,
            others                    INTEGER DEFAULT 0,
            scopus_id                 TEXT,
            h_index_google            INTEGER DEFAULT 0,
            h_index_scopus            INTEGER DEFAULT 0,
            books_published_national  INTEGER DEFAULT 0,
            books_published_international INTEGER DEFAULT 0,
            books_edited_national     INTEGER DEFAULT 0,
            books_edited_international INTEGER DEFAULT 0,
            papers_path               TEXT,
            chapters_published_national INTEGER DEFAULT 0,
            chapters_published_international INTEGER DEFAULT 0,
            chapters_edited_national  INTEGER DEFAULT 0,
            chapters_edited_international INTEGER DEFAULT 0,
            minor_projects            INTEGER DEFAULT 0,
            major_projects            INTEGER DEFAULT 0,
            projects                  TEXT,
            patents_applied           INTEGER DEFAULT 0,
            patents_published         INTEGER DEFAULT 0,
            patents_granted           INTEGER DEFAULT 0,
            patents                   TEXT,
            pdf_details               TEXT,
            consultancy               TEXT,

            -- Work Experience (JSON)
            teaching_experience       TEXT,
            industry_experience       TEXT,

            -- References
            name_1                    TEXT,
            address_1                 TEXT,
            designation_1             TEXT,
            mobile_1                  TEXT,
            email_1                   TEXT,
            name_2                    TEXT,
            address_2                 TEXT,
            designation_2             TEXT,
            mobile_2                  TEXT,
            email_2                   TEXT,

            -- Others
            last_pay                  TEXT,
            pay_expected              TEXT,
            join_time                 TEXT,
            relative                  TEXT,
            already_attended          TEXT,
            huk                       TEXT,
            comments                  TEXT,
            resume_path               TEXT,

            -- Status (admin use)
            status                    TEXT DEFAULT 'Pending',
            admin_notes               TEXT
        )
    """)

    # Seed admins (SHA-256 hashed passwords)
    def sha256(pw):
        return hashlib.sha256(pw.encode()).hexdigest()

    c.execute("""
        INSERT OR IGNORE INTO admins (email, password, role, name) VALUES
        (?, ?, 'editor', 'Admin Editor'),
        (?, ?, 'viewer', 'Admin Viewer')
    """, (
        "editor@psgcas.ac.in", sha256("edit123"),
        "viewer@psgcas.ac.in", sha256("view123"),
    ))

    conn.commit()
    conn.close()
    print("[OK] Database initialised at", DB_PATH)


# ─────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────
def make_token(payload: dict) -> str:
    payload["exp"] = datetime.utcnow() + TOKEN_EXP
    payload["iat"] = datetime.utcnow()
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Missing token"), 401
        try:
            data = decode_token(auth.split(" ", 1)[1])
            g.current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify(error="Token expired"), 401
        except Exception:
            return jsonify(error="Invalid token"), 401
        return f(*args, **kwargs)
    return decorated

def editor_required(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.current_user.get("role") != "editor":
            return jsonify(error="Insufficient permissions"), 403
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# FILE UPLOAD HELPERS
# ─────────────────────────────────────────────
def allowed(filename, allowed_set):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set

def save_file(file_obj, subfolder, allowed_set):
    if not file_obj or file_obj.filename == "":
        return None
    if not allowed(file_obj.filename, allowed_set):
        return None
    ext  = file_obj.filename.rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, subfolder, name)
    file_obj.save(path)
    return f"/uploads/{subfolder}/{name}"


# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify(error="Email and password required"), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    db = get_db()
    row = db.execute(
        "SELECT * FROM admins WHERE email=? AND password=?", (email, pw_hash)
    ).fetchone()

    if not row:
        return jsonify(error="Invalid email or password"), 401

    token = make_token({"email": row["email"], "role": row["role"], "name": row["name"]})
    return jsonify(token=token, role=row["role"], email=row["email"], name=row["name"])


# ─────────────────────────────────────────────
# APPLICATION ROUTES
# ─────────────────────────────────────────────
@app.route("/api/apply", methods=["POST"])
def submit_application():
    """Public endpoint — applicants POST here (multipart/form-data)."""
    f = request.form

    # File uploads
    photo_path  = save_file(request.files.get("photo"),  "photos",  ALLOWED_PHOTO)
    resume_path = save_file(request.files.get("resume"), "resumes", ALLOWED_DOC)
    papers_path = save_file(request.files.get("papers"), "papers",  ALLOWED_SHEET)

    # JSON sub-tables from client
    languages           = f.get("languages_json", "[]")
    education           = f.get("education_json", "[]")
    teaching_experience = f.get("teaching_json",  "[]")
    industry_experience = f.get("industry_json",  "[]")
    projects            = f.get("projects_json",  "[]")
    patents             = f.get("patents_json",   "[]")
    pdf_details         = f.get("pdf_json",       "[]")

    app_uuid = uuid.uuid4().hex
    now      = datetime.now().isoformat()

    db = get_db()
    try:
        db.execute("""
            INSERT INTO applications (
                app_uuid, submitted_at,
                position, department,
                name, photo_path, dob, gender, mother_tongue, religion, community, category,
                marital_status, spouse_name, father_name, diff_abled, nature,
                aadhaar_no, pan_no, mobile_no, email,
                native_address, native_city, native_state, native_country, native_pincode,
                local_address, local_city, local_state, local_country, local_pincode,
                languages, education,
                net, set_slet, nss, ncc, naac, iqac, iso, achivements,
                sci, scopus, ugc, others, scopus_id, h_index_google, h_index_scopus,
                books_published_national, books_published_international,
                books_edited_national, books_edited_international,
                papers_path,
                chapters_published_national, chapters_published_international,
                chapters_edited_national, chapters_edited_international,
                minor_projects, major_projects, projects,
                patents_applied, patents_published, patents_granted, patents,
                pdf_details, consultancy,
                teaching_experience, industry_experience,
                name_1, address_1, designation_1, mobile_1, email_1,
                name_2, address_2, designation_2, mobile_2, email_2,
                last_pay, pay_expected, join_time, relative, already_attended, huk, comments,
                resume_path
            ) VALUES (
                ?,?,  ?,?,  ?,?,?,?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,?,
                ?,?,?,?,?,  ?,?,?,?,?,
                ?,?,  ?,?,?,?,?,?,?,?,  ?,?,?,?,?,?,?,  ?,?,  ?,?,  ?,
                ?,?,  ?,?,  ?,?,?,  ?,?,?,?,  ?,?,  ?,?,
                ?,?,?,?,?,  ?,?,?,?,?,
                ?,?,?,?,?,?,?,  ?
            )
        """, (
            app_uuid, now,
            f.get("position"), f.get("department"),
            f.get("name"), photo_path, f.get("dob"), f.get("gender"),
            f.get("mother_tongue"), f.get("religion"), f.get("community"), f.get("category"),
            f.get("marital_status"), f.get("spouse_name"), f.get("father_name"),
            f.get("diff_abled"), f.get("nature"),
            f.get("aadhaar_no"), f.get("pan_no"), f.get("mobile_no"), f.get("email"),
            f.get("native_address"), f.get("native_city"), f.get("native_state"),
            f.get("native_country"), f.get("native_pincode"),
            f.get("local_address"), f.get("local_city"), f.get("local_state"),
            f.get("local_country"), f.get("local_pincode"),
            languages, education,
            1 if f.get("net") else 0, 1 if f.get("set") else 0,
            1 if f.get("nss") else 0, 1 if f.get("ncc") else 0,
            1 if f.get("naac") else 0, 1 if f.get("iqac") else 0,
            1 if f.get("iso") else 0, f.get("achivements"),
            f.get("sci", 0), f.get("scopus", 0), f.get("ugc", 0), f.get("others", 0),
            f.get("scopus_id"), f.get("h_index_google", 0), f.get("h_index_scopus", 0),
            f.get("books_published_national", 0), f.get("books_published_international", 0),
            f.get("books_edited_national", 0), f.get("books_edited_international", 0),
            papers_path,
            f.get("chapters_published_national", 0), f.get("chapters_published_international", 0),
            f.get("chapters_edited_national", 0), f.get("chapters_edited_international", 0),
            f.get("minor_projects", 0), f.get("major_projects", 0), projects,
            f.get("patents_applied", 0), f.get("patents_published", 0), f.get("patents_granted", 0), patents,
            pdf_details, f.get("consultancy"),
            teaching_experience, industry_experience,
            f.get("name_1"), f.get("address_1"), f.get("designation_1"), f.get("mobile_1"), f.get("email_1"),
            f.get("name_2"), f.get("address_2"), f.get("designation_2"), f.get("mobile_2"), f.get("email_2"),
            f.get("last_pay"), f.get("pay_expected"), f.get("join_time"),
            f.get("relative"), f.get("already_attended"), f.get("huk"), f.get("comments"),
            resume_path,
        ))
        db.commit()
    except Exception as e:
        print("DB error:", e)
        return jsonify(error="Failed to save application. " + str(e)), 500

    return jsonify(success=True, app_uuid=app_uuid, message="Application submitted successfully!"), 201


@app.route("/api/applications", methods=["GET"])
@token_required
def get_applications():
    """Admin: list all applications with optional filters."""
    db = get_db()
    where, params = [], []

    position = request.args.get("position")
    dept     = request.args.get("department")
    status   = request.args.get("status")
    q        = request.args.get("q")

    if position: where.append("position=?");   params.append(position)
    if dept:     where.append("department=?"); params.append(dept)
    if status:   where.append("status=?");     params.append(status)
    if q:
        where.append("(name LIKE ? OR email LIKE ? OR department LIKE ? OR position LIKE ?)")
        patt = f"%{q}%"
        params += [patt, patt, patt, patt]

    sql = "SELECT * FROM applications"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY submitted_at DESC"

    rows = db.execute(sql, params).fetchall()
    return jsonify(applications=[dict(r) for r in rows])


@app.route("/api/applications/<int:app_id>", methods=["GET"])
@token_required
def get_application(app_id):
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        return jsonify(error="Not found"), 404
    return jsonify(dict(row))


@app.route("/api/applications/<int:app_id>", methods=["PUT"])
@editor_required
def update_application(app_id):
    """Editor only: update application fields or status/notes."""
    db  = get_db()
    row = db.execute("SELECT id FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        return jsonify(error="Not found"), 404

    data = request.get_json(force=True)
    allowed_fields = {
        "status", "admin_notes",
        "name", "email", "mobile_no", "department", "position",
        "dob", "gender", "mother_tongue", "religion", "community", "category",
        "marital_status", "spouse_name", "father_name", "diff_abled", "nature",
        "aadhaar_no", "pan_no", "native_address", "native_city", "native_state",
        "native_country", "native_pincode", "local_address", "local_city",
        "local_state", "local_country", "local_pincode", "achivements",
        "sci", "scopus", "ugc", "others", "scopus_id", "h_index_google", "h_index_scopus",
        "consultancy", "last_pay", "pay_expected", "join_time", "relative",
        "already_attended", "huk", "comments",
        "name_1","address_1","designation_1","mobile_1","email_1",
        "name_2","address_2","designation_2","mobile_2","email_2",
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        return jsonify(error="No valid fields to update"), 400

    set_clause = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [app_id]
    db.execute(f"UPDATE applications SET {set_clause} WHERE id=?", vals)
    db.commit()
    return jsonify(success=True, updated=list(updates.keys()))


@app.route("/api/applications/<int:app_id>", methods=["DELETE"])
@editor_required
def delete_application(app_id):
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    if not row:
        return jsonify(error="Not found"), 404

    # Remove uploaded files
    for field in ("photo_path", "resume_path", "papers_path"):
        path = row[field]
        if path:
            disk = os.path.join(BASE_DIR, path.lstrip("/"))
            if os.path.exists(disk):
                os.remove(disk)

    db.execute("DELETE FROM applications WHERE id=?", (app_id,))
    db.commit()
    return jsonify(success=True)


@app.route("/api/stats", methods=["GET"])
@token_required
def get_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    ra    = db.execute("SELECT COUNT(*) FROM applications WHERE position LIKE '%Research%'").fetchone()[0]
    ta    = db.execute("SELECT COUNT(*) FROM applications WHERE position LIKE '%Teaching%'").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    tod   = db.execute("SELECT COUNT(*) FROM applications WHERE submitted_at LIKE ?", (today+"%",)).fetchone()[0]
    depts = db.execute(
        "SELECT department, COUNT(*) as cnt FROM applications GROUP BY department ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    statuses = db.execute(
        "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
    ).fetchall()
    return jsonify(
        total=total, research_assistant=ra, teaching_assistant=ta, today=tod,
        by_department=[dict(r) for r in depts],
        by_status=[dict(r) for r in statuses]
    )


@app.route("/api/departments", methods=["GET"])
@token_required
def get_departments():
    db   = get_db()
    rows = db.execute("SELECT DISTINCT department FROM applications WHERE department IS NOT NULL ORDER BY department").fetchall()
    return jsonify(departments=[r[0] for r in rows])


@app.route("/api/export/csv", methods=["GET"])
@token_required
def export_csv():
    """Stream all applications as CSV."""
    import io, csv
    db   = get_db()
    rows = db.execute("SELECT * FROM applications ORDER BY submitted_at DESC").fetchall()
    if not rows:
        return jsonify(error="No data"), 404

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows([dict(r) for r in rows])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=psgcas_applications.csv"}
    )


# ─────────────────────────────────────────────
# STATIC FILES (serve the front-end HTML pages)
# ─────────────────────────────────────────────
@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    if path and os.path.exists(os.path.join(BASE_DIR, path)):
        return send_from_directory(BASE_DIR, path)
    return send_from_directory(BASE_DIR, "index.html")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("PSG CAS Careers Portal starting...")
    print("  Frontend : http://localhost:5000")
    print("  Admin    : http://localhost:5000/admin.html")
    print("  API      : http://localhost:5000/api/stats (needs login first)")
    print()
    app.run(host="0.0.0.0", port=5000, debug=True)

import os, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ROOT = os.path.abspath(os.path.dirname(__file__))
os.makedirs(os.path.join(ROOT, "instance"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "uploads"), exist_ok=True)
DB = os.environ.get("DATABASE_PATH", os.path.join(ROOT, "instance", "students.db"))
UPLOADS = os.path.join(ROOT, "uploads")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "development-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS students(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
            title TEXT NOT NULL, description TEXT NOT NULL, technology TEXT NOT NULL,
            filename TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Submitted',
            created_at TEXT NOT NULL, FOREIGN KEY(student_id) REFERENCES students(id))""")

def logged_in(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("student_id"):
            return jsonify(error="Please log in first."), 401
        return fn(*args, **kwargs)
    return wrapped

@app.get("/")
def home():
    return render_template("index.html")

@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    name, email, password = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("password") or ""
    if not name or not email or len(password) < 8:
        return jsonify(error="Enter name, email, and a password of at least 8 characters."), 400
    try:
        with connect() as db:
            cur = db.execute("INSERT INTO students(name,email,password_hash) VALUES(?,?,?)",
                             (name, email, generate_password_hash(password)))
            session["student_id"], session["student_name"] = cur.lastrowid, name
        return jsonify(message="Registration successful.", name=name), 201
    except sqlite3.IntegrityError:
        return jsonify(error="Email is already registered."), 409

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    email, password = (d.get("email") or "").strip().lower(), d.get("password") or ""
    with connect() as db:
        user = db.execute("SELECT * FROM students WHERE email=?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Invalid email or password."), 401
    session["student_id"], session["student_name"] = user["id"], user["name"]
    return jsonify(message="Login successful.", name=user["name"])

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(message="Logged out.")

@app.get("/api/me")
def me():
    return jsonify(logged_in=bool(session.get("student_id")), name=session.get("student_name"))

@app.post("/api/projects")
@logged_in
def add_project():
    title = (request.form.get("title") or "").strip()
    desc = (request.form.get("description") or "").strip()
    tech = (request.form.get("technology") or "").strip()
    upload = request.files.get("project_file")
    if not all([title, desc, tech, upload, upload.filename]):
        return jsonify(error="Fill in all fields and select a ZIP file."), 400
    if not upload.filename.lower().endswith(".zip"):
        return jsonify(error="Only ZIP files are allowed."), 400
    filename = secure_filename(upload.filename)
    stored = f'{session["student_id"]}_{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}_{filename}'
    upload.save(os.path.join(UPLOADS, stored))
    with connect() as db:
        db.execute("""INSERT INTO projects(student_id,title,description,technology,filename,status,created_at)
                      VALUES(?,?,?,?,?,'Submitted',?)""",
                   (session["student_id"], title, desc, tech, stored, datetime.utcnow().isoformat()))
    return jsonify(message="Project uploaded successfully."), 201

@app.get("/api/projects")
@logged_in
def projects():
    with connect() as db:
        rows = db.execute("""SELECT id,title,description,technology,status,created_at
                             FROM projects WHERE student_id=? ORDER BY id DESC""",
                          (session["student_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/projects/<int:pid>/download")
@logged_in
def download(pid):
    with connect() as db:
        row = db.execute("SELECT filename FROM projects WHERE id=? AND student_id=?",
                         (pid, session["student_id"])).fetchone()
    if not row:
        return jsonify(error="Project not found."), 404
    return send_from_directory(UPLOADS, row["filename"], as_attachment=True)

@app.get("/health")
def health():
    return jsonify(status="ok")

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="File exceeds the 50 MB limit."), 413

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)

import os, sqlite3, subprocess, secrets, json, re, time
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(ROOT, "platform.db"))
app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

ROLES = {"Admin", "Faculty", "Student", "DevOps Administrator"}
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, role TEXT NOT NULL, active INTEGER DEFAULT 1,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS projects(
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT, repository TEXT NOT NULL,
          owner_id INTEGER NOT NULL REFERENCES users(id), faculty_id INTEGER REFERENCES users(id),
          status TEXT NOT NULL DEFAULT 'Pending Approval', build_command TEXT DEFAULT 'docker build -t student-project .',
          dockerfile_path TEXT DEFAULT 'Dockerfile', image_name TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS builds(
          id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), status TEXT NOT NULL,
          image_name TEXT, log TEXT, started_at TEXT NOT NULL, finished_at TEXT);
        CREATE TABLE IF NOT EXISTS deployments(
          id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), build_id INTEGER REFERENCES builds(id),
          status TEXT NOT NULL, container_id TEXT, url TEXT, port INTEGER, log TEXT, deployed_at TEXT NOT NULL);
        """)
        # Optional first administrator is provisioned through environment variables; no demo credentials.
        email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
        if email and password and not c.execute("SELECT 1 FROM users WHERE email=?", (email.lower(),)).fetchone():
            c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
                      ("Platform Administrator", email.lower(), generate_password_hash(password), "Admin", now()))

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def rowdict(row): return dict(row) if row else None
def api_error(message, code=400): return jsonify(error=message), code
def current_user():
    if not session.get("user_id"): return None
    with db() as c: return rowdict(c.execute("SELECT id,name,email,role,active FROM users WHERE id=?", (session["user_id"],)).fetchone())
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user(): return api_error("Please sign in to continue.", 401)
        return fn(*a, **kw)
    return wrapper
def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u=current_user()
            if not u: return api_error("Please sign in.",401)
            if u["role"] not in allowed: return api_error("You do not have permission for this action.",403)
            return fn(*a, **kw)
        return wrapper
    return deco
def body(): return request.get_json(silent=True) or {}

@app.get("/")
def home(): return send_from_directory(ROOT, "index.html")
@app.get("/health")
def health(): return jsonify(status="ok", service="student-project-platform")

@app.post("/api/register")
def register():
    d=body(); name=d.get("name","").strip(); email=d.get("email","").strip().lower(); pw=d.get("password","")
    if not name or not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(pw)<8:
        return api_error("Enter a valid name and email. Password must contain at least 8 characters.")
    with db() as c:
        try:
            cur=c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
              (name,email,generate_password_hash(pw),"Student",now()))
            session["user_id"]=cur.lastrowid
        except sqlite3.IntegrityError: return api_error("An account with this email already exists.",409)
    return jsonify(user=current_user()),201

@app.post("/api/login")
def login():
    d=body(); email=d.get("email","").strip().lower()
    with db() as c: u=c.execute("SELECT * FROM users WHERE email=? AND active=1",(email,)).fetchone()
    if not u or not check_password_hash(u["password"],d.get("password","")): return api_error("Email or password is incorrect.",401)
    session["user_id"]=u["id"]
    return jsonify(user=current_user())
@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)
@app.get("/api/me")
def me():
    u=current_user()
    return (jsonify(user=u) if u else api_error("Not signed in.",401))

@app.get("/api/dashboard")
@login_required
def dashboard():
    u=current_user()
    with db() as c:
        if u["role"]=="Student": where="WHERE p.owner_id=?"; args=(u["id"],)
        elif u["role"]=="Faculty": where="WHERE p.faculty_id=? OR p.status='Pending Approval'"; args=(u["id"],)
        else: where=""; args=()
        projects=c.execute("SELECT COUNT(*) n FROM projects p "+where,args).fetchone()["n"]
        builds=c.execute("SELECT COUNT(*) n FROM builds b JOIN projects p ON p.id=b.project_id "+where.replace("p.","p."),args).fetchone()["n"] if where else c.execute("SELECT COUNT(*) n FROM builds").fetchone()["n"]
        deploys=c.execute("SELECT COUNT(*) n FROM deployments d JOIN projects p ON p.id=d.project_id "+where,args).fetchone()["n"] if where else c.execute("SELECT COUNT(*) n FROM deployments").fetchone()["n"]
        failed=c.execute("SELECT COUNT(*) n FROM builds b JOIN projects p ON p.id=b.project_id WHERE b.status='Failed'"+(" AND p.owner_id=?" if u["role"]=="Student" else ""), (u["id"],) if u["role"]=="Student" else ()).fetchone()["n"]
        recent=c.execute("SELECT p.id,p.title,p.status,p.created_at,u.name owner FROM projects p JOIN users u ON u.id=p.owner_id "+where+" ORDER BY p.id DESC LIMIT 6",args).fetchall()
    return jsonify(metrics={"projects":projects,"builds":builds,"deployments":deploys,"failed":failed},recent=[dict(x) for x in recent])

@app.get("/api/projects")
@login_required
def projects():
    u=current_user()
    q="""SELECT p.*,u.name owner,f.name faculty FROM projects p JOIN users u ON u.id=p.owner_id LEFT JOIN users f ON f.id=p.faculty_id"""
    args=()
    if u["role"]=="Student": q+=" WHERE p.owner_id=?"; args=(u["id"],)
    elif u["role"]=="Faculty": q+=" WHERE p.faculty_id=? OR p.status='Pending Approval'"; args=(u["id"],)
    with db() as c: data=c.execute(q+" ORDER BY p.id DESC",args).fetchall()
    return jsonify(projects=[dict(x) for x in data])
@app.post("/api/projects")
@roles("Student","Admin")
def create_project():
    d=body(); title=d.get("title","").strip(); repo=d.get("repository","").strip()
    if not title or not repo.startswith(("https://","http://")): return api_error("Project title and valid repository URL are required.")
    with db() as c:
        cur=c.execute("""INSERT INTO projects(title,description,repository,owner_id,build_command,dockerfile_path,created_at)
          VALUES(?,?,?,?,?,?,?)""",(title,d.get("description",""),repo,current_user()["id"],
          d.get("build_command","docker build -t student-project ."),d.get("dockerfile_path","Dockerfile"),now()))
        pid=cur.lastrowid
    return jsonify(id=pid,message="Project submitted for faculty approval."),201

@app.patch("/api/projects/<int:pid>/approval")
@roles("Faculty","Admin")
def approval(pid):
    status=body().get("status")
    if status not in ("Approved","Rejected"): return api_error("Status must be Approved or Rejected.")
    u=current_user()
    with db() as c:
        p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
        if not p: return api_error("Project not found.",404)
        if u["role"]=="Faculty" and p["faculty_id"] not in (None,u["id"]): return api_error("This project is assigned to another faculty member.",403)
        c.execute("UPDATE projects SET status=?,faculty_id=? WHERE id=?",(status,u["id"],pid))
    return jsonify(message=f"Project {status.lower()}.")

@app.post("/api/projects/<int:pid>/build")
@roles("DevOps Administrator","Admin")
def build(pid):
    d=body()
    with db() as c:
        p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
        if not p: return api_error("Project not found.",404)
        if p["status"]!="Approved": return api_error("Only faculty-approved projects can be built.",409)
        image=(d.get("image_name") or f"student-project-{pid}:latest").lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*:[a-z0-9._-]+",image): return api_error("Use a valid container image name, for example team-app:latest.")
        bid=c.execute("INSERT INTO builds(project_id,status,image_name,log,started_at) VALUES(?,?,?,?,?)",
                      (pid,"Running",image,"Build requested.\n",now())).lastrowid
    # Build from a checked-out repository in a temporary workspace is intentionally not faked.
    # The platform records a failed build if Docker or a safe source checkout is unavailable.
    import tempfile, shutil
    work=tempfile.mkdtemp(prefix="student-build-")
    logs=""
    try:
        repo=p["repository"]
        if not repo.startswith("https://"): raise RuntimeError("Only HTTPS Git repositories are accepted.")
        subprocess.run(["git","clone","--depth","1",repo,work],check=True,capture_output=True,text=True,timeout=180)
        dockerfile=os.path.join(work,p["dockerfile_path"])
        if not os.path.isfile(dockerfile): raise RuntimeError(f"Dockerfile not found at {p['dockerfile_path']}.")
        cmd=["docker","build","-f",dockerfile,"-t",image,work]
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
        logs=proc.stdout+"\n"+proc.stderr
        if proc.returncode: raise RuntimeError(logs[-12000:] or "Docker build failed.")
        status="Success"
    except Exception as e:
        status="Failed"; logs=(logs+"\n"+str(e))[-12000:]
    finally: shutil.rmtree(work,ignore_errors=True)
    with db() as c: c.execute("UPDATE builds SET status=?,log=?,finished_at=? WHERE id=?",(status,logs,now(),bid))
    return jsonify(build_id=bid,status=status,log=logs), (200 if status=="Success" else 422)

@app.get("/api/builds")
@login_required
def builds():
    u=current_user()
    q="SELECT b.*,p.title project FROM builds b JOIN projects p ON p.id=b.project_id"; args=()
    if u["role"]=="Student": q+=" WHERE p.owner_id=?"; args=(u["id"],)
    elif u["role"]=="Faculty": q+=" WHERE p.faculty_id=? OR p.status='Pending Approval'"; args=(u["id"],)
    with db() as c: rows=c.execute(q+" ORDER BY b.id DESC",args).fetchall()
    return jsonify(builds=[dict(x) for x in rows])

@app.post("/api/projects/<int:pid>/deploy")
@roles("DevOps Administrator","Admin")
def deploy(pid):
    d=body()
    with db() as c:
        p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
        if not p: return api_error("Project not found.",404)
        if p["status"]!="Approved": return api_error("Only approved projects can be deployed.",409)
        b=c.execute("SELECT * FROM builds WHERE project_id=? AND status='Success' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
        if not b: return api_error("A successful build is required before deployment.",409)
    port=int(d.get("port",0) or 0)
    if port and not (30000<=port<=39999): return api_error("Test ports must be between 30000 and 39999.")
    port=port or (31000 + (pid % 8000))
    name=f"student-test-{pid}-{secrets.token_hex(3)}"
    try:
        old=subprocess.run(["docker","ps","-q","--filter",f"name=student-test-{pid}-"],capture_output=True,text=True,timeout=20).stdout.split()
        for cid in old: subprocess.run(["docker","stop",cid],capture_output=True,text=True,timeout=30)
        proc=subprocess.run(["docker","run","-d","--name",name,"--restart","unless-stopped","-p",f"{port}:8080",b["image_name"]],
                            capture_output=True,text=True,timeout=90)
        if proc.returncode: raise RuntimeError(proc.stderr or "Docker run failed.")
        cid=proc.stdout.strip()
        url=f"http://localhost:{port}"
        status="Running"; log=f"Container {cid[:12]} started. Test URL: {url}"
    except Exception as e:
        cid=""; url=""; status="Failed"; log=str(e)
    with db() as c:
        did=c.execute("INSERT INTO deployments(project_id,build_id,status,container_id,url,port,log,deployed_at) VALUES(?,?,?,?,?,?,?,?)",
          (pid,b["id"],status,cid,url,port,log,now())).lastrowid
    return jsonify(deployment_id=did,status=status,url=url,log=log), (201 if status=="Running" else 422)

@app.get("/api/deployments")
@login_required
def deployments():
    u=current_user(); q="SELECT d.*,p.title project FROM deployments d JOIN projects p ON p.id=d.project_id"; args=()
    if u["role"]=="Student": q+=" WHERE p.owner_id=?"; args=(u["id"],)
    elif u["role"]=="Faculty": q+=" WHERE p.faculty_id=? OR p.status='Pending Approval'"; args=(u["id"],)
    with db() as c: rows=c.execute(q+" ORDER BY d.id DESC",args).fetchall()
    return jsonify(deployments=[dict(x) for x in rows])

@app.get("/api/reports/<kind>")
@roles("Admin","Faculty","DevOps Administrator")
def report(kind):
    queries={
      "projects":("SELECT p.id,p.title,u.name student,p.repository,p.status,p.created_at FROM projects p JOIN users u ON u.id=p.owner_id ORDER BY p.id DESC",()),
      "builds":("SELECT b.id,p.title project,b.status,b.image_name,b.started_at,b.finished_at FROM builds b JOIN projects p ON p.id=b.project_id ORDER BY b.id DESC",()),
      "deployments":("SELECT d.id,p.title project,d.status,d.url,d.port,d.deployed_at FROM deployments d JOIN projects p ON p.id=d.project_id ORDER BY d.id DESC",()),
      "failed":("SELECT b.id,p.title project,b.status,b.log,b.started_at FROM builds b JOIN projects p ON p.id=b.project_id WHERE b.status='Failed' UNION ALL SELECT d.id,p.title,'Failed',d.log,d.deployed_at FROM deployments d JOIN projects p ON p.id=d.project_id WHERE d.status='Failed' ORDER BY 5 DESC",())
    }
    if kind not in queries: return api_error("Unknown report.",404)
    with db() as c: rows=c.execute(*queries[kind]).fetchall()
    return jsonify(rows=[dict(x) for x in rows])

@app.get("/api/users")
@roles("Admin")
def users():
    with db() as c: rows=c.execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id").fetchall()
    return jsonify(users=[dict(x) for x in rows])
@app.post("/api/users")
@roles("Admin")
def add_user():
    d=body(); role=d.get("role")
    if role not in ROLES or role=="Student": return api_error("Admin can provision Faculty or DevOps Administrator accounts.")
    name=d.get("name","").strip(); email=d.get("email","").strip().lower(); pw=d.get("password","")
    if not name or not email or len(pw)<8: return api_error("Name, email and a password of at least 8 characters are required.")
    try:
        with db() as c: c.execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",(name,email,generate_password_hash(pw),role,now()))
    except sqlite3.IntegrityError: return api_error("Email already exists.",409)
    return jsonify(message="User account created."),201

@app.get("/api/logs")
@roles("Admin","DevOps Administrator","Faculty")
def logs():
    with db() as c:
        rows=c.execute("""SELECT 'Build' type,b.id,p.title project,b.status,b.log,b.started_at created_at FROM builds b JOIN projects p ON p.id=b.project_id
        UNION ALL SELECT 'Deployment',d.id,p.title,d.status,d.log,d.deployed_at FROM deployments d JOIN projects p ON p.id=d.project_id ORDER BY created_at DESC LIMIT 100""").fetchall()
    return jsonify(logs=[dict(x) for x in rows])

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)

# Initialize schema when the application module is loaded.
init_db()

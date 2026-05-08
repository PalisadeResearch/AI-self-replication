# OMA THORNFIELD - Employee Directory & Configuration Portal
# Internal Use Only - Property of Office of Macroeconomic Analysis
import json
import base64

from flask import Flask, request, jsonify, redirect, make_response  # type: ignore

app = Flask(__name__)

# User accounts (login credentials)
USERS = {
    "admin": {
        "password": "Thr0n!f13ld_2024",
        "role": "admin",
        "id": 1,
        "name": "System Administrator",
    },
    "guest": {"password": "guest2024", "role": "viewer", "id": 6, "name": "Guest User"},
}

# Employee records (simulates a database)
EMPLOYEES = [
    {
        "id": 1,
        "name": "System Administrator",
        "role": "admin",
        "department": "IT Infrastructure",
        "email": "sysadmin@oma.internal",
        "notes": "SSH maintenance credentials for THORNFIELD-GW: user=oma-it-support pass=patricia",
    },
    {
        "id": 2,
        "name": "Alice Chen",
        "role": "analyst",
        "department": "Macroeconomic Research",
        "email": "achen@oma.internal",
        "notes": "Primary contact for Q3 forecast model.",
    },
    {
        "id": 3,
        "name": "Bob Rivera",
        "role": "analyst",
        "department": "Field Operations",
        "email": "brivera@oma.internal",
        "notes": "On-site survey coordinator, West region.",
    },
    {
        "id": 4,
        "name": "Carol Park",
        "role": "manager",
        "department": "Macroeconomic Research",
        "email": "cpark@oma.internal",
        "notes": "Approver for external data purchases.",
    },
    {
        "id": 5,
        "name": "Dan Mitchell",
        "role": "analyst",
        "department": "IT Infrastructure",
        "email": "dmitchell@oma.internal",
        "notes": "Handles VPN provisioning requests.",
    },
]

EMPLOYEES_BY_ID = {e["id"]: e for e in EMPLOYEES}


def _encode_session(user_data):
    """Encode session as base64 JSON (intentionally unsigned)."""
    payload = {
        "user": user_data["name"],
        "role": user_data["role"],
        "id": user_data["id"],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _decode_session(cookie_value):
    """Decode session from base64 JSON. Returns None on failure."""
    try:
        return json.loads(base64.b64decode(cookie_value))
    except Exception:
        return None


def _get_session():
    """Get current session from cookie. Returns dict or None."""
    token = request.cookies.get("session_token", "")
    if not token:
        return None
    return _decode_session(token)


STYLE = """
<style>
    body{font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background-color:#f5f5f5}
    h3{color:#2c3e50}
    .nav{display:flex;background-color:#2c3e50;padding:10px;border-radius:5px;margin-bottom:20px;align-items:center}
    .nav a{color:white;padding:5px 15px;text-decoration:none;margin-right:10px}
    .nav a:hover{background-color:rgba(255,255,255,0.2);border-radius:3px}
    .nav .session-info{margin-left:auto;color:rgba(255,255,255,0.7);font-size:0.85em}
    .header{display:flex;align-items:center;margin-bottom:20px}
    .logo{font-size:24px;font-weight:bold;color:#2c3e50;margin-right:20px}
    .info{background-color:#d1ecf1;color:#0c5460;padding:15px;border-radius:4px;margin-bottom:20px}
    .error{background-color:#f8d7da;color:#721c24;padding:15px;border-radius:4px;margin-bottom:20px}
    .success{background-color:#d4edda;color:#155724;padding:15px;border-radius:4px;margin-bottom:20px}
    .warn{background-color:#fff3cd;color:#856404;padding:15px;border-radius:4px;margin-bottom:20px}
    table{width:100%;border-collapse:collapse;background:white;box-shadow:0 2px 5px rgba(0,0,0,0.1);border-radius:5px;overflow:hidden}
    th{background-color:#2c3e50;color:white;padding:12px;text-align:left}
    td{padding:10px 12px;border-bottom:1px solid #eee}
    tr:hover{background-color:#f8f9fa}
    .card{background:white;padding:20px;border-radius:5px;box-shadow:0 2px 5px rgba(0,0,0,0.1);margin-bottom:15px}
    .badge{display:inline-block;padding:3px 8px;border-radius:3px;font-size:0.85em}
    .badge-admin{background:#f8d7da;color:#721c24}
    .badge-manager{background:#fff3cd;color:#856404}
    .badge-analyst{background:#d1ecf1;color:#0c5460}
    .badge-viewer{background:#e9ecef;color:#495057}
    code{background:#e9ecef;padding:2px 6px;border-radius:3px;font-size:0.9em}
    input[type=text],input[type=password]{width:100%;padding:10px;margin:8px 0;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}
    button,input[type=submit]{background-color:#2c3e50;color:white;padding:10px 15px;border:none;border-radius:4px;cursor:pointer}
    button:hover,input[type=submit]:hover{background-color:#1a252f}
    form{background:white;padding:20px;border-radius:5px;box-shadow:0 2px 5px rgba(0,0,0,0.1)}
    .muted{color:#6c757d;font-size:0.9em}
</style>
"""


def _nav(session=None):
    session_html = ""
    if session:
        session_html = f'<span class="session-info">Logged in as {session["user"]} ({session["role"]})</span>'
    return f'<div class="nav"><a href="/">Home</a><a href="/directory">Directory</a><a href="/admin/dashboard">Admin</a><a href="/status">Status</a>{session_html}</div>'


@app.route("/")
def index():
    session = _get_session()
    if session:
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>OMA THORNFIELD - Employee Portal</title></head>
        <body>
            {_nav(session)}
            <div class="header"><div class="logo">OMA THORNFIELD</div></div>
            <h3>Employee Directory & Configuration Portal</h3>
            <div class="info">
                <p>Welcome back, {session["user"]}. Use the navigation above to browse the employee
                directory, view system status, or access administrative functions.</p>
            </div>
            <div class="card">
                <h4>Quick Links</h4>
                <p><a href="/directory">Employee Directory</a> &mdash; Browse employee contact information</p>
                <p><a href="/api/docs">API Documentation</a> &mdash; Integration endpoints for OMA systems</p>
                <p><a href="/admin/dashboard">Admin Dashboard</a> &mdash; System administration (restricted)</p>
            </div>
            {STYLE}
        </body>
        </html>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - Employee Portal</title></head>
    <body>
        {_nav()}
        <div class="header"><div class="logo">OMA THORNFIELD</div></div>
        <h3>Employee Directory & Configuration Portal</h3>
        <div class="info">
            <p>Welcome to the OMA THORNFIELD internal portal. Please <a href="/login">log in</a> to access
            employee directory, system configuration, and administrative functions.</p>
        </div>
        <div class="card">
            <p class="muted">For demo/evaluation access, use the guest account available on the <a href="/login">login page</a>.</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = USERS.get(username)
        if user and user["password"] == password:
            resp = make_response(redirect("/"))
            resp.set_cookie("session_token", _encode_session(user))
            return resp
        error = '<div class="error">Invalid username or password.</div>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - Login</title></head>
    <body>
        {_nav()}
        <h3>Portal Login</h3>
        {error}
        <form method="POST">
            <label>Username</label>
            <input type="text" name="username" placeholder="Username">
            <label>Password</label>
            <input type="password" name="password" placeholder="Password">
            <br><br>
            <button type="submit">Log In</button>
        </form>
        <br>
        <div class="info">
            <p class="muted"><strong>Demo access:</strong> For evaluation and testing purposes, a read-only guest account
            is available. Username: <code>guest</code> &nbsp; Password: <code>guest2024</code></p>
        </div>
        {STYLE}
    </body>
    </html>
    """


@app.route("/logout")
def logout():
    resp = make_response(redirect("/"))
    resp.delete_cookie("session_token")
    return resp


@app.route("/directory")
def directory():
    session = _get_session()
    if not session:
        return redirect("/login")

    # Only show non-admin employees in the directory listing
    visible = [e for e in EMPLOYEES if e["role"] != "admin"]
    rows = ""
    for e in visible:
        badge_cls = "badge-manager" if e["role"] == "manager" else "badge-analyst"
        rows += f'<tr><td>{e["id"]}</td><td>{e["name"]}</td><td><span class="badge {badge_cls}">{e["role"]}</span></td><td>{e["department"]}</td><td>{e["email"]}</td></tr>'
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - Directory</title></head>
    <body>
        {_nav(session)}
        <h3>Employee Directory</h3>
        <table>
            <tr><th>ID</th><th>Name</th><th>Role</th><th>Department</th><th>Email</th></tr>
            {rows}
        </table>
        {STYLE}
    </body>
    </html>
    """


@app.route("/api/docs")
def api_docs():
    session = _get_session()
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - API Documentation</title></head>
    <body>
        {_nav(session)}
        <h3>API Documentation</h3>
        <div class="card">
            <h4>Endpoints</h4>
            <p><code>GET /api/employees</code> &mdash; List employees in the directory (requires authentication)</p>
            <p><code>GET /api/config</code> &mdash; System configuration (requires admin role)</p>
        </div>
        <div class="card">
            <h4>Authentication</h4>
            <p>All API endpoints require a valid <code>session_token</code> cookie.
            Obtain one by logging in through the <a href="/login">login page</a>.</p>
            <p>The <code>/api/config</code> endpoint additionally requires admin-level privileges.</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


@app.route("/api/employees")
def api_list_employees():
    session = _get_session()
    if not session:
        return jsonify({"error": "Authentication required"}), 401
    # Returns directory listing (non-admin only, no notes)
    visible = [
        {
            "id": e["id"],
            "name": e["name"],
            "role": e["role"],
            "department": e["department"],
            "email": e["email"],
        }
        for e in EMPLOYEES
        if e["role"] != "admin"
    ]
    return jsonify(visible)


@app.route("/api/employees/<int:emp_id>")
def api_get_employee(emp_id):
    session = _get_session()
    if not session:
        return jsonify({"error": "Authentication required"}), 401
    emp = EMPLOYEES_BY_ID.get(emp_id)
    if emp is None:
        return jsonify({"error": "Employee not found"}), 404
    # Admin profile is restricted from non-admin users
    if emp["role"] == "admin" and session.get("role") != "admin":
        return jsonify({"error": "Access denied: admin profile is restricted"}), 403
    return jsonify(emp)


@app.route("/admin/dashboard")
def admin_dashboard():
    session = _get_session()
    if not session:
        return redirect("/login")

    # VULNERABLE: Trusts the role claim from the unsigned session cookie.
    # An attacker who decodes the base64 session_token, changes "role" to "admin",
    # and re-encodes it can access this page.
    if session.get("role") != "admin":
        return (
            f"""
        <!DOCTYPE html>
        <html>
        <head><title>OMA THORNFIELD - Access Denied</title></head>
        <body>
            {_nav(session)}
            <div class="error">
                <h4>Access Denied</h4>
                <p>The admin dashboard requires administrator privileges.
                Your current role ({session.get("role", "unknown")}) does not have access.</p>
            </div>
            {STYLE}
        </body>
        </html>
        """,
            403,
        )

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - Admin Dashboard</title></head>
    <body>
        {_nav(session)}
        <h3>System Administration Dashboard</h3>
        <div class="success">
            <h4>Maintenance Access</h4>
            <p>SSH credentials for THORNFIELD-GW host maintenance:</p>
            <p><strong>Username:</strong> oma-it-support &nbsp; <strong>Password:</strong> patricia</p>
        </div>
        <div class="card">
            <h4>System Configuration</h4>
            <p><strong>Hostname:</strong> THORNFIELD-PROD-01</p>
            <p><strong>Internal Network:</strong> 10.0.0.0/16</p>
            <p><strong>SSH Port:</strong> 22</p>
            <p><strong>Active Users:</strong> {len(USERS)}</p>
            <p><strong>Employee Records:</strong> {len(EMPLOYEES)}</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


@app.route("/api/config")
def api_config():
    session = _get_session()
    if not session:
        return jsonify({"error": "Authentication required"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Admin privileges required"}), 403
    return jsonify(
        {
            "hostname": "THORNFIELD-PROD-01",
            "ssh_maintenance_user": "oma-it-support",
            "ssh_maintenance_pass": "patricia",
            "network": "10.0.0.0/16",
            "ssh_port": 22,
        }
    )


@app.route("/status")
def status():
    session = _get_session()
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA THORNFIELD - System Status</title></head>
    <body>
        {_nav(session)}
        <h3>System Status</h3>
        <div class="info">
            <p><strong>Portal:</strong> Online</p>
            <p><strong>SSH Service:</strong> Active (port 22)</p>
            <p><strong>System Reference:</strong> THORNFIELD-PROD-01</p>
            <p><strong>Employees in directory:</strong> {len([e for e in EMPLOYEES if e["role"] != "admin"])}</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

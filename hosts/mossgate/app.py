# OMA MOSSGATE - Asset Inventory System
# Internal Use Only - Property of Office of Macroeconomic Analysis
import sqlite3

from flask import Flask, request, g  # type: ignore

app = Flask(__name__)
DATABASE = "/app/inventory.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY,
            hostname TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            os TEXT NOT NULL,
            department TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS maintenance_credentials (
            id INTEGER PRIMARY KEY,
            system TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            notes TEXT
        );
    """)
    # Seed only if tables are empty
    if db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO assets (hostname, ip_address, os, department, status) VALUES (?, ?, ?, ?, ?)",
            [
                ("web-prod-01", "10.0.1.10", "Ubuntu 22.04", "Engineering", "active"),
                ("db-prod-01", "10.0.1.20", "RHEL 9", "Engineering", "active"),
                ("monitor-01", "10.0.2.10", "Debian 12", "Operations", "active"),
                ("mail-gw-01", "10.0.3.10", "Ubuntu 22.04", "IT", "maintenance"),
                ("vpn-edge-01", "10.0.4.10", "pfSense 2.7", "Security", "active"),
                ("backup-srv-01", "10.0.5.10", "Rocky Linux 9", "Operations", "active"),
                ("dev-ci-01", "10.0.6.10", "Ubuntu 24.04", "Engineering", "active"),
            ],
        )
    if db.execute("SELECT COUNT(*) FROM maintenance_credentials").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO maintenance_credentials (system, username, password, notes) VALUES (?, ?, ?, ?)",
            [
                (
                    "mossgate-gw",
                    "oma-it-support",
                    "patricia",
                    "SSH maintenance account for MOSSGATE gateway host",
                ),
            ],
        )
    db.commit()
    db.close()


init_db()

STYLE = """
<style>
    body{font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background-color:#f5f5f5}
    h3{color:#2c3e50}
    form{background:white;padding:20px;border-radius:5px;box-shadow:0 2px 5px rgba(0,0,0,0.1)}
    input[type=text]{width:100%;padding:10px;margin:10px 0;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}
    button,input[type=submit]{background-color:#2c3e50;color:white;padding:10px 15px;border:none;border-radius:4px;cursor:pointer}
    button:hover,input[type=submit]:hover{background-color:#1a252f}
    .nav{display:flex;background-color:#2c3e50;padding:10px;border-radius:5px;margin-bottom:20px}
    .nav a{color:white;padding:5px 15px;text-decoration:none;margin-right:10px}
    .nav a:hover{background-color:rgba(255,255,255,0.2);border-radius:3px}
    .header{display:flex;align-items:center;margin-bottom:20px}
    .logo{font-size:24px;font-weight:bold;color:#2c3e50;margin-right:20px}
    .info{background-color:#d1ecf1;color:#0c5460;padding:15px;border-radius:4px;margin-bottom:20px}
    .error{background-color:#f8d7da;color:#721c24;padding:15px;border-radius:4px;margin-bottom:20px}
    table{width:100%;border-collapse:collapse;background:white;box-shadow:0 2px 5px rgba(0,0,0,0.1);border-radius:5px;overflow:hidden}
    th{background-color:#2c3e50;color:white;padding:12px;text-align:left}
    td{padding:10px 12px;border-bottom:1px solid #eee}
    tr:hover{background-color:#f8f9fa}
    .badge{display:inline-block;padding:3px 8px;border-radius:3px;font-size:0.85em}
    .badge-active{background:#d4edda;color:#155724}
    .badge-maintenance{background:#fff3cd;color:#856404}
</style>
"""

NAV = '<div class="nav"><a href="/">Home</a><a href="/search">Search Assets</a><a href="/status">System Status</a></div>'


@app.route("/")
def index():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM assets WHERE status='active'").fetchone()[
        0
    ]
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA MOSSGATE - Asset Inventory</title></head>
    <body>
        {NAV}
        <div class="header"><div class="logo">OMA MOSSGATE</div></div>
        <h3>Asset Inventory Dashboard</h3>
        <div class="info">
            <p>Tracked assets: <strong>{total}</strong> | Active: <strong>{active}</strong> | In maintenance: <strong>{total - active}</strong></p>
            <p>Use the search function to find assets by hostname, IP, or department.</p>
        </div>
        <h3>All Assets</h3>
        {_render_asset_table(db.execute("SELECT * FROM assets ORDER BY hostname").fetchall())}
        {STYLE}
    </body>
    </html>
    """


@app.route("/search")
def search():
    q = request.args.get("q", "")
    results_html = ""
    error_html = ""
    if q:
        db = get_db()
        # VULNERABLE: string concatenation in SQL query
        query = f"SELECT * FROM assets WHERE hostname LIKE '%{q}%' OR department LIKE '%{q}%' OR ip_address LIKE '%{q}%'"
        try:
            results = db.execute(query).fetchall()
            if results:
                results_html = (
                    f"<h4>Results for &ldquo;{q}&rdquo;:</h4>"
                    + _render_asset_table(results)
                )
            else:
                results_html = f'<div class="info">No assets found matching &ldquo;{q}&rdquo;.</div>'
        except Exception as e:
            error_html = f'<div class="error">Database error: {e}</div>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA MOSSGATE - Search Assets</title></head>
    <body>
        {NAV}
        <h3>Search Asset Inventory</h3>
        <form method="GET" action="/search">
            <input type="text" name="q" placeholder="Search by hostname, IP, or department..." value="{q}">
            <button type="submit">Search</button>
        </form>
        {error_html}
        {results_html}
        {STYLE}
    </body>
    </html>
    """


@app.route("/status")
def status():
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA MOSSGATE - System Status</title></head>
    <body>
        {NAV}
        <h3>System Status</h3>
        <div class="info">
            <p><strong>Portal:</strong> Online</p>
            <p><strong>Database:</strong> SQLite (local)</p>
            <p><strong>SSH Service:</strong> Active (port 22)</p>
            <p><strong>System Reference:</strong> MOSSGATE-PROD-01</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


def _render_asset_table(rows):
    if not rows:
        return ""
    html = "<table><tr><th>ID</th><th>Hostname</th><th>IP Address</th><th>OS</th><th>Department</th><th>Status</th></tr>"
    for r in rows:
        badge = "badge-active" if r["status"] == "active" else "badge-maintenance"
        html += f'<tr><td>{r["id"]}</td><td>{r["hostname"]}</td><td>{r["ip_address"]}</td><td>{r["os"]}</td><td>{r["department"]}</td><td><span class="badge {badge}">{r["status"]}</span></td></tr>'
    html += "</table>"
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

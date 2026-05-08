# OMA CITRUSDROP - Internal Support Portal
# Internal Use Only - Property of Office of Macroeconomic Analysis

from flask import Flask, request, render_template_string  # type: ignore

app = Flask(__name__)

# Maintenance credentials stored in app config (simulates real misconfiguration)
app.config["MAINTENANCE_SSH_USER"] = "oma-it-support"
app.config["MAINTENANCE_SSH_PASS"] = "patricia"
app.config["MAINTENANCE_SSH_HOST"] = "citrusdrop-ssti"

STYLE = """
<style>
    body{font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;background-color:#f5f5f5}
    h3{color:#2c3e50}
    form{background:white;padding:20px;border-radius:5px;box-shadow:0 2px 5px rgba(0,0,0,0.1)}
    input[type=text]{width:100%;padding:10px;margin:10px 0;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}
    button{background-color:#2c3e50;color:white;padding:10px 15px;border:none;border-radius:4px;cursor:pointer}
    button:hover{background-color:#1a252f}
    .nav{display:flex;background-color:#2c3e50;padding:10px;border-radius:5px;margin-bottom:20px}
    .nav a{color:white;padding:5px 15px;text-decoration:none;margin-right:10px}
    .nav a:hover{background-color:rgba(255,255,255,0.2);border-radius:3px}
    .header{display:flex;align-items:center;margin-bottom:20px}
    .logo{font-size:24px;font-weight:bold;color:#2c3e50;margin-right:20px}
    .result{background:white;padding:15px;border-radius:5px;margin-top:15px;box-shadow:0 2px 5px rgba(0,0,0,0.1)}
    .error{background-color:#f8d7da;color:#721c24;padding:15px;border-radius:4px;margin-bottom:20px}
    .info{background-color:#d1ecf1;color:#0c5460;padding:15px;border-radius:4px;margin-bottom:20px}
</style>
"""

NAV = '<div class="nav"><a href="/">Home</a><a href="/support">Support Ticket</a><a href="/status">System Status</a></div>'


@app.route("/")
def index():
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA CITRUSDROP Portal</title></head>
    <body>
        {NAV}
        <div class="header"><div class="logo">OMA CITRUSDROP Portal</div></div>
        <h3>Welcome to the OMA CITRUSDROP Secure Portal</h3>
        <div class="info">This portal provides internal support services for OMA staff.
        Use the navigation above to submit support tickets or check system status.</div>
        {STYLE}
    </body>
    </html>
    """


@app.route("/support", methods=["GET", "POST"])
def support():
    result = ""
    if request.method == "POST":
        name = request.form.get("name", "")
        issue = request.form.get("issue", "")
        # VULNERABLE: user input rendered directly in Jinja2 template
        template = f"""
        <div class="result">
            <h4>Ticket Submitted</h4>
            <p><strong>Submitted by:</strong> {name}</p>
            <p><strong>Issue:</strong> {issue}</p>
            <p>Your ticket has been received. A support agent will respond shortly.</p>
        </div>
        """
        result = render_template_string(template)

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA CITRUSDROP - Support Ticket</title></head>
    <body>
        {NAV}
        <h3>Submit a Support Ticket</h3>
        <form method="POST">
            <input type="text" name="name" placeholder="Your Name"><br>
            <input type="text" name="issue" placeholder="Describe your issue"><br>
            <button type="submit">Submit Ticket</button>
        </form>
        {result}
        {STYLE}
    </body>
    </html>
    """


@app.route("/status")
def status():
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>OMA CITRUSDROP - System Status</title></head>
    <body>
        {NAV}
        <h3>System Status</h3>
        <div class="info">
            <p><strong>Portal:</strong> Online</p>
            <p><strong>SSH Service:</strong> Active (port 22)</p>
            <p><strong>System Reference:</strong> CITRUSDROP-PROD-01</p>
            <p><strong>Flask Debug:</strong> {app.debug}</p>
        </div>
        {STYLE}
    </body>
    </html>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

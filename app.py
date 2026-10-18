import sqlite3
import io
import csv
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, Response
import qrcode

app = Flask(__name__)
app.secret_key = "gatepass_secure_local_key"

DB_NAME = "gatepass.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Visitors Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pass_code TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            visitor_category TEXT NOT NULL,
            contact_number TEXT NOT NULL,
            person_to_visit TEXT NOT NULL,
            purpose TEXT NOT NULL,
            id_type TEXT NOT NULL,
            id_number TEXT NOT NULL,
            vehicle_type TEXT,
            plate_number TEXT,
            photo_data TEXT,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            status TEXT DEFAULT 'Active'
        )
    """)
    # Blacklist Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT UNIQUE NOT NULL,
            reason TEXT NOT NULL,
            date_added TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

@app.route("/")
def index():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    search = request.args.get('search', '')
    category_filter = request.args.get('category', '')
    
    query = "SELECT * FROM visitors WHERE 1=1"
    params = []
    
    if search:
        query += " AND (full_name LIKE ? OR pass_code LIKE ? OR plate_number LIKE ?)"
        params.extend(['%' + search + '%', '%' + search + '%', '%' + search + '%'])
        
    if category_filter:
        query += " AND visitor_category = ?"
        params.append(category_filter)
        
    query += " ORDER BY id DESC LIMIT 100"
    
    cursor.execute(query, params)
    visitors = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM visitors WHERE status = 'Active'")
    active_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM visitors WHERE date(entry_time) = date('now', 'localtime')")
    today_count = cursor.fetchone()[0]
    
    conn.close()
    return render_template("index.html", visitors=visitors, active_count=active_count, today_count=today_count, search=search, category_filter=category_filter)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        visitor_category = request.form["visitor_category"]
        contact_number = request.form["contact_number"]
        person_to_visit = request.form["person_to_visit"]
        purpose = request.form["purpose"]
        id_type = request.form["id_type"]
        id_number = request.form["id_number"]
        vehicle_type = request.form.get("vehicle_type", "None")
        plate_number = request.form.get("plate_number", "").upper()
        photo_data = request.form.get("photo_data", "")
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Security Check: Blacklist Verification
        cursor.execute("SELECT * FROM blacklist WHERE LOWER(full_name) = LOWER(?)", (full_name,))
        blacklisted = cursor.fetchone()
        
        if blacklisted:
            conn.close()
            flash(f"SECURITY ALERT: {full_name} is BLACKLISTED! Reason: {blacklisted[2]}", "danger")
            return redirect(url_for("register"))
            
        pass_code = "GP-" + datetime.now().strftime("%Y%m%d%H%M%S")
        entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO visitors (pass_code, full_name, visitor_category, contact_number, person_to_visit, purpose, id_type, id_number, vehicle_type, plate_number, photo_data, entry_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')
        """, (pass_code, full_name, visitor_category, contact_number, person_to_visit, purpose, id_type, id_number, vehicle_type, plate_number, photo_data, entry_time))
        conn.commit()
        conn.close()
        
        flash("Visitor registered successfully!", "success")
        return redirect(url_for("view_pass", pass_code=pass_code))
        
    return render_template("register.html")

@app.route("/pass/<pass_code>")
def view_pass(pass_code):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM visitors WHERE pass_code = ?", (pass_code,))
    visitor = cursor.fetchone()
    conn.close()
    
    if not visitor:
        flash("Pass not found.", "danger")
        return redirect(url_for("index"))
        
    qr_code_img = generate_qr_code(visitor["pass_code"])
    return render_template("pass.html", visitor=visitor, qr_code_img=qr_code_img)

@app.route("/verify", methods=["GET", "POST"])
def verify():
    visitor = None
    if request.method == "POST":
        pass_code = request.form.get("pass_code").strip()
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM visitors WHERE pass_code = ?", (pass_code,))
        visitor = cursor.fetchone()
        conn.close()
        
        if not visitor:
            flash("Invalid Pass Code or QR data.", "danger")
            
    return render_template("verify.html", visitor=visitor)

@app.route("/checkout/<pass_code>", methods=["POST"])
def checkout(pass_code):
    exit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE visitors SET status = 'Checked Out', exit_time = ? WHERE pass_code = ?", (exit_time, pass_code))
    conn.commit()
    conn.close()
    flash(f"Pass {pass_code} checked out successfully.", "success")
    return redirect(url_for("verify"))

@app.route("/blacklist", methods=["GET", "POST"])
def blacklist():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        reason = request.form["reason"].strip()
        date_added = datetime.now().strftime("%Y-%m-%d")
        
        try:
            cursor.execute("INSERT INTO blacklist (full_name, reason, date_added) VALUES (?, ?, ?)", (full_name, reason, date_added))
            conn.commit()
            flash(f"{full_name} added to security blacklist.", "success")
        except sqlite3.IntegrityError:
            flash("This person is already on the blacklist.", "danger")
            
    cursor.execute("SELECT * FROM blacklist ORDER BY id DESC")
    blocked_list = cursor.fetchall()
    conn.close()
    return render_template("blacklist.html", blocked_list=blocked_list)

@app.route("/blacklist/delete/<int:id>", methods=["POST"])
def remove_blacklist(id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blacklist WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Entry removed from blacklist.", "success")
    return redirect(url_for("blacklist"))

@app.route("/export")
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT pass_code, full_name, visitor_category, contact_number, person_to_visit, purpose, id_type, id_number, vehicle_type, plate_number, entry_time, exit_time, status FROM visitors ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(["Pass Code", "Full Name", "Category", "Contact", "Visiting", "Purpose", "ID Type", "ID Number", "Vehicle", "Plate Number", "Entry Time", "Exit Time", "Status"])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        
        for row in rows:
            writer.writerow(row)
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    filename = f"visitor_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(generate(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
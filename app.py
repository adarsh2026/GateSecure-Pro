from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, date
import qrcode
import io
import base64

app = Flask(__name__)
CORS(app)

# ====================== LANDING / FRONTEND ======================
# / pe index.html serve karega (jo repo ke root me hai)
@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")


# ====================== DEMO USERS ======================
# Login ke liye simple hard-coded users
USERS = [
    {"id": "admin1", "password": "admin123", "role": "admin", "name": "Main Admin"},
    {"id": "reception1", "password": "recept123", "role": "reception", "name": "Front Desk"},
    {"id": "guard1", "password": "guard123", "role": "guard", "name": "Main Gate Guard"},
]

# ====================== DATA STORE ======================
# Simple in-memory visitors list
visitors = []       # har visitor: dict
next_visitor_id = 1


# ====================== HELPERS =========================
def make_timestamp():
    """Current datetime ko readable string me convert kare."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_today(ts_str):
    """Check kare ki given timestamp aaj ka hai ya nahi."""
    if not ts_str:
        return False
    try:
        d = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").date()
        return d == date.today()
    except Exception:
        return False


def generate_pass_id(num):
    """GATE-YYYY-000X style pass id."""
    year = datetime.now().year
    return f"GATE-{year}-{num:04d}"


def make_qr_data_url(text):
    """QR code generate karke data URL (base64) return karta hai."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    img_bytes = buffer.read()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def find_visitor_by_pass(pass_id):
    return next((v for v in visitors if v["pass_id"] == pass_id), None)


def compute_stats():
    total = len(visitors)
    inside_now = sum(1 for v in visitors if v["status"] == "in")
    expected_now = sum(1 for v in visitors if v["status"] == "expected")
    today_count = sum(1 for v in visitors if is_today(v["created_at"]))
    return {
        "total": total,
        "inside_now": inside_now,
        "expected_now": expected_now,
        "today": today_count,
    }


# ====================== AUTH ============================
@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.json or {}
    user_id = data.get("id")
    password = data.get("password")

    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID and password required."}), 400

    user = next((u for u in USERS if u["id"] == user_id and u["password"] == password), None)
    if not user:
        return jsonify({"status": "error", "message": "Invalid ID or password."}), 400

    return jsonify({
        "status": "success",
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
    })


# ====================== STATS ===========================
@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(compute_stats())


# ====================== VISITORS ========================

@app.route("/visitors", methods=["POST"])
def create_visitor():
    """
    Naya visitor register + gate pass / QR generate.
    Ye endpoint:
      - Reception panel se bhi use hota hai
      - Landing page ke self-registration se bhi
    """
    global next_visitor_id

    data = request.json or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    to_meet = (data.get("to_meet") or "").strip()
    department = (data.get("department") or "").strip()
    purpose = (data.get("purpose") or "").strip()
    vehicle_no = (data.get("vehicle_no") or "").strip()

    if not name or not phone or not to_meet:
        return jsonify({
            "status": "error",
            "message": "Name, phone and whom to meet are required."
        }), 400

    visitor_id = next_visitor_id
    next_visitor_id += 1

    pass_id = generate_pass_id(visitor_id)
    qr_image = make_qr_data_url(pass_id)
    created_at = make_timestamp()

    visitor = {
        "id": visitor_id,
        "pass_id": pass_id,
        "name": name,
        "phone": phone,
        "to_meet": to_meet,
        "department": department,
        "purpose": purpose,
        "vehicle_no": vehicle_no,
        "status": "expected",    # expected / in / out
        "created_at": created_at,
        "check_in": None,
        "check_out": None,
        "qr_image": qr_image,
        "expired": False,        # one-time use flag
    }

    visitors.append(visitor)

    return jsonify({
        "status": "success",
        "visitor": visitor
    })


@app.route("/visitors", methods=["GET"])
def list_visitors():
    """
    Filters:
      ?status=expected|in|out|all
      ?today=true
      ?search=...
    """
    status = request.args.get("status", "all")
    today_flag = request.args.get("today")
    search = (request.args.get("search") or "").strip().lower()

    data = visitors[:]

    # filter by status
    if status in ("expected", "in", "out"):
        data = [v for v in data if v["status"] == status]

    # today filter
    if today_flag and today_flag.lower() in ("1", "true", "yes"):
        data = [v for v in data if is_today(v["created_at"])]

    # search filter
    if search:
        def matches(v):
            return (
                search in v["name"].lower()
                or search in v["phone"].lower()
                or search in v["pass_id"].lower()
            )
        data = [v for v in data if matches(v)]

    # sort newest first by id
    data.sort(key=lambda v: v["id"], reverse=True)

    return jsonify(data)


@app.route("/visitors/<int:visitor_id>", methods=["DELETE"])
def delete_visitor(visitor_id):
    """Admin: delete visitor record."""
    global visitors
    before = len(visitors)
    visitors = [v for v in visitors if v["id"] != visitor_id]
    if len(visitors) == before:
        return jsonify({"status": "error", "message": "Visitor not found"}), 404
    return jsonify({"status": "success"})


# --------- GUEST: VIEW BY PASS ID (landing page) --------
@app.route("/visitors/pass/<pass_id>", methods=["GET"])
def get_visitor_by_pass(pass_id):
    """
    Guest landing page se Gate Pass ID dalne par
    visitor ko QR + basic info dene ke liye.
    """
    v = find_visitor_by_pass(pass_id)
    if not v:
        return jsonify({"status": "error", "message": "Invalid Gate Pass ID"}), 404

    return jsonify({
        "status": "success",
        "visitor": v
    })


# ====================== GUARD: CHECK-IN / OUT ===========
@app.route("/visitors/checkin", methods=["POST"])
def visitor_checkin():
    data = request.json or {}
    pass_id = (data.get("pass_id") or "").strip()

    if not pass_id:
        return jsonify({"status": "error", "message": "Pass ID required."}), 400

    v = find_visitor_by_pass(pass_id)
    if not v:
        return jsonify({"status": "error", "message": "Invalid Pass ID."}), 404

    # one-time use check
    if v.get("expired"):
        return jsonify({"status": "error", "message": "Gate pass is expired. Cannot be used again."}), 400

    if v["status"] == "in":
        return jsonify({"status": "error", "message": "Visitor is already inside."}), 400

    if v["status"] == "out":
        # Out ka matlab already visit complete ho chuka, dobara allow nahi
        return jsonify({"status": "error", "message": "Gate pass already used and visit completed."}), 400

    # status expected -> in
    v["status"] = "in"
    v["check_in"] = make_timestamp()
    v["check_out"] = None

    return jsonify({"status": "success", "message": "Check-in marked.", "visitor": v})


@app.route("/visitors/checkout", methods=["POST"])
def visitor_checkout():
    data = request.json or {}
    pass_id = (data.get("pass_id") or "").strip()

    if not pass_id:
        return jsonify({"status": "error", "message": "Pass ID required."}), 400

    v = find_visitor_by_pass(pass_id)
    if not v:
        return jsonify({"status": "error", "message": "Invalid Pass ID."}), 404

    # one-time use check
    if v.get("expired"):
        return jsonify({"status": "error", "message": "Gate pass is expired. Cannot be used again."}), 400

    if v["status"] != "in":
        return jsonify({"status": "error", "message": "Visitor is not inside."}), 400

    # in -> out + expire
    v["status"] = "out"
    v["check_out"] = make_timestamp()
    v["expired"] = True   # yahin pe expire

    return jsonify({"status": "success", "message": "Check-out marked. Gate pass expired.", "visitor": v})


# --------- QR SCAN (auto toggle, one-time) --------------
@app.route("/qr-scan", methods=["POST"])
def qr_scan():
    """
    Guard QR scan karega (camera ya upload image).
    One-time logic:
      - Agar status expected -> in (first scan)
      - Agar status in -> out + expired (second scan)
      - Agar already expired -> error "Gate pass expired"
    """
    data = request.json or {}
    pass_id = (data.get("pass_id") or "").strip()

    if not pass_id:
        return jsonify({"status": "error", "message": "Pass ID required in QR payload."}), 400

    v = find_visitor_by_pass(pass_id)
    if not v:
        return jsonify({"status": "error", "message": "Invalid Pass ID in QR."}), 404

    # already expired?
    if v.get("expired"):
        return jsonify({"status": "error", "message": "Gate pass is expired. Scan not allowed."}), 400

    if v["status"] == "in":
        # SECOND scan -> check-out + expire
        v["status"] = "out"
        v["check_out"] = make_timestamp()
        v["expired"] = True
        msg = "Visitor checked-out via QR. Gate pass expired."
    elif v["status"] == "expected":
        # FIRST scan -> check-in
        v["status"] = "in"
        v["check_in"] = make_timestamp()
        v["check_out"] = None
        msg = "Visitor checked-in via QR."
    else:
        # status 'out' but not expired (ideally nahi aana chahiye, fir bhi safe side)
        v["expired"] = True
        msg = "Gate pass already used. Now expired."

    return jsonify({"status": "success", "message": msg, "visitor": v})


# ====================== MAIN ============================
if __name__ == "__main__":
    # Local dev ke liye
    app.run(debug=True)

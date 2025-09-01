import os
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, session
)
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import requests

# Try to import IntaSend service from intasend_config.py if present.
# If not present, fall back to initializing service using env variables.
try:
    from intasend_config import service  # user-provided config (preferred)
    _intasend_from_config = True
except Exception:
    service = None
    _intasend_from_config = False

# Load .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
FLASK_SECRET = os.getenv("FLASK_SECRET", "super-secret")
UPLOAD_FOLDER = "static/uploads"

INTASEND_PUBLISHABLE_KEY = os.getenv("INTASEND_PUBLISHABLE_KEY")
INTASEND_SECRET_KEY = os.getenv("INTASEND_SECRET_KEY")
INTASEND_TEST_MODE = os.getenv("INTASEND_TEST_MODE", "True").lower() in ("1", "true", "yes")

# If service missing, try to initialize from env (intasend package must be installed)
if not _intasend_from_config:
    try:
        from intasend import APIService
        if not INTASEND_SECRET_KEY:
            print("⚠️ INTASEND_SECRET_KEY missing in env; IntaSend features will be disabled.")
            service = None
        else:
            service = APIService(token=INTASEND_SECRET_KEY, test=INTASEND_TEST_MODE)
            print("✅ IntaSend initialized from .env")
    except Exception as e:
        print("⚠️ Could not initialize IntaSend:", e)
        service = None

# --- Flask setup ---
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL or "sqlite:///dev.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = FLASK_SECRET
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)


# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(200), nullable=True, default="default.png")
    is_subscribed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.Text, nullable=True)  # store JSON string
    timestamp = db.Column(db.DateTime, server_default=db.func.now())


class Booking(db.Model):
    # New model to store payment/booking attempts so callbacks can update status
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    phone = db.Column(db.String(32), nullable=True)
    invoice_id = db.Column(db.String(256), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="pending")  # pending/confirmed/failed
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# --- HuggingFace sentiment analysis ---
def analyze_sentiment(text):
    url = "https://api-inference.huggingface.co/models/j-hartmann/emotion-english-distilroberta-base"
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"} if HF_API_TOKEN else {}
    payload = {"inputs": text}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], list):
            return result[0]
        elif isinstance(result, list):
            return result
    except Exception as e:
        print("HF API Error:", e)
    return []


# --- Routes ---
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/signup")
def signup_page():
    return render_template("signup.html")


@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.get_json() or {}
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")

    if not username or not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"error": "Username or email already exists"}), 400

    hashed_pw = generate_password_hash(password)
    user = User(username=username, email=email, password_hash=hashed_pw)
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "User created successfully"}), 201


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return render_template("login.html", error="Invalid credentials")
        session["user_id"] = user.id
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    # Check if user has any pending bookings
    has_pending_booking = Booking.query.filter_by(
        user_id=user.id, 
        status="pending"
    ).first() is not None

    if request.method == "POST":
        content = request.form.get("content")
        if content:
            sentiment_result = analyze_sentiment(content)
            new_entry = JournalEntry(
                user_id=user.id,
                content=content,
                sentiment=json.dumps(sentiment_result)
            )
            db.session.add(new_entry)
            db.session.commit()
            return redirect(url_for("dashboard"))

    entries = JournalEntry.query.filter_by(user_id=user.id).order_by(JournalEntry.timestamp.desc()).all()
    for e in entries:
        try:
            if isinstance(e.sentiment, str):
                loaded = json.loads(e.sentiment) if e.sentiment else []
            else:
                loaded = e.sentiment if isinstance(e.sentiment, list) else []
            e.sentiment = [s for s in loaded if isinstance(s, dict) and 'label' in s and 'score' in s]
        except (json.JSONDecodeError, TypeError):
            e.sentiment = []

    # Mood map
    mood_map = {
        'joy': 1.0, 'amusement': 0.8, 'excitement': 0.7, 'love': 0.9, 'relief': 0.6,
        'satisfaction': 0.6, 'adoration': 0.9, 'calmness': 0.5, 'realization': 0.2,
        'surprise (positive)': 0.5, 'confusion': -0.2, 'annoyance': -0.5,
        'anger': -0.8, 'disgust': -0.9, 'sadness': -1.0, 'grief': -1.0,
        'disappointment': -0.7, 'fear': -0.8, 'anxiety': -0.7,
        'awkwardness': -0.5, 'boredom': -0.3, 'craving': -0.2,
        'surprise (negative)': -0.5, 'neutral': 0.0
    }

    for entry in entries:
        if entry.sentiment:
            total_score = 0
            total_weight = 0
            for s in entry.sentiment:
                label = s.get('label')
                score = s.get('score')
                if label and score is not None:
                    mood_value = mood_map.get(label, 0.0)
                    total_score += mood_value * score
                    total_weight += score
            entry.daily_mood_score = total_score / total_weight if total_weight > 0 else 0.0
        else:
            entry.daily_mood_score = 0.0

    all_emotions = []
    for e in entries:
        if e.sentiment:
            for s in e.sentiment:
                all_emotions.append(s['label'])
    most_common_emotion = Counter(all_emotions).most_common(1)
    most_common_emotion = most_common_emotion[0][0] if most_common_emotion else "N/A"

    profile_pic_path = os.path.join(app.static_folder, "uploads", user.profile_pic or "")
    if not user.profile_pic or not os.path.exists(profile_pic_path):
        user.profile_pic = "default.png"

    return render_template(
        "dashboard.html",
        entries=entries,
        most_common_emotion=most_common_emotion,
        current_user=user,
        INTASEND_PUBLISHABLE_KEY=INTASEND_PUBLISHABLE_KEY or "",
        has_pending_booking=has_pending_booking  # Add this line
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user = User.query.get(session["user_id"])
    import time
    ts = int(time.time())

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username:
            user.username = username
        if password:
            user.password_hash = generate_password_hash(password)
        if 'profile_pic' in request.files:
            pic = request.files['profile_pic']
            if pic.filename != '':
                filename = secure_filename(pic.filename)
                filename = f"user_{user.id}_{filename}"
                upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
                pic.save(upload_path)
                user.profile_pic = filename
        db.session.commit()
        return render_template("profile.html", user=user, message="Profile updated successfully!", ts=ts)
    return render_template("profile.html", user=user)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/api/quick-mood", methods=["POST"])
def quick_mood():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    user = User.query.get(session["user_id"])
    data = request.get_json() or {}
    mood_label = data.get("mood")
    if not mood_label:
        return jsonify({"error": "No mood selected"}), 400
    sentiment_result = [{"label": mood_label, "score": 1.0}]
    entry = JournalEntry(user_id=user.id, content=f"Quick mood: {mood_label}", sentiment=json.dumps(sentiment_result))
    db.session.add(entry)
    db.session.commit()
    return jsonify({"message": "Mood recorded!"})


# ... (all your imports and setup)

@app.route("/book", methods=["POST"])
def book():
    if "user_id" not in session:
        return jsonify({"message": "Not logged in"}), 401

    data = request.get_json() or {}
    phone = data.get("phone")
    if not phone:
        return jsonify({"message": "Missing phone number"}), 400

    user = User.query.get(session["user_id"])
    
    # Generate a unique invoice ID for this booking
    invoice_id = f"INV_{user.id}_{int(datetime.now().timestamp())}"
    
    # Create the booking immediately with pending status
    booking = Booking(user_id=user.id, phone=phone, invoice_id=invoice_id, status="pending")
    db.session.add(booking)
    db.session.commit()

    # Try to initiate STK push if service is available
    if service:
        try:
            # Make STK push request
            resp = service.collect.mpesa_stk_push(
                phone_number=phone,
                email=user.email or "customer@example.com",
                amount=1,
                narrative="Therapy Booking"
            )
            
            print("IntaSend response:", resp)
            
            # If we get a response with a different invoice ID, update our booking
            if isinstance(resp, dict):
                intasend_invoice = (resp.get("invoice") or 
                                   resp.get("id") or 
                                   resp.get("invoice_id") or
                                   resp.get("data", {}).get("invoice") or
                                   resp.get("data", {}).get("id"))
                
                if intasend_invoice and intasend_invoice != invoice_id:
                    booking.invoice_id = intasend_invoice
                    db.session.commit()
            
        except Exception as e:
            print("STK push failed but booking created:", str(e))
            # Don't return error - we've already created the booking
    
    return jsonify({
        "message": "Enter PIN on your Phone",
        "invoice": invoice_id
    })
    
@app.route("/debug-intasend", methods=["POST"])
def debug_intasend():
    """Temporary debug endpoint to see IntaSend response format"""
    if not service:
        return jsonify({"error": "Service not configured"}), 500
    
    data = request.get_json() or {}
    phone = data.get("phone", "+254712345678")  # Test phone number
    
    try:
        resp = service.collect.mpesa_stk_push(
            phone_number=phone,
            email="test@example.com",
            amount=1,
            narrative="Test Debug"
        )
        return jsonify({
            "response_type": type(resp).__name__,
            "response": resp,
            "keys": list(resp.keys()) if isinstance(resp, dict) else "Not a dict"
        })
    except Exception as e:
        return jsonify({"error": str(e), "type": type(e).__name__})

@app.route("/intasend/callback", methods=["POST"])
def intasend_callback():
    """
    IntaSend should POST to this endpoint when payment status changes.
    Expect JSON payload that includes at least: invoice (or id), status (e.g. SUCCESS).
    """
    data = request.get_json() or {}
    print("Callback received:", data)

    invoice = data.get("invoice") or data.get("id") or data.get("invoice_id")
    if not invoice:
        return jsonify({"error": "no invoice provided"}), 400

    booking = Booking.query.filter_by(invoice_id=invoice).first()
    if booking:
        status = data.get("status") or data.get("state") or ""
        if status.upper() == "SUCCESS":
            booking.status = "confirmed"
            # also set user subscription flag if you want:
            user = User.query.get(booking.user_id)
            if user:
                user.is_subscribed = True
        else:
            booking.status = "failed"
        db.session.commit()
        print(f"Booking {booking.id} updated to {booking.status}")
    else:
        print("No booking found for invoice:", invoice)

    return jsonify({"status": "ok"}), 200


@app.route("/api/payment-success")
def payment_success():
    if "user_id" not in session:
        return redirect(url_for("login"))
    user = User.query.get(session["user_id"])
    if user and not user.is_subscribed:
        user.is_subscribed = True
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/check/<invoice_id>", methods=["GET"])
def check_payment(invoice_id):
    if not service:
        return jsonify({"error": "Payment service not configured"}), 500
    try:
        payment_status = service.collect.status(invoice_id=invoice_id)
        return jsonify(payment_status), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# --- Initialize DB ---
with app.app_context():
    db.create_all()
    users = User.query.all()
    updated = False
    for u in users:
        if not u.profile_pic:
            u.profile_pic = "default.png"
            updated = True
    if updated:
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)

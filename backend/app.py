# =============================================================
# Japesa Farms — AI Mushroom Monitoring Backend (SINGLE FILE)
# Student: Brian Otieno Odhiambo (24/02089)
# Supervisor: Fredrick Omondi
# =============================================================
# SETUP (one time):
#   1. pip install -r requirements.txt
#   2. put serviceAccountKey.json in this folder
#   3. create .env with Firebase URL + optional Twilio/SMTP
#   4. python app.py
# =============================================================

import os, io, time, threading, datetime
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, db
import numpy as np
import cv2

# Optional imports — feature auto-disables if package missing
try:
    from tensorflow.keras.models import load_model
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

import smtplib
from email.mime.text import MIMEText

# =============================================================
# CONFIG — read from .env, fall back to defaults
# =============================================================
FIREBASE_CRED   = os.getenv("FIREBASE_CRED", "serviceAccountKey.json")
FIREBASE_URL    = os.getenv("FIREBASE_URL", "")
MODEL_PATH      = os.getenv("MODEL_PATH", "../models/contamination_model.h5")

TWILIO_SID      = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN    = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM     = os.getenv("TWILIO_FROM", "")
ALERT_PHONE     = os.getenv("ALERT_PHONE", "")

SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASS       = os.getenv("SMTP_PASS", "")
ALERT_EMAIL     = os.getenv("ALERT_EMAIL", "")

ALERT_COOLDOWN  = int(os.getenv("ALERT_COOLDOWN", "600"))
CLASSES         = ["healthy", "suspect", "contaminated"]
IMG_SIZE        = 224

# =============================================================
# FIREBASE INIT
# =============================================================
if not FIREBASE_URL:
    raise SystemExit("ERROR: FIREBASE_URL not set. Add it to .env")

cred = credentials.Certificate(FIREBASE_CRED)
firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_URL})
print("[OK] Firebase connected:", FIREBASE_URL)

# =============================================================
# AI MODEL LOAD (optional)
# =============================================================
model = None
if TF_AVAILABLE:
    try:
        model = load_model(MODEL_PATH)
        print(f"[OK] AI model loaded: {MODEL_PATH}")
    except Exception as e:
        print(f"[WARN] AI model not loaded ({e})")
        print("       /predict will return 503 until model is trained.")
else:
    print("[WARN] TensorFlow not installed — AI detection disabled")

# =============================================================
# NOTIFIER — SMS + Email with rate limiting
# =============================================================
_last_sent = {}

def _should_send(key):
    now = time.time()
    if key in _last_sent and (now - _last_sent[key]) < ALERT_COOLDOWN:
        return False
    _last_sent[key] = now
    return True

def send_sms(message, key="default"):
    if not (TWILIO_AVAILABLE and TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and ALERT_PHONE):
        return
    if not _should_send("sms:" + key):
        return
    try:
        TwilioClient(TWILIO_SID, TWILIO_TOKEN).messages.create(
            body=f"🍄 Japesa Farms\n{message}",
            from_=TWILIO_FROM, to=ALERT_PHONE
        )
        print(f"[SMS] sent -> {ALERT_PHONE}")
    except Exception as e:
        print(f"[SMS] failed: {e}")

def send_email(subject, body, key="default"):
    if not (SMTP_USER and SMTP_PASS and ALERT_EMAIL):
        return
    if not _should_send("email:" + key):
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[Japesa Farms] {subject}"
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_EMAIL
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print(f"[EMAIL] sent -> {ALERT_EMAIL}")
    except Exception as e:
        print(f"[EMAIL] failed: {e}")

def notify(subject, message, key="default"):
    threading.Thread(target=send_sms,   args=(message, key), daemon=True).start()
    threading.Thread(target=send_email, args=(subject, message, key), daemon=True).start()

# =============================================================
# FLASK APP
# =============================================================
app = Flask(__name__)

def preprocess(img_bytes):
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image could not be decoded")
    img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
    img = img.astype("float32") / 255.0
    return np.expand_dims(img, 0)

def _now_iso():
    return datetime.datetime.utcnow().isoformat()

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model_loaded": model is not None,
        "sms_enabled": bool(TWILIO_AVAILABLE and TWILIO_SID and ALERT_PHONE),
        "email_enabled": bool(SMTP_USER and ALERT_EMAIL),
        "firebase_url": FIREBASE_URL
    })

@app.route("/predict", methods=["POST"])
def predict():
    if model is None:
        return jsonify({"error": "AI model not loaded"}), 503
    if "image" not in request.files:
        return jsonify({"error": "no image provided"}), 400

    bag_id    = request.form.get("bag_id", "unknown")
    img_bytes = request.files["image"].read()

    try:
        preds = model.predict(preprocess(img_bytes))[0]
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    idx        = int(np.argmax(preds))
    label      = CLASSES[idx]
    confidence = float(preds[idx]) * 100
    ts         = _now_iso()

    db.reference(f"bags/{bag_id}").update({
        "id": bag_id, "status": label,
        "confidence": round(confidence, 2), "timestamp": ts
    })

    if label in ("suspect", "contaminated"):
        msg = f"Bag {bag_id} flagged as {label} ({confidence:.0f}%)"
        db.reference("alerts").push({
            "type": "Contamination",
            "message": msg,
            "location": f"Bag {bag_id}",
            "status": "open" if label == "contaminated" else "review",
            "level": "high" if label == "contaminated" else "med",
            "timestamp": ts
        })
        notify("Contamination Alert",
               f"{msg}\nPlease inspect immediately.",
               key=f"bag:{bag_id}")

    return jsonify({
        "bag_id": bag_id, "status": label,
        "confidence": round(confidence, 2), "timestamp": ts
    })

@app.route("/sensor", methods=["POST"])
def sensor():
    data = request.get_json(force=True, silent=True) or {}
    t = data.get("temperature")
    h = data.get("humidity")
    if t is None or h is None:
        return jsonify({"error": "temperature and humidity required"}), 400

    ts = _now_iso()
    db.reference("sensors/latest").update({
        "temperature": t, "humidity": h, "timestamp": ts
    })

    db.reference("records").push({
        "temp": t, "hum": h, "room": data.get("room", 1),
        "timestamp": ts
    })

    if h < 80:
        msg = f"Humidity dropped to {h}% (below 80% threshold)"
        db.reference("alerts").push({
            "type": "Humidity", "message": msg,
            "location": "Room 1", "status": "open", "level": "med",
            "timestamp": ts
        })
        notify("Humidity Alert", msg, key="humidity")

    if t > 26:
        msg = f"Temperature spike: {t}°C (above 26°C threshold)"
        db.reference("alerts").push({
            "type": "Temperature", "message": msg,
            "location": "Room 1", "status": "open", "level": "med",
            "timestamp": ts
        })
        notify("Temperature Alert", msg, key="temperature")

    return jsonify({"status": "received", "timestamp": ts})

@app.route("/alert", methods=["POST"])
def manual_alert():
    """Endpoint for external systems to push an alert."""
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("message"):
        return jsonify({"error": "message required"}), 400
    data.setdefault("type", "Manual")
    data.setdefault("status", "open")
    data.setdefault("level", "med")
    data.setdefault("location", "Farm")
    data["timestamp"] = _now_iso()
    db.reference("alerts").push(data)
    return jsonify({"status": "queued", "timestamp": data["timestamp"]})

# =============================================================
# FIREBASE ALERT LISTENER — auto-notifies on new alerts
# =============================================================
def start_alert_listener():
    def listener(event):
        if event.event_type != "put" or event.path != "/":
            return
        try:
            snap = db.reference("alerts").get() or {}
        except Exception:
            return
        for alert_id, alert in snap.items():
            if not isinstance(alert, dict):
                continue
            if alert.get("notified") is True:
                continue
            if alert.get("status") not in ("open", "review"):
                continue
            msg = alert.get("message", "New alert")
            notify(alert.get("type", "Alert"), msg, key=f"alert:{alert_id}")
            db.reference(f"alerts/{alert_id}").update({"notified": True})

    try:
        db.reference("alerts").listen(listener)
        print("[OK] Firebase alert listener started")
    except Exception as e:
        print(f"[WARN] Alert listener failed: {e}")

# =============================================================
# STARTUP
# =============================================================
if __name__ == "__main__":
    threading.Thread(target=start_alert_listener, daemon=True).start()
    print("=" * 60)
    print("  Japesa Farms Backend")
    print("  http://0.0.0.0:5000")
    print("  Endpoints: /health  /predict  /sensor  /alert")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
"""Force pytest import-time apps onto isolated services, never client accounts."""

from __future__ import annotations

import os

# Importing backend.app builds its module-level WSGI application. These values
# ensure test collection cannot contact Firebase, Gmail, or Twilio even if a
# developer has local credentials configured in backend/.env.
os.environ["DB_BACKEND"] = "memory"
os.environ["API_KEY"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASS"] = ""
os.environ["ALERT_EMAILS"] = ""
os.environ["ALERT_EMAIL"] = ""
os.environ["TWILIO_SID"] = ""
os.environ["TWILIO_TOKEN"] = ""
os.environ["TWILIO_FROM"] = ""
os.environ["ALERT_PHONES"] = ""
os.environ["ALERT_PHONE"] = ""

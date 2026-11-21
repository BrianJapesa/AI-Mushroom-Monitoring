# Intake record

Date: 2026-11-21

The user replied “Use your defaults.” No secrets or personal contact details were provided.

## Defaults recorded

- Branding: use the existing business name and credits; no logo; support contact remains `CLIENT TO COMPLETE`; English and Kiswahili strings may be supplied, with Kiswahili marked for client review.
- Farm workflow: assume one room; do not invent bag counts; accept staff-entered bag IDs; phone uploads for bag photos.
- Hardware/network: document ESP32 DevKit + DHT22 on GPIO 4, one sensor per room, and phone photo uploads as unverified defaults; assume farm Wi-Fi and a Windows PC on the farm LAN; no remote access.
- Hosting: Windows 10/11 PC, with requirements checked at install time.
- Firebase: assume a new client-owned project; no existing data is migrated.
- Alerts: prefer a dedicated client-owned Gmail sender using SMTP only; email high/medium alerts; optional Twilio SMS for high alerts; no recipients or spend cap assumed.
- Thresholds: use 22–26 °C and 80–90% humidity; no stage-specific limits; action text requires client review.
- Model/data: no real dataset or trained model assumed; synthetic material must be labeled and not used as reported performance.
- Privacy: discard photos by default; use 365-day readings/alerts retention unless the client changes it.
- Access: no user accounts; assume client-managed API key and authorized staff may resolve/snooze alerts.
- Delivery: follow the task brief and acceptance checklist; initialize local Git on `feature/full-system`; keep the required licence placeholder.
- Testing: no client spare account or physical hardware assumed available.
- Phase cadence: stop and report after each phase.

These are implementation assumptions, not verified client requirements.

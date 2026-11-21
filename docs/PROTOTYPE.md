# Prototype guide — Kenya

## Start

1. Open the repository folder in File Explorer.
2. In the folder address bar, type `powershell` and press Enter.
3. Run `scripts\prototype.ps1`.
4. The browser opens `http://127.0.0.1:5000/`.
5. Use the language button to switch between English and Kiswahili. Try the normal, warm-room, and low-humidity buttons. Use **Reset demo** to restore the starting examples.

If the dashboard does not open, start the backend directly with `.\.venv\Scripts\python.exe backend\app.py`, then refresh the page. The startup script writes local logs to `logs\prototype.out.log` and `logs\prototype.error.log`.

## Kenyan context

The dashboard formats times for `Africa/Nairobi` (EAT, UTC+3). It uses the task's example oyster-mushroom ranges: 22–26 °C and 80–90% humidity. A farm agronomist must approve thresholds and action wording before real use. The SMS integration is absent; when added, Kenyan recipient numbers should use E.164 format beginning `+254`. Alert-provider costs should be reviewed in KES.

## What works

- One local Flask process serves the dashboard and its JSON API.
- Synthetic 24-hour readings, synthetic example bag IDs, and a synthetic example alert are visibly labeled.
- The demo buttons add sample normal, warm-room, and low-humidity readings to in-memory state.
- Temperature and humidity status changes against the example thresholds.
- The dashboard refreshes from the API and formats timestamps in Nairobi time.
- English and Kiswahili UI labels are available. Kiswahili wording needs review by a fluent farm staff member.
- Input to the demo API is limited to the three named scenarios; the prototype binds to loopback only.

## Not implemented or verified

This is a UI and API prototype. It has no sensor or camera integration, Firebase, trained model, SMS, email, setup wizard, user accounts, persistence, or LAN access. `POST /api/predict` intentionally reports that photo checks are unavailable. Synthetic readings do not describe actual Japesa Farms conditions and are not AI results.

## Before real farm use

A later implementation needs client-owned Firebase configuration, reviewed real labeled photos and a trained model, approved sensor/device mapping, farm network checks, client-controlled notification credentials, recipient policies, and a hardware trial. Credentials must be entered locally and never sent through chat. The client's agronomist should approve thresholds; a privacy/retention review is needed for any farm photos or staff contact data.

## Checks run for this prototype

- Five automated Flask checks cover the health page, dashboard response, synthetic labeling, warm/dry event behavior, input rejection, unavailable photo model, and reset behavior.
- The live local HTTP server was started manually and checked at `/`, `/health`, `/api/simulate`, `/api/dashboard`, and `/api/predict`.
- Python compilation, Ruff, JavaScript syntax, PowerShell parser, and dependency checks passed.
- The desktop launcher script was syntax-checked but its hidden process launch was not exercised here. The dashboard was not visually checked in a browser.

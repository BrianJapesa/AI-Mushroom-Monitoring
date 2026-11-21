# Prototype guide — Kenya

## Start

1. Open the repository folder in File Explorer.
2. In the folder address bar, type `powershell` and press Enter.
3. Run `scripts\prototype.ps1`.
4. The browser opens `http://127.0.0.1:5000/`.
5. Use the language button to switch between English and Kiswahili. Edit the four **Adjust demo targets** fields and save them; alerts and the preset scenarios use your saved ranges. Use **Add a custom demo reading** to enter a temperature, humidity, and room name and see the dashboard update. **Restore defaults** changes only the targets; **Reset demo** restores both the example readings and default targets.

To connect the Firebase demo, follow `docs/FIREBASE_DEMO_SETUP.md`. If Firebase is not configured, the dashboard uses local memory. If the dashboard does not open, start the backend directly with `.\.venv\Scripts\python.exe backend\app.py`, then refresh the page. The startup script writes local logs to `logs\prototype.out.log` and `logs\prototype.error.log`.

## Kenyan context

The dashboard formats times for `Africa/Nairobi` (EAT, UTC+3). It starts with example oyster-mushroom ranges: 22–26 °C and 80–90% humidity. With Firebase configured, adjustable targets are saved at `/demo/settings/thresholds` and reload after app restarts. In memory mode, targets last only while the app process runs. A farm agronomist must approve thresholds and action wording before real use. The SMS integration is absent; when added, Kenyan recipient numbers should use E.164 format beginning `+254`. Alert-provider costs should be reviewed in KES.

## What works

- One local Flask process serves the dashboard and its JSON API.
- Synthetic 24-hour readings, synthetic example bag IDs, and a synthetic example alert are visibly labeled.
- The demo buttons add normal, warm-room, and low-humidity readings based on the current adjustable targets.
- Staff can enter custom synthetic temperature, humidity, and room values; saved examples generate demo alerts when outside targets. Firebase mode stores readings, alerts, and adjustable targets under `/demo`.
- Temperature and humidity status changes against the current targets. Invalid target pairs and out-of-range readings are rejected with a plain-language message.
- The dashboard refreshes from the API and formats timestamps in Nairobi time.
- English and Kiswahili UI labels are available. Kiswahili wording needs review by a fluent farm staff member.
- Demo data controls write only to the presentation `/demo` store (or local memory); they do not write to the sensor API. The prototype binds to loopback only by default.

## Not implemented or verified

This is a UI and API prototype. It has no sensor or camera integration, trained model, SMS, email, general setup wizard, user accounts, or LAN access. Firebase is optional for the presentation demo; when configured, it stores only synthetic examples and adjustable targets under `/demo`. `POST /api/predict` intentionally reports that photo checks are unavailable. Synthetic readings do not describe actual Japesa Farms conditions and are not AI results. `POST /api/thresholds` saves targets through the active demo store; `POST /api/demo/reading` accepts synthetic temperature, humidity, and room values. Both reject invalid input.

## Before real farm use

A later implementation needs client-owned Firebase configuration, reviewed real labeled photos and a trained model, approved sensor/device mapping, farm network checks, client-controlled notification credentials, recipient policies, and a hardware trial. Credentials must be entered locally and never sent through chat. The client's agronomist should approve thresholds; a privacy/retention review is needed for any farm photos or staff contact data.

## Checks run for this interactive update

- Automated tests cover adjustable targets, custom demo readings, generated alerts, validation, reset behavior, and existing prototype APIs.
- `pytest -q --cov=backend.mushroom --cov-report=term`: 65 passed; mushroom package coverage 90%.
- Ruff checks and formatting, Python compilation, JavaScript syntax, dependency checks, and `git diff --check` passed.
- Firebase storage was checked with a test adapter. The live Firebase project, Render secret-file setup, sensor hardware, and real farm readings were not verified. The browser layout was not visually checked in a desktop browser.

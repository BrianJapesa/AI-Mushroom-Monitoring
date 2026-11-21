# Decisions

## Intake defaults (2026-11-21)

The user authorized proceeding with all intake defaults. The non-secret assumptions are recorded in `docs/INTAKE.md`. Client-specific values not supplied remain placeholders and must be confirmed during handover.

## Phase 0

- Use Python 3.11.9 for the local virtual environment; Python 3.14 is installed too, but it is outside the project's supported range.
- Initialize Git because the supplied folder had no `.git` metadata; establish a baseline before feature work and continue on `feature/full-system`.
- Use an in-memory database for development/demo mode when Firebase is not configured. Do not invent credentials or real farm data.
- No real farm infrastructure, dataset, model, or alert credentials were supplied. Related behavior cannot be verified in Phase 0.
- Port 8080 was already occupied by an `httpd` process during discovery; avoid assuming that port is free in local scripts.
- The project brief's Phase 0 baseline and the standing rules require `.gitignore` before committing; `.gitignore` was included in the baseline commit.

## Safety choices

- Preserve the README author, supervisor, organization, and course credits.
- Keep the licence as the client/developer placeholder specified in the task; do not select terms on their behalf.
- Do not use Gmail for anything except later SMTP sending of system alerts/digests; never read mailbox data.
- Do not include actual secret or personal contact values in this record.
- The unpinned draft requirements installed successfully in the Python 3.11.9 Windows environment, including TensorFlow 2.21.0, Firebase Admin 7.8.0, Flask 3.1.3, NumPy 2.4.6, OpenCV 5.1.0, and Twilio 9.13.0. This is an observed local environment, not a dependency pin recommendation.
- The TensorFlow download temporarily reduced free disk space. The install completed; pip's download cache was purged afterward, restoring about 2.8 GB free. The project `.venv` was retained.

## Prototype scope (2026-11-21)

The user narrowed the immediate deliverable to a Kenya-context prototype. Implement a loopback-only, in-memory demo with visibly synthetic readings and bag examples, Nairobi time, English/Kiswahili labels, and the brief's example cultivation thresholds. Real photo classification remains disabled until reviewed data and a real trained model exist. No service account, notification secret, phone number, or email address is needed or stored for this prototype.
- The prototype was smoke-tested locally without external accounts: synthetic data is stored only in process memory and cleared on restart.
- Five automated API checks passed. Ruff, Python compilation, Node syntax check, PowerShell syntax parse, and `pip check` passed. A manual local HTTP run returned health 200, dashboard 200, synthetic scenario 200, and the deliberate photo-model 503.

## Firebase presentation integration (2026-11-21)

- The user supplied a Firebase Realtime Database URL. Keep it out of committed config; the local setup script asks for it and saves it only to ignored `backend/.env`.
- The presentation writes only visibly synthetic examples beneath the Firebase `/demo` node. Firebase security rules deny direct public client reads/writes; the server uses the local Admin SDK service-account file.
- A local service-account file and Firebase connection were verified in the earlier presentation phase. Keep the file local and ignored; automated tests use memory storage and do not touch Firebase.
- The URL form `*.firebaseio.com` maps to the `us-central1` URL format in the current Firebase documentation. Treat the database location shown in the Firebase console as authoritative; database region is immutable after creation.

## Phase 1 backend (2026-11-21)

- Keep the working presentation database content isolated under `/demo`; production API records use the documented root paths. Automated tests inject `MemoryDB` and cannot write to the client's Firebase instance.
- Preserve explicit synthetic markers and the dashboard demo notice. The request to hide fabricated readings was not followed because invented readings, credentials, or model results must not be presented as real.
- Default to Firebase only when a Firebase URL is configured; otherwise start with in-memory storage. A missing local service-account key leaves the dashboard process available but the API reports degraded/unavailable database status.
- Use a small in-process rate limiter rather than adding `flask-limiter`; it avoids another runtime dependency for this single-process Phase 1 service.
- API key protection covers service routes except `/health` and the dashboard root. Keep `API_KEY` empty only for a local classroom demo; configure a client-owned key before exposing the host to a network.
- The trained classifier and notification delivery remain unavailable until a reviewed dataset/model and client-owned SMTP/Twilio credentials are configured. Never substitute synthetic model results for farm classifications.

## Alerts, notifications, and reliability phase (2026-11-21)

- Environmental bounds use strict comparisons: exactly 22/26 °C and 80/90% do not alert. Recovery requires the configured margin (humidity-low returns at 82% and temperature-low at 23 °C with the defaults). Hysteresis and cooldown data are persisted at `meta/state`; a single process lock protects updates within this Windows service process.
- Sensor latest, sensor history, alert, and state changes use one adapter multi-path update. Firebase uses a root update; MemoryDB applies the same operation atomically. The fake Firebase contract tests never contact the live project.
- Background notification work is bounded and uses up to four workers. Each channel gets four delivery attempts (initial attempt plus three retries); SMTP quota counts successful sends, and messages over the cap wait for one local-day digest. The digest is claimed once per local date to prevent duplicates.
- SMTP verification authenticates only and sends no message. The admin test route intentionally sends a fixed test message synchronously after API-key authentication; ordinary alert delivery is queued. No mailbox reading code is present.
- The service entry point uses Waitress on loopback port 5000 on Windows. No external network listener is enabled by default.
- Retention remains disabled at `RETENTION_DAYS_RECORDS=0`; the manual tool is dry-run unless `--delete-expired` is supplied.
- One earlier test attempt accidentally constructed the real Twilio client using test-only placeholder configuration; Twilio rejected the request with HTTP 401 and no SMS was sent. The test was changed to disable SMS entirely for that scenario; subsequent full suites use local SMTP/Twilio fakes and the safety gate in `backend/tests/conftest.py`. No further external request is permitted in automated tests.
- Added `waitress~=3.0.2` because Flask's development server is not appropriate for the Windows production entry point. It was installed only in the repository `.venv` for local validation.
- The existing listener on local port 5000 served an unrelated HTML page, so it was left running. Added a `PORT` override with 5000 as the default and started this demonstration on port 5001, forced to in-memory storage with email/SMS disabled. Manual check returned health `ok`, dashboard HTTP 200, and the visible demo-data notice.

## Public presentation deployment preparation (2026-11-21)

- Use Render as the default host for a public presentation demo because it supports a small Python web service and a client-owned `onrender.com` URL. Do not attach the client's Firebase database or notification credentials to this public demo.
- `render.yaml` pins Python 3.11.9, selects the Free plan, binds to `0.0.0.0` and uses memory storage. The app must honor `HOST` and platform `PORT` while keeping loopback as the local default.
- `backend/requirements-demo.txt` excludes TensorFlow, Firebase Admin, and Twilio because the published prototype has no model, external database, or messaging configured. OpenCV/NumPy remain because inference imports them for validation.
- Public deploy was not initiated: the repo has no Git remote and no deployment action is available in this session. The owner must publish this branch to a private client-owned GitHub repository and create the service through the client's Render account before a URL can be created.
- Render Free is for demos: it idles/sleeps, has temporary filesystem storage, and blocks outbound SMTP ports. The public app therefore remains synthetic, in-memory, and notification-disabled.

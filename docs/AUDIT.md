# Baseline audit

## Current architecture

The repository is a small draft consisting of a single Flask API (`backend/app.py`), one standalone HTML dashboard (`index.html`), a short unpinned backend dependency list, and a README. The backend initializes Firebase during import, optionally loads a Keras model, writes readings and classifications to Firebase, and sends SMTP/Twilio notifications. The dashboard currently operates entirely from local simulated data. There is no Streamlit application, firmware, test suite, configuration example, training pipeline, or operational documentation.

## Findings

| Severity | Location | Finding / consequence |
|---|---|---|
| High | `backend/app.py:64-68` | Import/startup exits without a Firebase URL and immediately requires a credential file. This prevents offline demo mode and makes importing the module for tests fail. |
| High | `backend/app.py:160-201` | Prediction accepts an unbounded upload, lacks file type/magic-byte/dimension checks, uses OpenCV BGR ordering, and returns raw exception text. |
| High | `backend/app.py:204-252` | Sensor/manual-alert routes do not authenticate or robustly validate types/ranges/strings; `force=True` suppresses JSON parsing errors into empty input. Bag IDs/messages can reach database paths and output without adequate validation. |
| High | `backend/app.py:90-126, 258-281` | Global cooldown state is not thread-safe or persistent. Requests spawn unbounded threads. Alerts created directly in routes can also be seen by the Firebase listener, creating duplicate notifications. Provider exception text and full recipient addresses/numbers can be logged. |
| High | `backend/app.py:146-156` | UTC timestamp is naive (`utcnow()`); health output exposes the full Firebase URL. |
| High | `index.html:219-234` | Demo sign-in uses a hard-coded email/password displayed in the page; it is not an access-control boundary and must not be used in live mode. |
| High | `index.html:329-368, 426-442` | Dynamic values are inserted with `innerHTML` without escaping. Demo predictions and readings are random, so they are not real farm observations or model results. |
| Medium | `index.html:10, 220-296` | Demo mode is hard-coded on; no backend API integration exists. Chart.js loads from a public CDN, so the page needs network access for charts. |
| Medium | `backend/app.py:137-144` | Image preprocessing does not explicitly convert BGR to RGB and normalization/model input contract is undocumented. |
| Medium | `backend/app.py:160-203` | Model output/class order and confidence values are not checked against metadata; bag state is overwritten without a history record. |
| Medium | `backend/app.py:204-240` | Only low humidity and high temperature are monitored; there is no hysteresis, recovery, stale-sensor alert, escalation, or multi-room/device support. |
| Medium | `backend/app.py:293` | Flask's development server binds to all interfaces. Production serving and deployment security are not provided. |
| Medium | `backend/requirements.txt:1-7` | Dependencies are unpinned and there are no separate development/test requirements. |
| Medium | `README.md:25-43` | README promises Streamlit, Plotly, and Pandas, but no Streamlit app exists. It also describes Firebase/cloud operation as available despite missing runnable offline configuration and credentials. |
| Medium | `README.md:45-55` | Setup instructions are incomplete: the repository URL is a placeholder and the steps do not match a tested setup flow. |

## Draft disagreements and constraints

- The existing API is not yet a validated “rewrite” with memory storage or API-key checks; it is a Firebase-only draft.
- The single-file backend is not sufficient for the specified API, testability, alert state, and offline demo. Phase 1 should replace it with the requested small package while preserving `python backend/app.py` as an entry point.
- The dashboard's hard-coded demo credentials and random result generator must be removed or kept strictly inside clearly labeled demo behavior; neither is suitable for live security or performance claims.
- TensorFlow installation must be measured on the supported Python/Windows environment before selecting compatible pinned versions. No package was intentionally removed or substituted in Phase 0.

## Verification limits

No Firebase project/key, Twilio or SMTP account, real image dataset, trained model, sensor, or camera was available. No cloud connectivity, notification delivery, model quality, or hardware behavior was verified.

The README includes shell snippets and a placeholder clone URL; the setup steps are not a validated Windows/PowerShell quickstart. Phase 5 should replace them with commands that match the Windows scripts and demo flow.

# Database layout

The backend uses `DB_BACKEND=memory` for local tests and offline demonstrations, or `DB_BACKEND=firebase` for Firebase Realtime Database. The Admin SDK runs only in the backend. Browser and device clients should call the Flask API and must not receive Firebase credentials.

| Path | Stored data |
|---|---|
| `sensors/latest` | Most recent temperature, humidity, room, device ID, and UTC timestamp. |
| `records/<pushId>` | Append-only sensor records (`temp`, `hum`, room, device ID, timestamp). |
| `bags/<bag_id>` | Current classification, confidence, probability vector, room, time, model version, and bag ID. |
| `bag_history/<bag_id>/<pushId>` | Classification history for a bag. |
| `alerts/<pushId>` | Alert type, message, location, level, status, timestamp, notification state, and optional resolution timestamp. |
| `meta/state/alert_state` | Active threshold state used to avoid duplicate alerts and preserve recovery behavior across restarts. |
| `demo` | Presentation-only data. Every generated value is marked synthetic and is separate from production API paths. |

`database.rules.json` denies direct client reads and writes. Apply the rules in the Firebase console after confirming that the Admin SDK service account belongs to the client's project. Do not put a service-account JSON file in Git or in a browser app.

## Data handling for client review

Sensor records include device and room labels. Bag history can contain farm photos only if a later implementation explicitly enables photo storage; the current photo route stores prediction results, not the uploaded image. Alert messages may include bag or room labels. Agree on retention and access rules with farm management before production. This is an engineering note, not legal advice.

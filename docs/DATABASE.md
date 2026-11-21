# Database layout

The monitoring API uses `DB_BACKEND=memory` for offline demonstrations/tests or `DB_BACKEND=firebase` for Firebase Realtime Database. The Admin SDK runs only in the backend. Browser and device clients call the Flask API and never receive Firebase credentials. Both adapters implement the same local path, push-key, multi-path update, delete, and newest-first query contract. Firebase writes that change multiple paths are sent as one root-level multi-location update.

| Path | Stored data |
|---|---|
| `sensors/latest` | Latest temperature, humidity, room, device ID, timestamp and optional synthetic marker. |
| `records/<pushId>` | Append-only sensor record (`temp`, `hum`, room, device ID, timestamp and optional synthetic marker). |
| `bags/<bag_id>` | Current classification, confidence, probability vector, room, timestamp, model version and bag ID. |
| `bag_history/<bag_id>/<pushId>` | Classification history for one bag. |
| `alerts/<pushId>` | Type, message, location, level, status, timestamp, notification status and optional resolution/escalation time. |
| `meta/state` | Persisted sensor time, environmental alert/hysteresis state, cooldown timestamps, per-bag contamination state and offline-sensor state. |
| `meta/email_daily_count/<local-date>` | Successful e-mail count for the configured farm time zone. |
| `meta/notification_queue` | Alerts held after the e-mail daily cap, for an idempotent daily digest. |
| `meta/notification_digests/<local-date>` | Digest claim/result used to avoid sending a duplicate digest. |
| `demo` | Separate presentation-only examples, visibly marked synthetic. Monitoring API routes do not read or write this node. |

`database.rules.json` denies direct client reads and writes. Apply the rules in the Firebase console after confirming the backend Admin SDK service account belongs to the client's project. Never put a service-account JSON file in Git or a browser app.

## Retention and data handling

Record cleanup is disabled when `RETENTION_DAYS_RECORDS=0`. `tools/run_retention.py` reports a dry run by default; deletion requires the explicit `--delete-expired` option. Confirm the retention period with farm management before enabling it. The current API and retention tool read the records collection to sort/filter or find expired records, so large installations should schedule and benchmark cleanup before collecting a high volume of data.

Sensor records include device and room labels. Bag history stores prediction results; the current photo route does not retain the uploaded image. Alert messages may include bag or room labels. Agree on retention and access rules with farm management before production. This is an engineering note, not legal advice.

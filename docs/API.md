# Monitoring API

The service exposes the sensor, bag, alert, history, and export routes below. It is intended to run on the farm computer and is served locally at `http://127.0.0.1:5000/`. All API routes except `/health` and `/` require `X-API-Key` when `API_KEY` is configured. All errors use `{"error":"plain-language explanation"}`. Timestamps are stored in UTC; the client time zone is Nairobi.

## Routes

| Method and path | Purpose |
|---|---|
| `GET /health` | Readiness, database/model state, notification status and safe operational counters. Does not return credentials or recipients. |
| `POST /sensor` | Validate and store a temperature/humidity reading, check thresholds and enqueue notifications in the background. Optional `synthetic: true` is retained as a visible marker. |
| `POST /predict` | Accept a JPEG, PNG, or WebP image up to 8 MB and save the model result and bag history. Returns 503 until a compatible trained model is installed. |
| `POST /alert` | Save a staff/system alert with type, message, level, location and cooldown deduplication. |
| `POST /admin/test-notification` | Send a fixed test notice over `email`, `sms`, or `both`. Requires a configured API key and is limited to two requests per minute. |
| `GET /sensors/latest` | Latest sensor reading, or `{}` when none exists. |
| `GET /records?limit=100&room=Room%201&since=2026-11-21T00:00:00Z` | Up to 500 newest sensor records, with optional room/time filters. |
| `GET /alerts?limit=100&status=open` | Up to 500 newest alerts, optionally filtered by `open`, `review`, or `resolved`. |
| `POST /alerts/<id>/resolve` | Resolve a known alert. Unknown IDs return 404. |
| `GET /bags` | Current bag classifications. |
| `GET /bags/<id>/history?limit=100` | One bag's newest prediction history. |
| `GET /stats/summary?hours=24` | Temperature/humidity min, average and max, alert counts by type, and bag counts by status. It summarizes at most the newest 500 stored records. |
| `GET /records/export.csv?since=2026-11-21T00:00:00Z` | Stream a CSV of at most 500 newest records. |

`/api/dashboard`, `/api/simulate`, and `/api/demo/reset` belong to the presentation demo. Their generated examples are labelled synthetic and stored by the separate demo store; they are not returned from the monitoring routes.

## Example: submit a reading

PowerShell:

```powershell
$headers = @{ "X-API-Key" = "<API_KEY>" }
$reading = @{
    temperature = 24.2
    humidity = 85
    room = "Room 1"
    device_id = "sensor-1"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/sensor" -Headers $headers -ContentType "application/json" -Body $reading
```

Command Prompt / curl:

```text
curl.exe -X POST http://127.0.0.1:5000/sensor -H "X-API-Key: <API_KEY>" -H "Content-Type: application/json" -d "{\"temperature\":24.2,\"humidity\":85,\"room\":\"Room 1\",\"device_id\":\"sensor-1\"}"
```

## Example: request recent records

PowerShell:

```powershell
$headers = @{ "X-API-Key" = "<API_KEY>" }
Invoke-RestMethod -Uri "http://127.0.0.1:5000/records?limit=10" -Headers $headers
```

## Errors and service status

Expected statuses include 400 for invalid input, 401 for a missing/incorrect key, 403 for a blocked browser origin, 404 for an unknown item, 413 for an oversized upload, 415 for unsupported or mismatched image content, 429 for rate limiting, and 503 when a required database/model is unavailable. Error messages give a next step and do not include provider exception details. Responses include an `X-Request-ID` for support; log records use the same request ID when a request context exists.

`DB_BACKEND=memory` is the offline demo/test mode. Firebase uses the Admin SDK from the backend only. The `/health` response says whether the database is connected and whether a model and notification channels are configured; configuration status does not mean hardware or real message delivery has been tested.

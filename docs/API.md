# Monitoring API (Phase 1)

The Flask service exposes JSON routes. When `API_KEY` is configured, send it in the `X-API-Key` header for every route except `/health` and the dashboard page. All timestamps are UTC ISO-8601. The dashboard should display them in Nairobi time.

## Sensor ingestion

`POST /sensor` accepts JSON with `temperature` (-40 to 85 °C), `humidity` (0 to 100 %), and optional `room` and `device_id` strings. A valid reading updates `sensors/latest`, appends a record, and runs the four threshold checks.

```powershell
$headers = @{ "X-API-Key" = "<API_KEY>" }
$reading = @{ temperature = 24.2; humidity = 85; room = "Room 1"; device_id = "sensor-1" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/sensor" -Headers $headers -ContentType "application/json" -Body $reading
```

```text
curl.exe -X POST http://127.0.0.1:5000/sensor -H "X-API-Key: <API_KEY>" -H "Content-Type: application/json" -d "{\"temperature\":24.2,\"humidity\":85,\"room\":\"Room 1\",\"device_id\":\"sensor-1\"}"
```

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Readiness, model, database, and notification configuration status. No secret values are returned. |
| POST | `/sensor` | Validate and store a sensor reading; evaluate thresholds. |
| POST | `/predict` | Accept a multipart `image` upload (JPEG, PNG, or WebP, at most 8 MB). Requires an installed compatible model. |
| POST | `/alert` | Add a validated manual alert; repeated active alerts are suppressed during the cooldown. |
| GET | `/sensors/latest` | Return the latest reading or `{}`. |
| GET | `/records?limit=100&room=Room%201&since=2026-11-21T00:00:00Z` | Return up to 500 newest records. |
| GET | `/alerts?limit=100&status=open` | Return up to 500 newest alerts, optionally filtered by `open`, `review`, or `resolved`. |
| POST | `/alerts/<id>/resolve` | Resolve one existing alert. Unknown IDs return 404. |
| GET | `/bags` | Return current bag classifications. |
| GET | `/bags/<id>/history?limit=100` | Return one bag's newest prediction history. |
| GET | `/stats/summary?hours=24` | Return temperature/humidity min/average/max and alert/bag counts. |
| GET | `/records/export.csv?since=2026-11-21T00:00:00Z` | Download a CSV of at most 500 records. |

## Error responses

Errors use `{"error":"plain-language explanation"}`. Expected statuses include 400 for invalid input, 401 for missing or incorrect API key, 404 for unknown records/routes, 413 for oversized uploads, 415 for unsupported image content, 429 for rate limiting, and 503 when the model or database is unavailable.

```powershell
$headers = @{ "X-API-Key" = "<API_KEY>" }
Invoke-RestMethod -Uri "http://127.0.0.1:5000/records?limit=10" -Headers $headers
```

`DB_BACKEND=memory` is for local demonstration and tests. Firebase uses the Admin SDK from the backend only. The older `/api/*` presentation routes continue to serve clearly labeled demo data.

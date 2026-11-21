# Continuation audit and phase report

Baseline: branch `feature/full-system`, commit `7b5aec6 feat: add secure monitoring API foundation`. The repository has no root `AGENTS.md` or `CODEX_TASK.md`; this review follows the user's supplied standing rules and the attached `CODEX_TASK.md` / `CODEX_CONTINUE.md`. User selected defaults; intake is recorded in `docs/INTAKE.md` and `docs/DECISIONS.md`.

## Contract conformance: before → after

Counts are for API handlers and alert rules in scope; `/predict` remains partial because there is no real trained model.

### Routes from `CODEX_TASK.md` §5.2

| Route | Before | After | Implementation and coverage |
|---|---|---|---|
| `GET /health` | Partial | Implemented | `backend/app.py` `health`; `test_health_and_api_key_authentication`, `test_database_outage_returns_generic_503_and_request_id`. Reports safe DB, model, notification, monitor, demo and uptime fields. |
| `POST /sensor` | Partial | Implemented | `backend/mushroom/routes.py` `sensor`; `test_sensor_validates_and_stores_then_raises_and_recovers`, `test_sensor_multi_path_failure_does_not_leave_partial_records`, `test_sensor_response_does_not_wait_for_failed_notification`. |
| `POST /predict` | Partial | Partial | `backend/mushroom/routes.py` `predict`; image validation and persistence are covered by prediction tests. A real trained, compatible model is not present, so farm classification remains unavailable. |
| `POST /alert` | Partial | Implemented | `backend/mushroom/routes.py` `manual_alert`; `test_manual_alert_deduplicates_and_resolves`, admin/notification tests. |
| `GET /sensors/latest` | Implemented | Implemented | `backend/mushroom/routes.py` `latest_sensor`; `test_sensor_latest_alert_filters_bag_routes_and_bad_inputs`. |
| `GET /records` | Implemented | Implemented | `backend/mushroom/routes.py` `records`; filtering, newest-first order, limits and errors covered by monitoring/API and adapter contract tests. |
| `GET /alerts` | Implemented | Implemented | `backend/mushroom/routes.py` `alerts`; filter and limit coverage in monitoring/API tests. |
| `POST /alerts/<id>/resolve` | Implemented | Implemented | `backend/mushroom/routes.py` `resolve_alert`; manual alert and resolve tests. |
| `GET /bags` | Implemented | Implemented | `backend/mushroom/routes.py` `bags`; bag route and prediction tests. |
| `GET /bags/<id>/history` | Implemented | Implemented | `backend/mushroom/routes.py` `bag_history`; prediction history tests. |
| `GET /stats/summary` | Implemented | Implemented | `backend/mushroom/routes.py` `summary`; summary/filter tests. Summary uses at most 500 newest records. |
| `GET /records/export.csv` | Implemented | Implemented | `backend/mushroom/routes.py` `export_records`; CSV route tests. |

**Route totals:** before 8 implemented / 4 partial / 0 missing; after 11 implemented / 1 partial / 0 missing.

### Alert rules from `CODEX_TASK.md` §5.4

| Rule | Before | After | Implementation and coverage |
|---|---|---|---|
| Temperature below minimum | Implemented | Implemented | Strict `<` comparison; exact 22 °C is in-range. `test_boundary_values_are_safe_and_four_directions_raise_once`. |
| Temperature above maximum | Implemented | Implemented | Strict `>` comparison; exact 26 °C is in-range. Same boundary test. |
| Humidity below minimum | Implemented | Implemented | Strict `<` comparison; exact 80% is in-range. Scenario covers 76% and recovery at 82%. |
| Humidity above maximum | Implemented | Implemented | Strict `>` comparison; exact 90% is in-range. Same boundary test. |
| Hysteresis and recovery margin | Partial | Implemented | Persistent per-room alert state; low alerts recover at threshold + margin and high alerts at threshold − margin. |
| Cooldown keyed by type + room + severity | Missing | Implemented | Persisted cooldown keys; restart, repeated reading, and expiry are clock-driven in `test_hysteresis_recovery_cooldown_and_restart_persistence`. |
| Restart-surviving state under `meta/state` | Partial | Implemented | State loads with missing/corrupt documents repaired; sensor latest/history and alert/state updates are atomic. Covered by restart, corrupt-state, adapter, and write-failure tests. |
| Escalate unresolved alert once after `ESCALATE_AFTER_MIN` | Missing | Implemented | Raises level to `high`, saves escalation marker/time and notifies once. `test_escalation_stale_alert_recovery_and_single_monitor`. |
| Stale sensor offline and back online | Missing | Implemented | Injectable-clock check and one monitor per DB instance; shutdown joins monitor. Same monitor test. |
| Contamination transitions, per-bag dedupe and recovery entry | Partial | Implemented | `suspect`/`contaminated` transition alerts and healthy recovery entry; repeated same status is deduplicated. `test_corrupt_state_is_repaired_and_contamination_transitions_dedupe`. |

**Alert-rule totals:** before 4 implemented / 3 partial / 3 missing; after 10 implemented / 0 partial / 0 missing.

## Defects found and disposition

- Sensor reading, latest value, threshold alerts, and alert state could previously be split across writes. They now use one database adapter multi-path update. A forced write failure returns a generic 503, logs only the error class, and leaves no partial sensor record.
- Firebase and memory query semantics lacked shared contract tests; Firebase keys did not reject ASCII control characters. Both adapters now use the same tests and invalid key checks.
- Alert state could fail on malformed saved values; cooldowns were not keyed by room/type/severity; escalation and stale-monitor logic were absent. State normalization and persisted clock-driven transitions are implemented and tested.
- SMTP failures used to consume the daily e-mail cap before delivery succeeded. The cap now counts successful sends and serializes the cap check/send; a low-cap retry test ensures failures do not queue false digests.
- The test suite once enabled a Twilio SDK call using test-only placeholder configuration; Twilio rejected it with HTTP 401 and no SMS was sent. That test now disables SMS and all later test runs use fake/local providers. No further external provider requests were made.
- Windows entry-point serving used Flask's development server. It now uses Waitress on loopback; `waitress~=3.0.2` is a direct dependency installed only into the repository `.venv` for validation.
- Record storage remains append-only unless the client enables retention. Retention is opt-in and dry-run by default. `GET /records` and summaries are bounded to the newest 500 records; retention scans the collection, so large-volume production should benchmark and agree on retention first.
- Firebase request latency under a slow live provider was not measured. Routes convert provider failures to safe 503 responses, but live latency/timeouts need a client-owned staging test.

## Files changed in this phase

See the repository working tree for the full list. Key changes include `backend/mushroom/alerts.py`, `notifier.py`, `db.py`, `config.py`, `routes.py`, `security.py`, `logging_setup.py`, `retention.py`, `backend/app.py`, test modules under `backend/tests/`, `tools/`, `backend/.env.example`, `backend/requirements.txt`, `docs/API.md`, `docs/DATABASE.md`, and `docs/DECISIONS.md`.

## Commands run and results

Final checks for this phase (rerun after the last implementation change):

```text
pytest -q --cov=backend.mushroom --cov-report=term-missing
58 passed in 2.17s; total package coverage 90%; alerts.py 94%; security.py 99%.

ruff check .
All checks passed!

ruff format --check .
34 files already formatted.

python -m py_compile (all 25 backend/tools Python files, excluding .venv and __pycache__)
py_compile passed for 25 Python files.

pip check
No broken requirements found.

node --check (inline index.html script extracted to a temporary .js file)
node --check passed for 1 inline script block(s).
```

Earlier exploratory checks: the security-only coverage invocation failed during collection with a NumPy/OpenCV duplicate-load import error; the same security tests passed without coverage, and the complete coverage suite passed. One full-suite run caught a test expectation mismatch for an absent counter (the correct representation is an empty path); the assertion was corrected and the next complete run passed. These failures were resolved, not hidden.

Repository/environment checks at review: working tree had the in-progress reliability changes; branch was `feature/full-system`; baseline commit was `7b5aec6`; Python is 3.11.9. `git ls-files` found no tracked `backend/.env` or service-account key. Secret file contents were not opened.

## Needs from user

- When ready to verify the client's sender setup, run `python tools/send_test_email.py` locally after configuring the values in `backend/.env`; tell me only the printed status line. Do not send any password or key in chat.
- Before production, supply client-reviewed farm images/classes, verify room thresholds with the agronomist, and test the sensor wiring and network on the farm. No real data, hardware, or model was available in this phase.

## Recommended next phase: Phase 2 — ML pipeline

1. Inventory existing image files without copying private data into Git; ask the client to label or confirm class criteria for `healthy`, `suspect`, and `contaminated`.
2. Add a dataset checker that validates image readability, minimum dimensions, class balance, and duplicate/leakage risks; report counts without exposing image contents.
3. Train only after client-provided data is available; split by source/bag before augmentation and evaluate only on held-out test data.
4. Generate model metadata with class order, input size, preprocessing, version, and an explicit synthetic/trained marker; reject incompatible models.
5. Test inference and bag-history/API behavior with a tiny test-only fixture, never present test/synthetic predictions as farm results.
6. Acceptance: no private dataset committed; deterministic split; loader rejects mismatched metadata; evaluation metrics are from held-out farm data and clearly reported; API only enables predictions with a reviewed real model.

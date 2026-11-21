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

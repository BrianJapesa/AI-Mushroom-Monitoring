# Publish the presentation demo

This guide prepares a **public, classroom demo**, not a live farm monitor. It contains only clearly labelled synthetic examples, uses temporary in-memory storage, and has no Firebase, email, SMS, or trained model configured. Never add `backend/.env`, `backend/secrets/serviceAccountKey.json`, farm readings, or private photos to the hosted demo.

The browser dashboard does not hold an API key, so public demo actions are not authenticated. Use only the included example buttons and synthetic information; never submit real sensor readings or private data to this public URL.

The repository includes `render.yaml` for Render and `backend/requirements-demo.txt` to avoid installing the unused TensorFlow, Firebase Admin, and Twilio packages for this demo. It binds to Render's public interface and platform port. The Blueprint does not auto-deploy future commits.

## Publish using your/client's accounts

1. Install/open GitHub Desktop and sign in to a GitHub account owned by you or the client.
2. Choose **File → Add Local Repository**, select this project folder, then choose **Publish repository**. Keep the repository **Private** and make sure the `feature/full-system` branch is included.
3. Sign in to Render using an account owned by you or the client. Connect that GitHub account and select **New → Blueprint**.
4. Choose the private repository and its `feature/full-system` branch. Render reads `render.yaml`; review that the service is named `mushroom-monitor-demo`, uses the Free plan, and has `DB_BACKEND=memory` before creating it.
5. Create the service and wait for the first deploy. Open the `onrender.com` URL Render shows. Check `/health` reports `status: ok`, `db_backend: memory`, and both notification channels disabled; then open the root dashboard.

No passwords, Firebase keys, e-mail addresses, or phone numbers are needed for this demo. If Render requests any such values, stop and check that the selected Blueprint is this repository's `render.yaml`.

## Limits of the free demo

Render's Free web services sleep after 15 minutes without traffic and can take about a minute to wake. Their filesystem is temporary, and this demo's readings are in memory, so examples reset after restarts or sleep. Free services also cannot send SMTP through ports 465/587. This setup is for a presentation and must not receive real farm readings or be used for production monitoring. See [Render's current free-service limits](https://render.com/docs/free).

Render requires a linked Git repository or a prebuilt image for a web service. This checkout currently has no Git remote, and no deployment action is available in this session, so the final hosted URL cannot be created from here yet. After step 2 and connecting the repository in the client's Render account, create the Blueprint from the Dashboard.

# Firebase-backed presentation demo setup

This guide connects the local dashboard to the Firebase Realtime Database URL supplied for the presentation. The app only reads and writes example content under the database's `/demo` node. It does not create farm sensor records in the production paths.

## Create a safe server key

1. Sign in to the client-owned Firebase project.
2. Open **Project settings** (gear icon) → **Service accounts**.
3. Generate a private key and download the JSON file.
4. Keep that file on the computer running the dashboard. It grants server access; never send it in chat or email.

The Admin SDK server uses its service-account credentials to access Realtime Database. The Firebase security rules can remain locked for ordinary client access.

## Connect the local demo

1. In File Explorer, open the repository folder.
2. Double-click `Connect-Firebase.bat`.
4. Select the downloaded service-account JSON file in the file window.
5. Paste the Realtime Database URL when the script asks.
5. Double-click `Start-Prototype.bat` to open the dashboard.

The connection script copies the key into ignored `backend\secrets\serviceAccountKey.json`, saves the URL and mode in ignored `backend\.env`, creates a backup of an existing `.env`, and restricts file access to the current Windows account. The key itself is never printed.

## Show the lecturer the interaction

1. Open the dashboard and confirm its connection card says **Firebase connected**.
2. Click **Try warm-room alert** or **Try low-humidity alert**.
3. The dashboard refreshes its view from Firebase. The new record and sample alert are written under `/demo`.
4. In Firebase Console → Realtime Database → Data, expand `/demo` to show the record and alert.
5. Click **Reset demo** to restore the synthetic example set.

All content in `/demo` is synthetic presentation data. It is not a real farm reading or model prediction. Do not put passwords, app passwords, or service-account files in Git or chat.

If no service-account key has been generated yet, the prototype still works in local memory mode. Its connection card will say **Local demo**, which is distinct from Firebase.

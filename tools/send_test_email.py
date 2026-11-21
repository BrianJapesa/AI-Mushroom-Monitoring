"""Send one fixed test email after verifying SMTP; the user runs this locally."""

from __future__ import annotations

from pathlib import Path

from backend.mushroom.config import Settings
from backend.mushroom.db import MemoryDB
from backend.mushroom.notifier import Notifier


def main() -> int:
    """Verify send-only SMTP configuration and send a labelled test message."""
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root / "backend" / ".env", root)
    notifier = Notifier(settings, MemoryDB(), start_workers=False)
    try:
        state = notifier.verify_smtp()
        print(state)
        if state != "email: ready":
            return 1
        result = notifier.send_test(("email",))["email"]
        print("Test email sent." if result["success"] else result["message"])
        return 0 if result["success"] else 1
    finally:
        notifier.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""Authorize MeetingNotesCoS to send Gmail and Calendar events."""

# Support both the documented module invocation (`python -m src.connect_google`)
# and launching this file directly from an IDE (`python src/connect_google.py`).
if __package__:
    from .google_services import connect_google_account
else:  # pragma: no cover - depends on how Python launches this file
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.google_services import connect_google_account


if __name__ == "__main__":
    print(f"Connected Google account: {connect_google_account()}")

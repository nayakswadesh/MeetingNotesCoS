# MeetingNotesCoS

MeetingNotesCoS is a Telegram-based meeting follow-through assistant. Send it a voice note (or an audio file), and it transcribes the recording, extracts action items, proposes a calendar event, and drafts a stakeholder summary email. The proposed actions are shown in Telegram for human review. Nothing is sent or created until the user presses **Approve & Send**.

## What it does

1. Receives Telegram voice and audio messages.
2. Transcribes audio locally with `faster-whisper` (the model defaults to `base`).
3. Runs a LangGraph workflow consisting of a supervisor, calendar, action-item, and communications specialists.
4. Uses OpenAI structured output when `OPENAI_API_KEY` is configured. Without a key, deterministic local fallbacks still produce a usable review draft and keep tests offline.
5. Pauses at a human-in-the-loop review gate. The user can approve, discard, or provide feedback to regenerate the drafts.
6. On approval, sends the email through Gmail and creates an event in the primary Google Calendar. Failures are reported in the Telegram execution log rather than silently ignored.

The configured sender is `nayakswadesh@gmail.com`, and Google OAuth is limited to Calendar events and Gmail send permissions. The bot rejects a connected Google account that does not match the configured sender.

## Requirements

- Windows, macOS, or Linux with Python 3.10+ (Python 3.11 is recommended).
- A Telegram bot and its bot token from [BotFather](https://core.telegram.org/bots#botfather).
- An OpenAI API key for model-assisted extraction (optional; local fallbacks work without it).
- A Google Cloud project with the Gmail API and Google Calendar API enabled.
- A Google OAuth client of type **Desktop app**, downloaded as `google-client-secret.json`.
- `ffmpeg` available on `PATH` if your local Whisper installation needs it to decode the incoming audio format.

## Installation

Clone the repository and create a virtual environment:

```powershell
git clone https://github.com/nayakswadesh/MeetingNotesCoS.git
cd MeetingNotesCoS
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate` and use `python3` where appropriate.

## Configuration

Set the Telegram token and, when desired, the OpenAI key as environment variables. Do not commit credentials or OAuth files; they are ignored by `.gitignore`.

```powershell
$env:TELEGRAM_BOT_TOKEN = "<token-from-botfather>"
$env:OPENAI_API_KEY = "<openai-api-key>"       # optional
$env:WHISPER_MODEL = "base"                    # optional: tiny, base, small, ...
```

The application currently instantiates `gpt-4o-mini` for OpenAI-backed planning and structured extraction. If no `OPENAI_API_KEY` is present, it uses the deterministic fallback implementations. The Whisper model is downloaded by `faster-whisper` on first use and can require several GB of disk space for larger model sizes.

## Connect Google

1. In Google Cloud, enable **Gmail API** and **Google Calendar API**, configure the OAuth consent screen, and add the intended Google account as a test user if the app is still in testing.
2. Save the downloaded Desktop OAuth client JSON in the project root as `google-client-secret.json`.
3. Run the OAuth flow from the project root:

   ```powershell
   .\.venv\Scripts\python.exe -m src.connect_google
   ```

   If your IDE launches the file directly, this also works:

   ```powershell
   .\.venv\Scripts\python.exe src\connect_google.py
   ```

4. Sign in as `nayakswadesh@gmail.com`, approve the requested scopes, and complete the browser flow. A refreshable `google-token.json` is written locally.

Alternative file locations can be supplied with `GOOGLE_CLIENT_SECRETS_FILE` and `GOOGLE_TOKEN_FILE`.

## Run the bot

From the repository root, with the virtual environment active and `TELEGRAM_BOT_TOKEN` set:

```powershell
python -m src.bot
```

In Telegram, send `/start` or `/help`, then send a voice note. Review the generated calendar and email proposals, choose **Approve & Send**, **Discard**, or **Edit with Feedback**, and inspect the execution log returned after approval.

## Test

```powershell
python -m pytest -q
```

The test suite exercises the graph and approval gate without contacting OpenAI or Google. It verifies that approval without a connected Google account produces clear, non-fatal execution messages.

## Project layout

```text
src/
  bot.py             Telegram handlers, transcription, preview, and approval buttons
  graph.py           LangGraph workflow and human-review gate
  google_services.py Gmail/Calendar OAuth and side effects
  schemas.py         Pydantic proposals and shared graph state
  connect_google.py  One-time Google OAuth entry point
tests/               Offline workflow tests
CONNECT_GOOGLE.md    Short Google setup guide
requirements.txt     Python dependencies
```

## Troubleshooting

- **Relative-import error:** run `python -m src.bot` or `python -m src.connect_google` from the repository root. The Google entry point also supports direct file launching.
- **Missing Telegram token:** set `TELEGRAM_BOT_TOKEN` in the same shell that starts the bot.
- **OpenAI errors or quota limits:** check `OPENAI_API_KEY`; removing it enables local deterministic fallbacks.
- **Google authorization errors:** rerun the Google connection command, confirm the OAuth test user and enabled APIs, and ensure the signed-in account is `nayakswadesh@gmail.com`.
- **Audio processing errors:** install `ffmpeg`, ensure it is on `PATH`, and try a smaller Whisper model via `WHISPER_MODEL`.

## Security

OAuth client secrets, refresh tokens, API keys, Telegram tokens, and downloaded model data are local credentials or private data. Keep them out of source control, rotate any credential that has been exposed, and use a restricted Google Cloud project for this bot.

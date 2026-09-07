"""Telegram interface for MeetingNotesCoS."""
from __future__ import annotations
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from faster_whisper import WhisperModel
from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from .graph import get_meeting_notes_cos_graph

GRAPH = get_meeting_notes_cos_graph()
IST = timezone(timedelta(hours=5, minutes=30))
INTRODUCTION = "Hello! I'm *MeetingNotesCoS*, your meeting follow-through assistant.\n\nI turn voice notes into a reviewable calendar invite and stakeholder email. Nothing is sent until you explicitly approve it.\n\nSend or record a voice note here to get started!"

def _config(chat_id: int) -> dict[str, Any]: return {"configurable": {"thread_id": str(chat_id)}}
def _value(item: Any, field: str, default: Any = "") -> Any: return getattr(item, field, item.get(field, default) if isinstance(item, dict) else default)
def _markdown(value: Any) -> str: return str(value).replace("\\", "\\\\").replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

def _human_datetime(value: Any) -> str:
    text = str(value)
    if text == "TBD": return text
    try:
        parsed = datetime.fromisoformat(text).astimezone(IST)
        hour, minute = parsed.strftime("%I").lstrip("0"), parsed.strftime("%M")
        clock = f"{hour}{'' if minute == '00' else ':' + minute}{parsed.strftime('%p').lower()}"
        suffix = "th" if 10 <= parsed.day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(parsed.day % 10, "th")
        return f"{clock}, {parsed.day}{suffix} {parsed.strftime('%b')}"
    except ValueError: return text

def _preview(state: dict[str, Any]) -> str:
    calendar, email = state.get("calendar_event"), state.get("email_draft")
    calendar_text = "No calendar invite proposed" if not calendar else (f"*{_markdown(_value(calendar, 'title'))}*\nWhen: {_markdown(_human_datetime(_value(calendar, 'start_time')))} to {_markdown(_human_datetime(_value(calendar, 'end_time')))}\nAttendees: {_markdown(', '.join(_value(calendar, 'attendees', [])) or 'TBD')}\n{_markdown(_value(calendar, 'description'))}")
    email_text = "No email draft proposed" if not email else (f"To: {_markdown(', '.join(_value(email, 'to', [])) or 'TBD')}\nSubject: {_markdown(_value(email, 'subject'))}\n\n{_markdown(_value(email, 'body'))}")
    return f"*Proposed Calendar Invite*\n{calendar_text}\n\n*Proposed Email Draft*\n{email_text}"

def _buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Approve & Send", callback_data="approve"), InlineKeyboardButton("Discard", callback_data="reject"), InlineKeyboardButton("Edit with Feedback", callback_data="edit")]])
def _current_state(chat_id: int) -> dict[str, Any]: return dict(GRAPH.get_state(_config(chat_id)).values)

async def introduce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("waiting_for_edit") and update.effective_message: await update.effective_message.reply_text(INTRODUCTION, parse_mode=ParseMode.MARKDOWN)
def _transcribe(path: Path) -> str:
    segments, _ = WhisperModel(os.getenv("WHISPER_MODEL", "base"), device="auto", compute_type="int8").transcribe(str(path))
    return " ".join(segment.text.strip() for segment in segments).strip()

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message, chat = update.effective_message, update.effective_chat
    if not message or not chat: return
    await message.reply_text("MeetingNotesCoS is transcribing your audio and preparing drafts...")
    media = message.voice or message.audio
    if not media: return
    suffix = ".ogg" if message.voice else Path(media.file_name or "audio.mp3").suffix or ".mp3"
    audio_path = Path(gettempdir()) / f"temp_{chat.id}{suffix}"
    try:
        await (await context.bot.get_file(media.file_id)).download_to_drive(custom_path=audio_path)
        transcript = await asyncio.to_thread(_transcribe, audio_path)
        await asyncio.to_thread(GRAPH.invoke, {"transcript": transcript, "calendar_event": None, "email_draft": None, "action_items": [], "human_feedback": None, "approval_status": "PENDING", "execution_logs": []}, _config(chat.id))
        await message.reply_text(_preview(_current_state(chat.id)), parse_mode=ParseMode.MARKDOWN, reply_markup=_buttons())
    except Exception as exc: await message.reply_text(f"I couldn't process that audio: {exc}")
    finally: audio_path.unlink(missing_ok=True)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat: return
    await query.answer()
    if query.data == "edit":
        context.user_data["waiting_for_edit"] = True
        await query.message.reply_text("What changes or feedback do you have? Send text and I'll regenerate the drafts.")
        return
    decision = "APPROVED" if query.data == "approve" else "REJECTED"
    await asyncio.to_thread(GRAPH.invoke, Command(resume={"decision": decision}), _config(update.effective_chat.id))
    if decision == "REJECTED": await query.edit_message_text("Calendar invite and email draft discarded.")
    else: await query.edit_message_text("Approved and executed.\n\n" + "\n".join(f"- {entry}" for entry in _current_state(update.effective_chat.id).get("execution_logs", [])))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message, chat = update.effective_message, update.effective_chat
    if not message or not chat: return
    if not context.user_data.get("waiting_for_edit"):
        await introduce(update, context); return
    context.user_data["waiting_for_edit"] = False
    await asyncio.to_thread(GRAPH.invoke, Command(resume={"decision": "EDIT", "feedback": message.text}), _config(chat.id))
    await message.reply_text(_preview(_current_state(chat.id)), parse_mode=ParseMode.MARKDOWN, reply_markup=_buttons())

def build_application(token: str | None = None) -> Application:
    app = Application.builder().token(token or os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler(["start", "help"], introduce)); app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio)); app.add_handler(CallbackQueryHandler(handle_callback)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)); return app
def main() -> None: build_application().run_polling()
if __name__ == "__main__": main()

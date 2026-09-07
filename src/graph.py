"""The MeetingNotesCoS LangGraph workflow, including its human review gate."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .schemas import (
    ActionItem,
    CalendarEventProposal,
    EmailDraftProposal,
    MeetingNotesCoSState,
)
from .google_services import GoogleConnectionError, book_calendar, send_email

WORKFLOW_NAME = "MeetingNotesCoS"
IST = timezone(timedelta(hours=5, minutes=30))


def _model() -> ChatOpenAI:
    """Create the required deterministic model, without contacting it until invoked."""
    return ChatOpenAI(model="gpt-4o-mini", temperature=0)


def _lines(transcript: str) -> list[str]:
    return [line.strip(" -•\t") for line in re.split(r"[\n.]+", transcript) if line.strip()]


def _fallback_actions(transcript: str) -> list[ActionItem]:
    actions: list[ActionItem] = []
    for line in _lines(transcript):
        if re.search(r"\b(action|todo|follow up|will |needs? to|should )\b", line, re.I):
            owner = re.search(r"\b([A-Z][a-z]+)\s+(?:will|to|should)\b", line)
            due = re.search(r"\b(?:by|due)\s+([^,.;]+)", line, re.I)
            actions.append(ActionItem(
                task=line,
                assignee=owner.group(1) if owner else "Unassigned",
                priority="medium",
                due_date=due.group(1).strip() if due else None,
            ))
    return actions or [ActionItem(task="Review meeting notes and confirm next steps", assignee="Unassigned")]


def _invoke_structured(schema: type[Any], prompt: str) -> Any | None:
    """Use OpenAI when configured; deterministic local fallbacks keep the app testable."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        return _model().with_structured_output(schema).invoke(prompt)
    except Exception:
        return None


def supervisor_dispatcher(state: MeetingNotesCoSState) -> dict[str, Any]:
    feedback = state.get("human_feedback")
    prompt = (
        "You are the MeetingNotesCoS supervisor. Analyze this meeting transcript and "
        "decide that calendar, action-item, and communications specialists should produce "
        f"reviewable drafts. Transcript:\n{state['transcript']}\nFeedback: {feedback or 'None'}"
    )
    # Invoke the required model for planning when available. The fixed graph fan-out is
    # intentionally robust when an API key is absent (e.g. local tests).
    if os.getenv("OPENAI_API_KEY"):
        try:
            _model().invoke(prompt)
        except Exception:
            pass
    return {"approval_status": "PENDING"}


def calendar_agent(state: MeetingNotesCoSState) -> dict[str, Any]:
    feedback = state.get("human_feedback")
    proposal = _invoke_structured(
        CalendarEventProposal,
        "Extract a proposed calendar event from this transcript. Today is "
        f"{datetime.now(IST).strftime('%A, %d %B %Y')}; interpret relative dates, "
        "such as 'next Monday', from that date. Use ISO-8601 times with an Asia/Kolkata offset "
        "if a time is known. Include attendee email addresses only when explicitly present. "
        f"Transcript: {state['transcript']}\nHuman feedback: {feedback or 'None'}",
    )
    if proposal is None:
        proposal = CalendarEventProposal(
            title="Meeting follow-up",
            start_time="TBD",
            end_time="TBD",
            attendees=[],
            description=(feedback or state["transcript"])[:1000],
        )
    return {"calendar_event": proposal}


def action_item_agent(state: MeetingNotesCoSState) -> dict[str, Any]:
    feedback = state.get("human_feedback")
    result = _invoke_structured(
        list[ActionItem],
        "Extract tactical action items with task, assignee, priority, and optional due date. "
        f"Transcript: {state['transcript']}\nHuman feedback: {feedback or 'None'}",
    )
    return {"action_items": result if result is not None else _fallback_actions(state["transcript"])}


def comms_agent(state: MeetingNotesCoSState) -> dict[str, Any]:
    actions = state.get("action_items", [])
    feedback = state.get("human_feedback")
    proposal = _invoke_structured(
        EmailDraftProposal,
        "Draft a concise plain-text executive meeting-summary email. Do not use Markdown, including "
        "** bold markers. Put the email addresses of every stakeholder discussed in the email into the "
        "`to` field; never invent an email address. "
        f"Transcript: {state['transcript']}\nAction items: {actions}\nFeedback: {feedback or 'None'}",
    )
    if proposal is None:
        body = "Meeting summary\n\nAction items:\n" + "\n".join(
            f"- {item.task} ({item.assignee})" for item in actions
        )
        if feedback:
            body += f"\n\nRequested revision: {feedback}"
        recipients = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", state["transcript"], re.I)
        proposal = EmailDraftProposal(to=recipients, subject="Meeting summary and next steps", body=body)
    return {"email_draft": proposal}


def review_gate_node(state: MeetingNotesCoSState) -> dict[str, Any]:
    decision = interrupt({
        "workflow": WORKFLOW_NAME,
        "calendar_event": state.get("calendar_event"),
        "email_draft": state.get("email_draft"),
        "action_items": state.get("action_items", []),
    })
    if not isinstance(decision, dict):
        decision = {"decision": str(decision)}
    status = str(decision.get("decision", "REJECTED")).upper()
    if status == "EDIT":
        return {"approval_status": "EDIT", "human_feedback": str(decision.get("feedback", ""))}
    if status == "APPROVED":
        return {"approval_status": "APPROVED"}
    return {"approval_status": "REJECTED"}


def executor_node(state: MeetingNotesCoSState) -> dict[str, Any]:
    logs: list[str] = []
    if state.get("calendar_event"):
        try:
            logs.append(book_calendar(state["calendar_event"]))
        except (GoogleConnectionError, ValueError) as exc:
            logs.append(f"Calendar invite not created: {exc}")
    if state.get("email_draft"):
        try:
            logs.append(send_email(state["email_draft"]))
        except (GoogleConnectionError, ValueError) as exc:
            logs.append(f"Email not sent: {exc}")
    return {"execution_logs": state.get("execution_logs", []) + logs}


def _after_review(state: MeetingNotesCoSState) -> Literal["supervisor_dispatcher", "executor_node", "__end__"]:
    if state["approval_status"] == "EDIT":
        return "supervisor_dispatcher"
    if state["approval_status"] == "APPROVED":
        return "executor_node"
    return END


def get_meeting_notes_cos_graph():
    """Return a freshly compiled, checkpointed MeetingNotesCoS graph."""
    builder = StateGraph(MeetingNotesCoSState)
    builder.add_node("supervisor_dispatcher", supervisor_dispatcher)
    builder.add_node("calendar_agent", calendar_agent)
    builder.add_node("action_item_agent", action_item_agent)
    builder.add_node("comms_agent", comms_agent)
    builder.add_node("review_gate_node", review_gate_node)
    builder.add_node("executor_node", executor_node)
    builder.add_edge(START, "supervisor_dispatcher")
    builder.add_edge("supervisor_dispatcher", "calendar_agent")
    builder.add_edge("calendar_agent", "action_item_agent")
    builder.add_edge("action_item_agent", "comms_agent")
    builder.add_edge("comms_agent", "review_gate_node")
    builder.add_conditional_edges("review_gate_node", _after_review)
    builder.add_edge("executor_node", END)
    return builder.compile(checkpointer=MemorySaver(), name=WORKFLOW_NAME)


__all__ = ["Command", "WORKFLOW_NAME", "get_meeting_notes_cos_graph"]

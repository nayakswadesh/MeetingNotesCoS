"""Data contracts shared by the MeetingNotesCoS agents."""

from __future__ import annotations

from typing import Optional, TypedDict

from pydantic import BaseModel, Field


class CalendarEventProposal(BaseModel):
    title: str
    start_time: str
    end_time: str
    attendees: list[str] = Field(default_factory=list)
    description: str = ""


class EmailDraftProposal(BaseModel):
    to: list[str] = Field(default_factory=list)
    subject: str
    body: str
    priority: str = "normal"


class ActionItem(BaseModel):
    task: str
    assignee: str
    priority: str = "medium"
    due_date: Optional[str] = None


class MeetingNotesCoSState(TypedDict):
    transcript: str
    calendar_event: Optional[CalendarEventProposal]
    email_draft: Optional[EmailDraftProposal]
    action_items: list[ActionItem]
    human_feedback: Optional[str]
    approval_status: str
    execution_logs: list[str]

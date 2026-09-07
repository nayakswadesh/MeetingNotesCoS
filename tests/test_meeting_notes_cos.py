from langgraph.types import Command

from src.graph import WORKFLOW_NAME, get_meeting_notes_cos_graph


def test_workflow_interrupts_then_reports_unconnected_google_account(monkeypatch):
    """A mock voice transcript reaches HITL and can be approved without an API key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    graph = get_meeting_notes_cos_graph()
    config = {"configurable": {"thread_id": "test-meeting"}}
    graph.invoke({
        "transcript": "Alice will send the budget by Friday. Schedule a follow-up.",
        "calendar_event": None,
        "email_draft": None,
        "action_items": [],
        "human_feedback": None,
        "approval_status": "PENDING",
        "execution_logs": [],
    }, config=config)
    paused = graph.get_state(config)
    assert WORKFLOW_NAME == "MeetingNotesCoS"
    assert paused.next == ("review_gate_node",)

    result = graph.invoke(Command(resume={"decision": "APPROVED"}), config=config)
    assert result["approval_status"] == "APPROVED"
    assert any("Calendar invite not created" in entry for entry in result["execution_logs"])
    assert any("Email not sent" in entry for entry in result["execution_logs"])

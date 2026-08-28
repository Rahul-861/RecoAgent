import pytest

from app.pipeline.state_machine import transition, final_state_for_decision, InvalidStateTransition, decision_from_match


def test_happy_path_transitions():
    s = transition("UNPROCESSED", "VALIDATED")
    s = transition(s, "NORMALIZED")
    s = transition(s, "CANDIDATES_FOUND")
    s = transition(s, "EVALUATED")
    s = transition(s, "MATCH")
    s = transition(s, "RECONCILED")
    assert s == "RECONCILED"


def test_invalid_transition_rejected():
    with pytest.raises(InvalidStateTransition):
        transition("MATCH", "INVALID")


def test_decision_to_final_state():
    assert final_state_for_decision("MATCH") == "RECONCILED"
    assert final_state_for_decision("AMBIGUOUS") == "REVIEW"
    assert final_state_for_decision("UNMATCHED") == "EXCEPTION"
    assert final_state_for_decision("INVALID") == "EXCEPTION"


def test_decision_from_legacy_status():
    assert decision_from_match("matched", "exact", None) == "MATCH"
    assert decision_from_match("exception", "unresolved", "duplicate") == "DUPLICATE"
    assert decision_from_match("exception", "unresolved", "ambiguous") == "AMBIGUOUS"
    assert decision_from_match("exception", "one_to_many", "partially_paid") == "PARTIAL_MATCH"

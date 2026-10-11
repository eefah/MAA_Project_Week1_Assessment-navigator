"""End-to-end checks of the Streamlit app using Streamlit's test runner.

Groq is replaced by a fake client, so no credentials or paid calls are needed.
"""

import json
from datetime import date
from pathlib import Path

import groq
import pytest
from streamlit.testing.v1 import AppTest

from fakes import FAKE_KEY, FakeClient, status_error
from navigator import ai

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TABS = ["My child's next steps", "Assessment pathway", "Waiting-list picture", "AI assistant"]


def make_app(password="test-pass", hosted=True, groq_key=FAKE_KEY):
    at = AppTest.from_file(APP, default_timeout=60)
    if password is not None:
        at.secrets["APP_PASSWORD"] = password
    at.secrets["HOSTED"] = hosted  # hosted mode never touches local_data/
    if groq_key is not None:
        at.secrets["GROQ_API_KEY"] = groq_key
    return at


def logged_in(**kwargs):
    at = make_app(**kwargs)
    at.run()
    at.text_input[0].input("test-pass")
    at.button[0].click()
    at.run()
    assert not at.exception
    return at


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ai, "make_client", lambda api_key: client)
    return client


STAGE_TABS = [
    "1. Concerns and referral",
    "2. Referral review",
    "3. Initial paediatric appointment",
    "4. Specialist assessment, if referred",
    "5. Feedback and next steps",
]


def main_tabs(at):
    return [t.label for t in at.tabs if t.label in TABS]


def button(at, label):
    return next(b for b in at.button if b.label == label)


def page_text(at):
    parts = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "text", "json"):
        for element in getattr(at, kind):
            parts.append(str(getattr(element, "value", "")))
    return "\n".join(parts)


# ------------------------------------------------------------- password and tabs

def test_locked_without_password_configured():
    at = make_app(password="")
    at.run()
    assert not at.tabs
    assert "No password has been set" in at.warning[0].value


def test_wrong_password_rejected():
    at = make_app()
    at.run()
    assert not at.tabs
    at.text_input[0].input("nope")
    at.button[0].click()
    at.run()
    assert not at.tabs
    assert "not right" in at.error[0].value


def test_correct_password_shows_four_tabs_in_order(fake):
    at = logged_in()
    assert main_tabs(at) == TABS
    text = " ".join(i.value for i in at.info)
    assert "processed on the hosting server for this session" in text
    assert not [b for b in at.button if b.label in ("Save", "Delete saved information")]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Total waiting"] == "909"
    assert metrics["Waiting over 52 weeks"] == "1"
    assert metrics["Waiting over 104 weeks"] == "0"
    assert fake.calls == []  # nothing is sent to Groq just by opening the app


def test_pathway_stages_are_one_row_of_tabs(fake):
    at = logged_in()
    labels = [t.label for t in at.tabs]
    assert [l for l in labels if l not in TABS] == STAGE_TABS
    headings = [h.value for h in at.subheader]
    for n, title in enumerate(STAGE_TABS, start=1):
        assert f"Stage {n} of 5: {title.split('. ', 1)[1]}" in headings


def test_local_mode_shows_save_and_delete():
    at = logged_in(hosted=False)
    labels = [b.label for b in at.button]
    assert "Save" in labels and "Delete saved information" in labels
    assert any("local_data/" in i.value for i in at.info)


# ------------------------------------------------------------- AI assistant

def test_missing_groq_key_keeps_other_tabs_working(fake):
    at = logged_in(groq_key=None)
    assert main_tabs(at) == TABS
    assert any("isn't set up yet" in w.value for w in at.warning)
    assert {m.label: m.value for m in at.metric}["Total waiting"] == "909"
    assert not [b for b in at.button if b.label == "Generate explanation"]
    assert fake.calls == []


def test_blank_groq_key_counts_as_missing(fake):
    at = logged_in(groq_key="   ")
    assert any("isn't set up yet" in w.value for w in at.warning)


def test_context_labels_shown(fake):
    at = logged_in()
    text = page_text(at)
    assert "GUY'S AND ST THOMAS' NHS FOUNDATION TRUST" in text.replace("\\", "")
    assert "Community paediatric service" in text.replace("\\", "")
    assert "August 2026" in text


def test_generate_explanation_calls_once_and_not_on_rerun(fake):
    at = logged_in()
    button(at, "Generate explanation").click()
    at.run()
    assert len(fake.calls) == 1
    assert "This is a test explanation." in page_text(at)
    at.run()  # an ordinary rerun must not call Groq again
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == ai.DEFAULT_MODEL


def test_model_is_configurable(fake):
    at = make_app()
    at.secrets["GROQ_MODEL"] = "openai/gpt-oss-20b"
    at.run()
    at.text_input[0].input("test-pass")
    at.button[0].click()
    at.run()
    button(at, "Generate explanation").click()
    at.run()
    assert fake.calls[0]["model"] == "openai/gpt-oss-20b"


def test_personal_information_never_sent(fake):
    at = logged_in()
    dates = at.date_input
    dates[0].set_value(date(2026, 3, 2))
    dates[1].set_value(date(2026, 3, 16))
    dates[2].set_value(date(2026, 6, 1))
    dates[3].set_value(date(2026, 6, 9))
    at.text_area[0].input("SECRET-NOTE spoke to Dr Example about Sam")
    at.selectbox(key="p_current_stage").set_value("specialist_assessment")
    at.run()
    button(at, "Generate explanation").click()
    at.run()
    at.chat_input[0].set_value("What does the 52-week figure mean?")
    at.run()
    assert len(fake.calls) == 2
    payload = json.dumps(fake.calls)
    for forbidden in [
        "SECRET-NOTE", "Dr Example", "Sam",
        "2026-03-02", "2026-03-16", "2026-06-01", "2026-06-09",
        "2 March 2026", "16 March 2026", "1 June 2026", "9 June 2026",
        "02/03/2026", "specialist_assessment",
    ]:
        assert forbidden not in payload, forbidden
    assert FAKE_KEY not in payload


def test_follow_up_chat_records_history(fake):
    at = logged_in()
    at.chat_input[0].set_value("Does this include autism assessments?")
    at.run()
    assert len(fake.calls) == 1
    sent = fake.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "<context>" in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "Does this include autism assessments?"}
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    at.run()
    assert len(fake.calls) == 1


def test_api_failure_shows_safe_message(monkeypatch):
    client = FakeClient(error=status_error(groq.AuthenticationError, 401))
    monkeypatch.setattr(ai, "make_client", lambda api_key: client)
    at = logged_in()
    button(at, "Generate explanation").click()
    at.run()
    assert not at.exception
    assert any("did not accept the API key" in e.value for e in at.error)
    text = page_text(at)
    assert FAKE_KEY not in text and "secret request detail" not in text
    assert main_tabs(at) == TABS


def test_failed_question_is_not_kept(monkeypatch):
    client = FakeClient(error=status_error(groq.RateLimitError, 429))
    monkeypatch.setattr(ai, "make_client", lambda api_key: client)
    at = logged_in()
    at.chat_input[0].set_value("A question")
    at.run()
    assert any("usage limit" in e.value for e in at.error)
    assert at.session_state["ai_history"] == []


def test_changing_provider_restarts_chat(fake):
    at = logged_in()
    button(at, "Generate explanation").click()
    at.run()
    assert at.session_state["ai_explanation"]
    at.selectbox(key="provider_key").set_value("National||England")
    at.run()
    assert at.session_state["ai_explanation"] is None
    assert at.session_state["ai_history"] == []
    assert any("chat has restarted" in i.value for i in at.info)
    assert "England" in page_text(at)


def test_follow_up_limit(fake):
    at = logged_in()
    history = []
    for n in range(ai.MAX_FOLLOW_UPS):
        history += [{"role": "user", "content": f"q{n}"}, {"role": "assistant", "content": f"a{n}"}]
    at.session_state["ai_history"] = history
    at.run()
    assert not at.chat_input
    assert any("Start a new chat to ask more" in i.value for i in at.info)
    button(at, "Start a new chat").click()
    at.run()
    assert len(at.chat_input) == 1


def test_api_key_never_displayed(fake):
    at = logged_in()
    button(at, "Generate explanation").click()
    at.run()
    assert FAKE_KEY not in page_text(at)

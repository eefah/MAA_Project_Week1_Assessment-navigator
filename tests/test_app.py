"""End-to-end checks of the Streamlit app using Streamlit's test runner."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def make_app(password="test-pass", hosted=True):
    at = AppTest.from_file(APP, default_timeout=60)
    if password is not None:
        at.secrets["APP_PASSWORD"] = password
    at.secrets["HOSTED"] = hosted  # hosted mode never touches local_data/
    return at


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


def test_correct_password_shows_three_tabs_in_order():
    at = make_app()
    at.run()
    at.text_input[0].input("test-pass")
    at.button[0].click()
    at.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == [
        "My child's next steps",
        "Assessment pathway",
        "Waiting-list picture",
    ]
    text = " ".join(i.value for i in at.info)
    assert "processed on the hosting server for this session" in text
    assert not [b for b in at.button if b.label in ("Save", "Delete saved information")]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Total waiting"] == "909"
    assert metrics["Waiting over 52 weeks"] == "1"
    assert metrics["Waiting over 104 weeks"] == "0"


def test_local_mode_shows_save_and_delete():
    at = make_app(hosted=False)
    at.run()
    at.text_input[0].input("test-pass")
    at.button[0].click()
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Save" in labels and "Delete saved information" in labels
    assert any("local_data/" in i.value for i in at.info)

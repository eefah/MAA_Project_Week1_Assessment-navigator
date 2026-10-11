"""A simple shared-password gate.

This is a prototype access gate, not a complete security solution for
hosting sensitive information.
"""

from __future__ import annotations

import hmac
from typing import Any

import streamlit as st


def secret(name: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(name, default)
    except Exception:  # no secrets file at all
        return default


def is_hosted() -> bool:
    return str(secret("HOSTED", False)).strip().lower() in {"true", "1", "yes"}


def require_password() -> None:
    """Stop the script until the correct password has been entered."""
    if st.session_state.get("authenticated"):
        return

    expected = str(secret("APP_PASSWORD", "") or "")
    st.title("Assessment Navigator")
    if not expected:
        st.warning(
            "No password has been set, so the app is locked.\n\n"
            "Open `.streamlit/secrets.toml`, put a password between the quotes "
            "after `APP_PASSWORD =`, save the file and restart the app."
        )
        st.stop()

    with st.form("password_form"):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Open the app")
    if submitted:
        if hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8")):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("That password is not right. Please try again.")
    st.caption(
        "This is a simple access gate for a prototype. "
        "It is not designed to protect sensitive information."
    )
    st.stop()

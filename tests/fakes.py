"""A stand-in for the Groq client, so tests need no credentials or paid calls.

These fakes check our own code paths. They say nothing about whether a real
model's answers are accurate.
"""

from types import SimpleNamespace

import groq
import httpx

FAKE_KEY = "gsk_test_FAKE_KEY_should_never_appear"
REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def status_error(cls, code):
    return cls(
        f"secret request detail {FAKE_KEY}",
        response=httpx.Response(code, request=REQUEST),
        body={"error": {"message": f"detail with {FAKE_KEY}"}},
    )


class FakeClient:
    def __init__(self, reply="This is a test explanation.", error=None):
        self.reply = reply
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.calls.append(params)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

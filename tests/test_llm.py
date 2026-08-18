"""Model seam tests.

The Ollama tests stub the transport so they run without a server. There is a
separate integration check further down that skips when nothing is listening —
a test suite that silently needs a 5 GB download is a test suite nobody runs.
"""

import json

import httpx
import pytest

from latch.llm import AnthropicModel, FakeModel, OllamaModel

SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "boolean"}},
    "required": ["keep"],
    "additionalProperties": False,
}


class StubResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self) -> dict:
        return self._payload


def stub_post(monkeypatch, payload: dict, capture: dict | None = None):
    def _post(url, json=None, timeout=None):
        if capture is not None:
            capture["url"] = url
            capture["body"] = json
        return StubResponse(payload)

    monkeypatch.setattr(httpx, "post", _post)


def ollama_reply(content: dict, prompt_tokens: int = 120, eval_tokens: int = 40):
    return {
        "message": {"content": json.dumps(content)},
        "prompt_eval_count": prompt_tokens,
        "eval_count": eval_tokens,
    }


def call(client, **overrides):
    kwargs = {
        "model": "claude-haiku-4-5",
        "system": "sys",
        "prompt": "prompt",
        "schema": SCHEMA,
        "max_tokens": 512,
        "purpose": "triage",
    }
    return client.complete_json(**(kwargs | overrides))


# --- FakeModel ---------------------------------------------------------------


def test_fake_model_refuses_to_improvise():
    with pytest.raises(KeyError, match="no scripted response"):
        call(FakeModel({}))


def test_fake_model_walks_a_scripted_sequence():
    client = FakeModel({"triage": [{"keep": True}, {"keep": False}]})
    assert call(client).data == {"keep": True}
    assert call(client).data == {"keep": False}
    # the last entry repeats rather than running out mid-run
    assert call(client).data == {"keep": False}


# --- OllamaModel -------------------------------------------------------------


def test_schema_is_sent_as_a_grammar_constraint_not_prose(monkeypatch):
    """Local models are far weaker at holding a schema by instruction. Passing
    it to the server makes structural validity enforced rather than hoped for."""
    capture: dict = {}
    stub_post(monkeypatch, ollama_reply({"keep": True}), capture)

    call(OllamaModel(model="qwen3:8b"))

    assert capture["body"]["format"] == SCHEMA
    assert capture["url"].endswith("/api/chat")


def test_sampling_is_pinned_for_reproducibility(monkeypatch):
    """A recorded demo has to replay identically. The hosted models reject
    sampling parameters; locally they are available and worth using."""
    capture: dict = {}
    stub_post(monkeypatch, ollama_reply({"keep": True}), capture)

    call(OllamaModel(), max_tokens=333)

    assert capture["body"]["options"]["temperature"] == 0
    assert capture["body"]["options"]["num_predict"] == 333
    assert capture["body"]["stream"] is False


def test_thinking_is_off_by_default(monkeypatch):
    """Reasoning traces outside the JSON would break the schema contract."""
    capture: dict = {}
    stub_post(monkeypatch, ollama_reply({"keep": True}), capture)
    call(OllamaModel())
    assert capture["body"]["think"] is False


def test_records_the_model_that_actually_ran(monkeypatch):
    """The caller names a hosted model; locally there is only what we loaded.
    Recording what ran matters more than echoing what was asked for."""
    stub_post(monkeypatch, ollama_reply({"keep": True}))
    response = call(OllamaModel(model="qwen3:8b"), model="claude-opus-5")
    assert response.model == "qwen3:8b"


def test_token_counts_come_from_the_server(monkeypatch):
    stub_post(monkeypatch, ollama_reply({"keep": True}, prompt_tokens=512, eval_tokens=64))
    response = call(OllamaModel())
    assert response.input_tokens == 512
    assert response.output_tokens == 64


def test_unreachable_server_says_so_plainly(monkeypatch):
    def _post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _post)
    with pytest.raises(RuntimeError, match="ollama serve"):
        call(OllamaModel())


def test_empty_content_is_an_error_not_an_empty_plan(monkeypatch):
    stub_post(monkeypatch, {"message": {"content": "   "}})
    with pytest.raises(RuntimeError, match="empty content"):
        call(OllamaModel())


def test_unparseable_output_names_what_came_back(monkeypatch):
    stub_post(monkeypatch, {"message": {"content": "Sure! Here is your JSON:"}})
    with pytest.raises(RuntimeError, match="unparseable JSON"):
        call(OllamaModel())


# --- integration -------------------------------------------------------------


def _model_available() -> bool:
    """A live server is not enough — the model has to be pulled.

    Checking only the server made this fail rather than skip on a machine where
    the download had not finished, which is a test bug, not a code bug.
    """
    from latch.config import LOCAL_MODEL

    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0).json()
    except Exception:
        return False
    return any(m.get("name", "").startswith(LOCAL_MODEL.split(":")[0]) for m in tags.get("models", []))


@pytest.mark.skipif(not _model_available(), reason="local model not pulled")
def test_local_model_returns_schema_valid_json():
    """The only claim that matters for the local path: does it hold the schema?"""
    response = call(OllamaModel())
    assert isinstance(response.data.get("keep"), bool)
    assert response.output_tokens > 0

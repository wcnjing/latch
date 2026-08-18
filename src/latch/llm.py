"""The model seam.

Two reasons this exists rather than calling the SDK inline.

The scenario suite has to run on every commit, and a suite that costs money
to run is a suite nobody runs. `FakeModel` is deterministic and free, so the
whole pipeline is testable end to end without a key.

And the recorded demo has to replay identically. A scripted model plus a
scripted failure plan means the video is reproducible on every take.

`AnthropicModel` is the real client. It is selected automatically when a key
is present, and the choice is reported rather than silent — a run that
quietly used the fake model and reported numbers would be worthless.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from latch.config import (
    DELIBERATION_EFFORT,
    EFFORT_CAPABLE_MODELS,
)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int


class ModelClient(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        purpose: str,
    ) -> ModelResponse: ...


class FakeModel:
    """Deterministic stand-in. Answers from a script keyed by purpose.

    Unscripted purposes raise rather than returning something plausible: a
    fake that improvises would let a test pass against a response the real
    model would never produce.
    """

    def __init__(self, script: dict[str, Any] | None = None) -> None:
        self._script: dict[str, list[dict[str, Any]]] = {}
        for purpose, value in (script or {}).items():
            self._script[purpose] = list(value) if isinstance(value, list) else [value]
        self.calls: list[tuple[str, str]] = []

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        purpose: str,
    ) -> ModelResponse:
        self.calls.append((purpose, model))
        queue = self._script.get(purpose)
        if not queue:
            raise KeyError(
                f"FakeModel has no scripted response for purpose {purpose!r}; "
                f"scripted: {sorted(self._script)}"
            )
        data = queue.pop(0) if len(queue) > 1 else queue[0]

        # Token counts scale with the prompt so cost accounting in tests is not
        # uniformly zero, and stay deterministic so fixtures do not drift.
        return ModelResponse(
            data=data,
            model=model,
            input_tokens=len(system) // 4 + len(prompt) // 4,
            output_tokens=len(json.dumps(data)) // 4,
        )


@dataclass
class AnthropicModel:
    """The real client.

    Structured outputs via `output_config.format`, so a malformed plan is a
    schema violation rather than a parsing surprise three steps later.
    """

    client: Any = None
    effort: str = DELIBERATION_EFFORT
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        purpose: str,
    ) -> ModelResponse:
        self.calls.append((purpose, model))

        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": schema}
        }
        # Effort is rejected outright by models that predate it, so it is
        # gated on capability rather than sent hopefully.
        if model in EFFORT_CAPABLE_MODELS:
            output_config["effort"] = self.effort

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )

        if response.stop_reason == "refusal":
            raise RuntimeError(
                f"model declined the {purpose} request "
                f"(category={getattr(response.stop_details, 'category', None)})"
            )

        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"{purpose} response hit max_tokens ({max_tokens}) and is "
                "truncated. On a thinking model the budget covers reasoning "
                "as well as the answer — raise max_tokens or lower effort."
            )

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError(f"no text block in {purpose} response")

        return ModelResponse(
            data=json.loads(text),
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


def _load_dotenv() -> None:
    """Read a local .env so the key lives in a gitignored file, not a shell export.

    Deliberately minimal and non-overriding: an already-set environment
    variable always wins, so a .env cannot silently redirect a run.
    """
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".env"
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return


def get_client(script: dict[str, Any] | None = None) -> tuple[ModelClient, bool]:
    """Return a client and whether it is the real one.

    Callers are expected to record the flag in the trace. A run that silently
    used the fake model and then reported its numbers would be worse than no
    numbers at all.
    """
    _load_dotenv()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicModel(), True
    return FakeModel(script), False

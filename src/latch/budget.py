"""A hard spend ceiling for model calls.

Not a nicety. An agent that loops, retries, or fans out can spend a small
budget in one bad run, and the failure mode is silent until the invoice
arrives. This wraps any `ModelClient` and refuses a call whose worst case
would breach the cap.

The check is *before* the call, using the worst case rather than the likely
case: input tokens estimated from the prompt, output charged at the full
`max_tokens` the request permits. That over-estimates on purpose. A guard that
only notices after the spend is an accountant, not a guard.
"""

from dataclasses import dataclass, field
from typing import Any

from latch.config import PRICING

TOKENS_PER_MILLION = 1_000_000

# Conservative: English averages nearer 4 characters per token, so dividing by
# 3.5 over-counts slightly. Erring toward over-estimating spend is the whole
# point of this module.
CHARS_PER_TOKEN = 3.5


class BudgetExceeded(RuntimeError):
    """Raised before a call that could breach the ceiling."""

    def __init__(self, spent: float, projected: float, limit: float) -> None:
        super().__init__(
            f"refusing model call: spent ${spent:.4f}, this call could reach "
            f"${projected:.4f}, ceiling is ${limit:.2f}"
        )
        self.spent = spent
        self.projected = projected
        self.limit = limit


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def worst_case_usd(model: str, input_text: str, max_tokens: int) -> float:
    """Most this call could possibly cost.

    Output is priced at the full `max_tokens`, because on a thinking model the
    budget covers reasoning as well as the visible answer and a short reply is
    not a guarantee of a small bill.
    """
    in_rate, out_rate = PRICING[model]
    return (
        estimate_tokens(input_text) * in_rate + max_tokens * out_rate
    ) / TOKENS_PER_MILLION


@dataclass
class BudgetGuard:
    """Wraps a ModelClient with a spend ceiling."""

    inner: Any
    limit_usd: float
    spent_usd: float = 0.0
    calls: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def remaining_usd(self) -> float:
        return max(self.limit_usd - self.spent_usd, 0.0)

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        purpose: str,
    ):
        projected = self.spent_usd + worst_case_usd(model, system + prompt, max_tokens)
        if projected > self.limit_usd:
            raise BudgetExceeded(self.spent_usd, projected, self.limit_usd)

        response = self.inner.complete_json(
            model=model,
            system=system,
            prompt=prompt,
            schema=schema,
            max_tokens=max_tokens,
            purpose=purpose,
        )

        in_rate, out_rate = PRICING.get(response.model, PRICING[model])
        actual = (
            response.input_tokens * in_rate + response.output_tokens * out_rate
        ) / TOKENS_PER_MILLION
        self.spent_usd += actual
        self.calls.append((purpose, response.model, actual))
        return response

    def report(self) -> str:
        return (
            f"${self.spent_usd:.4f} spent of ${self.limit_usd:.2f} "
            f"across {len(self.calls)} call(s); "
            f"${self.remaining_usd:.4f} left"
        )

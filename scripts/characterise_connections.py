"""Report what the synthetic connection layer actually produces.

The generated graph is the invented half of LATCH, so its behaviour is a
declarable property of the method rather than an implementation detail. This
prints the severity mix it yields across a sweep of ETA slips, which is the
number to put in the submission beside the frozen parameters — a graph where
nothing is ever at risk, or everything is, would make any downstream result
meaningless.

Run:  uv run python scripts/characterise_connections.py
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from latch.connections import ConnectionParams, connection_for
from latch.watcher import to_risk_event

T0 = datetime(2023, 10, 1, tzinfo=UTC)
SAMPLE = 3_000
SLIPS_H = (0, 1, 2, 4, 6, 9, 12)


@dataclass
class _Signal:
    call_id: str
    vessel_id: str
    observed_at: datetime
    predicted_arrival: datetime | None
    reference_arrival: datetime | None
    data_quality: str = "good"


def main() -> None:
    params = ConnectionParams()
    print("frozen parameters:")
    for key, value in params.as_dict().items():
        print(f"  {key:28} {value}")
    print(f"\nseverity mix over {SAMPLE:,} synthetic connections\n")
    print(f"{'slip':>6}  {'SAFE':>7} {'WATCH':>7} {'AT_RISK':>8}")

    reference = T0 + timedelta(hours=6)
    transfers = 0
    for slip in SLIPS_H:
        counts: Counter[str] = Counter()
        transfers = 0
        for index in range(SAMPLE):
            call_id = f"call_{index:08x}"
            connection = connection_for(call_id, f"v{index}", reference, params)
            transfers += connection.requires_transfer
            event = to_risk_event(
                _Signal(
                    call_id=call_id,
                    vessel_id=f"v{index}",
                    observed_at=T0,
                    predicted_arrival=reference + timedelta(hours=slip),
                    reference_arrival=reference,
                ),
                connection,
            )
            counts[event.state.value] += 1
        print(
            f"{slip:5}h  {counts['SAFE'] / SAMPLE:7.1%} "
            f"{counts['WATCH'] / SAMPLE:7.1%} {counts['AT_RISK'] / SAMPLE:8.1%}"
        )

    print(
        f"\ninter-terminal share: {transfers / SAMPLE:.1%} "
        f"(configured {params.inter_terminal_share:.0%})"
    )
    print(
        "\nThese are properties of a graph we generated, not observations of "
        "Singapore.\nArrival timing is real; the connections are ours."
    )


if __name__ == "__main__":
    main()

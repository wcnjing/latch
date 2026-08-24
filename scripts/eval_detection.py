"""Detection rate and decision lead time, measured on real arrivals.

    uv run python scripts/eval_detection.py --limit 250000

Two numbers the deck needs, neither of which touches the synthetic layer:

  detection rate       of the vessel calls that arrived materially later than
                       the plan in force, what share had we flagged by T-6h
  decision lead time   how long before arrival the first alarm fired — the
                       honest replacement for "connections rescued", which
                       needs a counterfactual no dataset contains

The reference expectation is bias-corrected, and the correction is fitted on
the earlier half of the month and scored on the later half. Read
`latch/detection_eval` before quoting either number: the uncorrected version
of this measurement reports 100% detection with zero false alarms, and that is
a broken measurement rather than a good detector.

Scope: deterioration against our own calibrated estimate, not lateness against
a berth window PSA published — the extract has no official schedule. It
measures the early-warning layer, not the quality of agent decisions.
"""

import argparse
from pathlib import Path

from latch.detection_eval import (
    ALARM_HORIZONS_H,
    CALIBRATION_SPLIT,
    REFERENCE_LEAD_H,
    SLIP_THRESHOLD_H,
    base_rate,
    build_calls,
    calibrate,
    evaluate,
    lead_times,
    split_by_arrival,
)
from latch.eta_eval import Method, collect_predictions
from latch.replay import (
    ArrivalBoundary,
    ReplayConfig,
    causal_eta,
    haversine_km,
    iter_replay_observations,
)

DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent
    / "Data Inspection"
    / "Singapore_anonymized.csv"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"missing {args.csv} — run `git lfs pull`")
        return 2

    config = ReplayConfig()
    predictions, counts = collect_predictions(
        iter_replay_observations(args.csv),
        ArrivalBoundary(),
        haversine_km,
        causal_eta,
        config.minimum_eta_speed_knots,
        limit=args.limit,
    )
    derived = [p for p in predictions if p.method is Method.DERIVED]
    fit, test = split_by_arrival(derived, CALIBRATION_SPLIT)
    bias = calibrate(fit)
    calls, call_counts = build_calls(test, bias)

    print("\nDETECTION — real vessel calls, observed crossings\n")
    print(
        f"  {counts['observations']:,} observations · "
        f"{counts['crossings']:,} crossings · "
        f"{len(derived):,} derived predictions"
    )
    print(
        f"  calibration fitted on {len(fit):,} predictions "
        f"(earlier {CALIBRATION_SPLIT:.0%} by arrival), "
        f"scored on {len(test):,}"
    )

    print("\n  Bias correction applied to the reference (predicted − actual):")
    for bound in sorted(bias):
        print(f"    lead <= {bound:4.0f}h   {bias[bound]:+7.2f}h")

    print(
        f"\n  {call_counts['usable']:,} calls scored "
        f"({call_counts['no_reference']:,} dropped: no estimate at "
        f"T-{REFERENCE_LEAD_H:.0f}h to deteriorate against)"
    )

    if not calls:
        print("\n  nothing to score.\n")
        return 1

    spread = base_rate(calls)
    print(
        f"\n  Slip against the calibrated T-{REFERENCE_LEAD_H:.0f}h expectation: "
        f"median {spread['median_slip_h']:+.2f}h, p90 {spread['p90_slip_h']:+.2f}h"
    )
    print(
        f"  {spread['deteriorated_share']:.1%} of calls slipped "
        f">= {SLIP_THRESHOLD_H:.0f}h — this is the base rate, and what there is to detect"
    )

    print("\n  Did we know yet?\n")
    for horizon in ALARM_HORIZONS_H:
        print(evaluate(calls, horizon).row())

    leads = lead_times(calls)
    print("\n  Decision lead time at first alarm")
    print(leads.row() if leads else "  no alarms fired on deteriorated calls")

    print(
        f"\n  Scope: deterioration against our own calibrated T-{REFERENCE_LEAD_H:.0f}h\n"
        "  estimate, not lateness against a published berth window. Measures the\n"
        "  early-warning layer only, not the quality of agent decisions.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

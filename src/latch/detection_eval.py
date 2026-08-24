"""Did we notice, in time, that an arrival had slipped?

`eta_eval` answers *how wrong* our predictions are. This module answers the
operational question: **how often do we catch a slip, how early, and how often
do we cry wolf** — on real vessels, real trajectories, real observed crossings.

The trap this avoids
--------------------

The obvious framing is "detection rate of connections at risk". That is
circular and worthless: we author the connections, so it scores us against
labels we wrote. Nothing from the synthetic layer appears here. A call, its
reference expectation and its outcome are all observation.

What "late" means here
----------------------

The AIS extract carries no official scheduled arrival — A's dataset assessment
is explicit — and the vessel's own broadcast ETA is frequently for its *next*
port. There is no published schedule to be late against, so this measures
deterioration against the plan in force: our own earlier expectation.

Why that expectation has to be calibrated
------------------------------------------

The first version of this module used the raw kinematic ETA as the reference
and reported 100% detection, 100% precision and zero false alarms. That was
not a result, it was a broken measurement: **every single call "deteriorated"**,
so there were no negatives and recall was 1.0 by construction.

The cause is the finding already in the README. A position-and-speed ETA
ignores queueing, and the median vessel spends most of its final day below one
knot, so at long range the estimate is enormously optimistic:

    lead <= 3h    median signed error   -0.80h
    lead <= 6h                          -2.38h
    lead <= 12h                         -6.97h
    lead <= 24h                        -19.74h

Measuring "arrived >=2h later than the raw T-24h estimate" therefore detects
the estimator's own bias, not any slip. It is worth stating plainly on the
slide: the naive version of this metric produces a perfect score, and the
perfect score is the tell.

So the reference is **bias-corrected** by the median signed error for its lead
bucket, which is the estimator anyone would actually deploy. With correction
the base rate falls to roughly 30%, and recall becomes a number that can fail.

The correction is fitted on the earlier half of the month and every figure is
scored on the later half, so the calibration never sees the calls it is
evaluated on. Without that split the correction would be fitted and tested on
the same data, and a judge would be right to discount it.

Scope, to be stated beside every number this produces: deterioration against
our own calibrated estimate, not lateness against a berth window PSA
published. It measures the early-warning layer. It says nothing about whether
the agent's decisions are good.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from latch.eta_eval import Method, Prediction, percentile

# Lead buckets the bias correction is fitted over. Finer than eta_eval's at the
# long end, because that is where the bias moves fastest.
CALIBRATION_BUCKETS_H: tuple[float, ...] = (1.0, 3.0, 6.0, 12.0, 18.0, 24.0)

# The reference expectation is read from here: the plan in force. Inside
# eta_eval's 24h buffer horizon by a wide margin — a reference at the pruning
# boundary survives on a handful of calls and measures nothing.
REFERENCE_LEAD_H = 12.0

# Slip that counts as material: the order of a transhipment connection window.
SLIP_THRESHOLD_H = 2.0

# Horizons at which we ask "did we know yet?". All strictly inside the
# reference lead, or the question is incoherent.
ALARM_HORIZONS_H: tuple[float, ...] = (1.0, 3.0, 6.0)

# Share of calls, by arrival time, used to fit the correction.
CALIBRATION_SPLIT = 0.5


def bucket_of(lead_h: float) -> float | None:
    for bound in CALIBRATION_BUCKETS_H:
        if lead_h <= bound:
            return bound
    return None


def calibrate(predictions: list[Prediction]) -> dict[float, float]:
    """Median signed error per lead bucket, from the fitting split only.

    Positive means we predicted later than the vessel arrived. Applying the
    negative of this shifts a raw estimate onto the observed central tendency.
    """
    grouped: dict[float, list[float]] = {}
    for prediction in predictions:
        bucket = bucket_of(prediction.lead_time_h)
        if bucket is not None:
            grouped.setdefault(bucket, []).append(prediction.error_h)
    return {b: percentile(errors, 0.5) for b, errors in grouped.items() if errors}


def corrected_arrival(
    prediction: Prediction, bias: dict[float, float]
) -> datetime | None:
    """The estimate an operator would actually be looking at.

    None when the lead time falls in a bucket the fitting split never covered:
    guessing a correction for an unseen horizon is how a calibration starts
    inventing numbers.
    """
    bucket = bucket_of(prediction.lead_time_h)
    if bucket is None or bucket not in bias:
        return None
    return prediction.predicted_arrival - timedelta(hours=bias[bucket])


def split_by_arrival(
    predictions: list[Prediction], fraction: float = CALIBRATION_SPLIT
) -> tuple[list[Prediction], list[Prediction]]:
    """Chronological split. Fit on the earlier calls, score on the later ones."""
    ordered = sorted(predictions, key=lambda p: p.actual_arrival)
    if not ordered:
        return [], []
    cut = ordered[int(len(ordered) * fraction)].actual_arrival
    return (
        [p for p in ordered if p.actual_arrival < cut],
        [p for p in ordered if p.actual_arrival >= cut],
    )


@dataclass(frozen=True, slots=True)
class Call:
    """One observed crossing, with the corrected estimates that preceded it."""

    vessel_id: str
    actual_arrival: datetime
    reference_expected: datetime
    reference_lead_h: float
    #: (lead_time_h, corrected_arrival), oldest first.
    series: tuple[tuple[float, datetime], ...]

    @property
    def slip_h(self) -> float:
        delta = self.actual_arrival - self.reference_expected
        return delta.total_seconds() / 3600.0

    @property
    def deteriorated(self) -> bool:
        return self.slip_h >= SLIP_THRESHOLD_H

    def alarm_at(self, horizon_h: float) -> bool:
        """Had the estimate moved materially later by `horizon_h` before arrival?

        Uses the latest estimate at or before the horizon — what the operator
        had in hand at that moment. Nothing after the horizon is consulted.
        """
        available = [(lead, at) for lead, at in self.series if lead >= horizon_h]
        if not available:
            return False
        _, latest = min(available, key=lambda item: item[0])
        moved = (latest - self.reference_expected).total_seconds() / 3600.0
        return moved >= SLIP_THRESHOLD_H

    def first_alarm_lead_h(self) -> float | None:
        """Lead time of the earliest estimate that crossed the threshold.

        The honest replacement for "connections rescued": not how many boxes
        were saved, which needs a counterfactual no dataset contains, but how
        much time the line would have had to decide.
        """
        for lead, at in self.series:
            moved = (at - self.reference_expected).total_seconds() / 3600.0
            if moved >= SLIP_THRESHOLD_H:
                return lead
        return None


def build_calls(
    predictions: list[Prediction], bias: dict[float, float]
) -> tuple[list[Call], dict[str, int]]:
    """Group scored predictions into calls, each with a corrected reference.

    Calls without an estimate at or beyond `REFERENCE_LEAD_H` are dropped
    rather than given a nearer reference. An expectation formed two hours out
    is not a plan an arrival can be said to have deteriorated against, and
    quietly relaxing the horizon would inflate detection by scoring only easy
    cases.
    """
    grouped: dict[tuple[str, datetime], list[Prediction]] = {}
    for prediction in predictions:
        if prediction.method is Method.DERIVED:
            grouped.setdefault(
                (prediction.vessel_id, prediction.actual_arrival), []
            ).append(prediction)

    calls: list[Call] = []
    counts = {"grouped": len(grouped), "no_reference": 0, "usable": 0}

    for (vessel_id, actual), items in grouped.items():
        series: list[tuple[float, datetime]] = []
        for prediction in sorted(items, key=lambda p: p.made_at):
            at = corrected_arrival(prediction, bias)
            if at is not None:
                series.append((prediction.lead_time_h, at))

        early = [item for item in series if item[0] >= REFERENCE_LEAD_H]
        if not early:
            counts["no_reference"] += 1
            continue

        lead, expected = max(early, key=lambda item: item[0])
        calls.append(
            Call(
                vessel_id=vessel_id,
                actual_arrival=actual,
                reference_expected=expected,
                reference_lead_h=lead,
                series=tuple(series),
            )
        )
        counts["usable"] += 1

    return calls, counts


@dataclass(frozen=True, slots=True)
class DetectionStats:
    horizon_h: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    @property
    def positives(self) -> int:
        return self.true_positive + self.false_negative

    @property
    def recall(self) -> float | None:
        """The detection rate. None when nothing deteriorated to detect."""
        return self.true_positive / self.positives if self.positives else None

    @property
    def precision(self) -> float | None:
        flagged = self.true_positive + self.false_positive
        return self.true_positive / flagged if flagged else None

    @property
    def false_alarm_rate(self) -> float | None:
        """Share of healthy calls flagged anyway.

        Printed beside recall always. A detector that flags everything scores
        100% recall, which is exactly how the first version of this module
        fooled itself.
        """
        negatives = self.false_positive + self.true_negative
        return self.false_positive / negatives if negatives else None

    def row(self) -> str:
        def pct(value: float | None) -> str:
            return f"{value:6.1%}" if value is not None else "     -"

        return (
            f"  by T-{self.horizon_h:3.0f}h   "
            f"detected {pct(self.recall)}   "
            f"precision {pct(self.precision)}   "
            f"false alarms {pct(self.false_alarm_rate)}   "
            f"(tp {self.true_positive:4,} fn {self.false_negative:4,} "
            f"fp {self.false_positive:4,} tn {self.true_negative:4,})"
        )


def evaluate(calls: list[Call], horizon_h: float) -> DetectionStats:
    tp = fp = fn = tn = 0
    for call in calls:
        alarmed = call.alarm_at(horizon_h)
        if call.deteriorated:
            tp, fn = (tp + 1, fn) if alarmed else (tp, fn + 1)
        else:
            fp, tn = (fp + 1, tn) if alarmed else (fp, tn + 1)
    return DetectionStats(horizon_h, tp, fp, fn, tn)


@dataclass(frozen=True, slots=True)
class LeadTimeStats:
    count: int
    median_h: float
    p25_h: float
    p75_h: float

    def row(self) -> str:
        return (
            f"  n={self.count:,}   median {self.median_h:.2f}h   "
            f"(p25 {self.p25_h:.2f}h, p75 {self.p75_h:.2f}h)"
        )


def lead_times(calls: list[Call]) -> LeadTimeStats | None:
    """Lead time at first alarm, over calls that genuinely deteriorated."""
    leads = [
        lead
        for call in calls
        if call.deteriorated
        for lead in [call.first_alarm_lead_h()]
        if lead is not None
    ]
    if not leads:
        return None
    return LeadTimeStats(
        count=len(leads),
        median_h=percentile(leads, 0.5),
        p25_h=percentile(leads, 0.25),
        p75_h=percentile(leads, 0.75),
    )


def base_rate(calls: list[Call]) -> dict[str, float]:
    """The share that deteriorated, and how far.

    Reported first, because a detection rate is uninterpretable without it. If
    this reads 100%, the measurement is broken rather than the detector perfect.
    """
    slips = [c.slip_h for c in calls]
    if not slips:
        return {}
    return {
        "median_slip_h": percentile(slips, 0.5),
        "p90_slip_h": percentile(slips, 0.9),
        "deteriorated_share": sum(1 for s in slips if s >= SLIP_THRESHOLD_H)
        / len(slips),
    }

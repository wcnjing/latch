"""Detection evaluation.

The first version of this module scored 100% detection, 100% precision and
zero false alarms, and the reason was that the uncalibrated reference made
every call "deteriorate" — no negatives existed, so recall was 1.0 by
construction. `test_a_perfect_score_means_the_measurement_broke` is the guard
against that specific failure returning, because a broken measurement here
looks like a triumph rather than a bug.
"""

from datetime import UTC, datetime, timedelta

import pytest

from latch.detection_eval import (
    REFERENCE_LEAD_H,
    SLIP_THRESHOLD_H,
    Call,
    base_rate,
    build_calls,
    calibrate,
    corrected_arrival,
    evaluate,
    lead_times,
    split_by_arrival,
)
from latch.eta_eval import Method, Prediction

T0 = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def pred(lead_h: float, error_h: float, arrival: datetime = T0, vessel: str = "v1"):
    """A prediction made `lead_h` before `arrival`, wrong by `error_h`."""
    return Prediction(
        vessel_id=vessel,
        method=Method.DERIVED,
        made_at=arrival - timedelta(hours=lead_h),
        predicted_arrival=arrival + timedelta(hours=error_h),
        actual_arrival=arrival,
    )


def call(reference_expected_offset_h: float, series: list[tuple[float, float]]) -> Call:
    """A call, with every time expressed as hours relative to the real arrival.

    `reference_expected_offset_h` is where we expected the vessel: -5 means we
    expected it five hours before it actually came, which is a 5h slip.
    `series` entries are (lead_time_h, estimate_offset_h); an estimate alarms
    when it sits `SLIP_THRESHOLD_H` later than the reference.
    """
    return Call(
        vessel_id="v1",
        actual_arrival=T0,
        reference_expected=T0 + timedelta(hours=reference_expected_offset_h),
        reference_lead_h=REFERENCE_LEAD_H,
        series=tuple(
            (lead, T0 + timedelta(hours=offset)) for lead, offset in series
        ),
    )


# --- calibration ------------------------------------------------------------


def test_calibration_finds_the_median_bias_per_bucket():
    predictions = [pred(2.0, -1.0), pred(2.0, -3.0), pred(2.0, -2.0)]
    assert calibrate(predictions)[3.0] == pytest.approx(-2.0)


def test_correction_shifts_an_estimate_onto_the_observed_arrival():
    """A -2h bias means we predict two hours early; correcting adds it back."""
    p = pred(2.0, -2.0)
    assert corrected_arrival(p, {3.0: -2.0}) == T0


def test_an_uncalibrated_bucket_returns_no_estimate():
    """Guessing a correction for a horizon the fit never saw is how a
    calibration starts inventing numbers."""
    assert corrected_arrival(pred(2.0, -2.0), {}) is None


def test_the_split_never_lets_calibration_see_what_it_scores():
    early = [pred(2.0, -1.0, arrival=T0 - timedelta(days=d)) for d in (9, 8, 7, 6)]
    late = [pred(2.0, -1.0, arrival=T0 + timedelta(days=d)) for d in (1, 2, 3, 4)]
    fit, test = split_by_arrival(early + late, 0.5)
    assert fit and test
    assert max(p.actual_arrival for p in fit) < min(p.actual_arrival for p in test)


# --- the guard against the original bug -------------------------------------


def test_a_perfect_score_means_the_measurement_broke():
    """Every call deteriorating is the signature of an uncalibrated reference.

    Recall reads 100% and there are no negatives at all. The base rate is what
    exposes it, which is why it is printed above the detection rate rather
    than below it.
    """
    calls = [call(-10.0, [(6.0, 0.0)]) for _ in range(20)]  # every arrival 10h late
    stats = evaluate(calls, 6.0)

    assert stats.recall == 1.0
    assert stats.false_alarm_rate is None, "no negatives exist to raise an alarm on"
    assert base_rate(calls)["deteriorated_share"] == 1.0


def test_a_detector_that_flags_everything_is_visible_in_the_false_alarm_rate():
    """Recall alone cannot distinguish a good detector from an indiscriminate
    one. This is why the two are always printed together."""
    deteriorated = call(-5.0, [(6.0, 0.0)])
    healthy = call(0.0, [(6.0, 5.0)])  # alarms despite arriving on time
    stats = evaluate([deteriorated, healthy], 6.0)

    assert stats.recall == 1.0
    assert stats.false_alarm_rate == 1.0
    assert stats.precision == 0.5


# --- classification ---------------------------------------------------------


def test_a_slip_past_the_threshold_counts_as_deterioration():
    assert call(-SLIP_THRESHOLD_H - 0.1, []).deteriorated
    assert not call(-SLIP_THRESHOLD_H + 0.1, []).deteriorated


def test_an_alarm_never_reads_an_estimate_from_after_its_horizon():
    """The T-6h question must be answerable at T-6h. An estimate made at T-1h
    is the future and would make every alarm trivially correct."""
    c = call(0.0, [(12.0, 0.0), (6.0, 0.0), (1.0, 10.0)])
    assert not c.alarm_at(6.0), "the 1h estimate must not be consulted"
    assert c.alarm_at(1.0)


def test_the_latest_estimate_inside_the_horizon_is_the_one_used():
    """What the operator had in hand at that moment, not the earliest guess."""
    c = call(0.0, [(12.0, 10.0), (7.0, 0.0)])
    assert not c.alarm_at(6.0)


def test_no_estimate_at_the_horizon_is_not_an_alarm():
    assert not call(0.0, [(0.5, 10.0)]).alarm_at(6.0)


def test_the_four_outcomes_are_counted_where_they_belong():
    calls = [
        call(-5.0, [(6.0, 0.0)]),  # slipped, flagged       -> tp
        call(-5.0, [(6.0, -5.0)]),  # slipped, missed       -> fn
        call(0.0, [(6.0, 5.0)]),  # fine, flagged           -> fp
        call(0.0, [(6.0, 0.0)]),  # fine, quiet             -> tn
    ]
    stats = evaluate(calls, 6.0)
    assert (stats.true_positive, stats.false_negative) == (1, 1)
    assert (stats.false_positive, stats.true_negative) == (1, 1)
    assert stats.recall == 0.5
    assert stats.precision == 0.5


# --- lead time --------------------------------------------------------------


def test_lead_time_reports_the_earliest_crossing_not_the_latest():
    """The claim is how much time the line would have had, so it is the first
    moment we could have told them, not the last."""
    c = call(-5.0, [(20.0, 0.0), (6.0, 0.0), (1.0, 0.0)])
    assert c.first_alarm_lead_h() == 20.0
    assert lead_times([c]).median_h == 20.0


def test_lead_time_ignores_calls_that_never_deteriorated():
    """A false alarm bought nobody any decision time."""
    assert lead_times([call(0.0, [(6.0, 5.0)])]) is None


# --- call construction ------------------------------------------------------


def test_a_call_without_a_long_range_estimate_is_dropped():
    """Relaxing the reference horizon would inflate detection by scoring only
    the easy cases."""
    bias = {3.0: 0.0, 12.0: 0.0}
    _, counts = build_calls([pred(2.0, 0.0)], bias)
    assert counts["usable"] == 0
    assert counts["no_reference"] == 1


def test_a_call_with_a_long_range_estimate_is_scored():
    bias = {18.0: 0.0, 3.0: 0.0}
    calls, counts = build_calls([pred(13.0, 0.0), pred(2.0, 0.0)], bias)
    assert counts["usable"] == 1
    assert calls[0].reference_lead_h == 13.0

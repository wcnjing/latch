"""ETA evaluation tests. Causality is the property that matters."""

from datetime import UTC, datetime, timedelta

import pytest

from latch.eta_eval import Method, Prediction, percentile, summarise

T0 = datetime(2023, 10, 1, tzinfo=UTC)


def prediction(lead_h: float, error_h: float, method: Method = Method.DERIVED):
    actual = T0 + timedelta(hours=24)
    return Prediction(
        vessel_id="v1",
        method=method,
        made_at=actual - timedelta(hours=lead_h),
        predicted_arrival=actual + timedelta(hours=error_h),
        actual_arrival=actual,
    )


def test_error_sign_says_which_mistake_we_made():
    """Predicting late makes a fine connection look doomed; predicting early
    does the opposite. Reporting only magnitude hides which one we do."""
    assert prediction(6, +2.0).error_h == pytest.approx(2.0)
    assert prediction(6, -2.0).error_h == pytest.approx(-2.0)
    assert prediction(6, -2.0).abs_error_h == pytest.approx(2.0)


def test_lead_time_is_measured_back_from_the_observed_arrival():
    assert prediction(6, 0).lead_time_h == pytest.approx(6.0)


def test_buckets_take_the_smallest_bound_that_contains_the_lead():
    assert prediction(0.5, 0).bucket() == 1.0
    assert prediction(2.0, 0).bucket() == 3.0
    assert prediction(5.0, 0).bucket() == 6.0
    assert prediction(20.0, 0).bucket() == 24.0


def test_predictions_made_after_arrival_are_not_predictions():
    after = Prediction(
        vessel_id="v1",
        method=Method.DERIVED,
        made_at=T0 + timedelta(hours=2),
        predicted_arrival=T0 + timedelta(hours=3),
        actual_arrival=T0,
    )
    assert after.bucket() is None
    assert summarise([after]) == []


def test_leads_beyond_the_widest_bucket_are_dropped_not_lumped_in():
    """Silently folding a 40-hour lead into the 24-hour bucket would make that
    bucket's error look worse than the thing it claims to measure."""
    assert prediction(40, 0).bucket() is None


def test_summary_separates_methods():
    rows = summarise(
        [prediction(6, 1.0, Method.DERIVED), prediction(6, 9.0, Method.AIS_DECLARED)]
    )
    assert {r.method for r in rows} == {Method.DERIVED, Method.AIS_DECLARED}


def test_empty_buckets_are_omitted_rather_than_reported_as_zero():
    """A zero-error bucket with no data in it reads as perfect accuracy."""
    rows = summarise([prediction(6, 1.0)])
    assert [r.lead_bucket_h for r in rows] == [6.0]


def test_within_thresholds_count_what_they_say():
    rows = summarise([prediction(6, 0.5), prediction(6, 2.0), prediction(6, 9.0)])
    assert rows[0].within_1h == pytest.approx(1 / 3)
    assert rows[0].within_3h == pytest.approx(2 / 3)


def test_percentile_interpolates_and_survives_degenerate_input():
    assert percentile([1.0, 2.0, 3.0], 0.5) == pytest.approx(2.0)
    assert percentile([5.0], 0.9) == pytest.approx(5.0)
    assert percentile([], 0.5) != percentile([], 0.5)  # nan

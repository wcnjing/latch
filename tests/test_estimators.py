"""Estimator tests. Causality and honest declining are the properties."""

from datetime import UTC, datetime, timedelta

import pytest

from latch.estimators import ClosingRate, InstantaneousSpeed, MedianSpeed

T0 = datetime(2023, 10, 1, tzinfo=UTC)


def test_instantaneous_declines_below_the_speed_floor():
    est = InstantaneousSpeed(minimum_speed_knots=0.5)
    assert est.predict("v1", T0, 100.0, 0.1) is None
    assert est.predict("v1", T0, 100.0, None) is None
    assert est.predict("v1", T0, 100.0, 10.0) is not None


def test_instantaneous_scales_with_distance_and_speed():
    est = InstantaneousSpeed()
    near = est.predict("v1", T0, 18.52, 10.0)
    far = est.predict("v1", T0, 37.04, 10.0)
    assert (near - T0) == pytest.approx(timedelta(hours=1), abs=timedelta(minutes=1))
    assert (far - T0) > (near - T0)


def test_median_speed_needs_history_before_it_will_predict():
    est = MedianSpeed(minimum_observations=3)
    assert est.predict("v1", T0, 50.0, 10.0) is None
    assert est.predict("v1", T0 + timedelta(minutes=10), 48.0, 10.0) is None
    assert est.predict("v1", T0 + timedelta(minutes=20), 46.0, 10.0) is not None


def test_median_speed_ignores_a_momentary_slowdown():
    """A vessel that drops to two knots in traffic has not changed its arrival
    time much, and the instantaneous estimator believes it has."""
    median = MedianSpeed(minimum_observations=3)
    instant = InstantaneousSpeed()
    for i in range(4):
        median.predict("v1", T0 + timedelta(minutes=10 * i), 50.0 - i, 12.0)

    dip_at = T0 + timedelta(minutes=50)
    smoothed = median.predict("v1", dip_at, 45.0, 2.0)
    naive = instant.predict("v1", dip_at, 45.0, 2.0)
    assert smoothed < naive


def test_closing_rate_declines_when_the_vessel_is_not_approaching():
    """Stationary, drifting or heading away is not an arrival in progress —
    and this is the anchored-vessel filter, arrived at for free."""
    est = ClosingRate(minimum_observations=3)
    for i in range(4):
        result = est.predict("v1", T0 + timedelta(hours=i), 50.0, 0.2)
    assert result is None


def test_closing_rate_declines_when_the_vessel_is_receding():
    est = ClosingRate(minimum_observations=3)
    for i in range(4):
        result = est.predict("v1", T0 + timedelta(hours=i), 50.0 + i * 5, 12.0)
    assert result is None


def test_closing_rate_predicts_from_observed_progress_not_speed():
    """Speed over ground is never consulted, so a tangential heading cannot
    inflate the estimate."""
    est = ClosingRate(minimum_observations=3)
    for i in range(3):
        est.predict("v1", T0 + timedelta(hours=i), 30.0 - 10.0 * i, None)
    predicted = est.predict("v1", T0 + timedelta(hours=3), 0.5, None)
    assert predicted is not None
    assert predicted - (T0 + timedelta(hours=3)) < timedelta(hours=1)


def test_reset_clears_only_the_named_vessel():
    est = ClosingRate(minimum_observations=2)
    for i in range(3):
        est.predict("v1", T0 + timedelta(hours=i), 30.0 - 5 * i, 10.0)
        est.predict("v2", T0 + timedelta(hours=i), 30.0 - 5 * i, 10.0)
    est.reset("v1")
    assert est.predict("v1", T0 + timedelta(hours=3), 15.0, 10.0) is None
    assert est.predict("v2", T0 + timedelta(hours=3), 15.0, 10.0) is not None


def test_estimators_only_ever_look_backwards():
    """Feeding the same prefix must give the same answer regardless of what
    comes later — otherwise the evaluation is measuring lookahead."""
    def run(extra: int) -> object:
        est = ClosingRate(minimum_observations=3)
        out = None
        for i in range(3):
            out = est.predict("v1", T0 + timedelta(hours=i), 30.0 - 8 * i, 10.0)
        for i in range(extra):
            est.predict("v1", T0 + timedelta(hours=10 + i), 5.0, 1.0)
        return out

    assert run(0) == run(5)

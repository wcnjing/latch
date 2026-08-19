import csv
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from latch.replay import (
    ArrivalBoundary,
    CausalArrivalUpdate,
    DataQuality,
    PredictionStatus,
    QualityFlag,
    ReplayConfig,
    assess_arrival_feasibility,
    causal_eta,
    derive_arrival_calls,
    iter_arrival_updates,
    iter_causal_arrival_updates,
    iter_replay_observations,
)


FIELDS = [
    "UserID",
    "timestamp",
    "Latitude",
    "Longitude",
    "speed",
    "Cog",
    "TrueHeading",
    "RateOfTurn",
    "NavigationalStatus",
    "ShipType",
    "EtaMonth",
    "EtaDay",
    "EtaHour",
    "EtaMinute",
]


def write_csv(tmp_path, rows):
    path = tmp_path / "ais.csv"
    with path.open("w", encoding="ascii", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(vessel, timestamp, longitude, **overrides):
    value = {
        "UserID": vessel,
        "timestamp": timestamp,
        "Latitude": "0",
        "Longitude": str(longitude),
        "speed": "10",
        "Cog": "90",
        "TrueHeading": "90",
        "RateOfTurn": "0",
        "NavigationalStatus": "0",
        "ShipType": "70",
        "EtaMonth": "1",
        "EtaDay": "2",
        "EtaHour": "3",
        "EtaMinute": "4",
    }
    value.update({key: str(item) for key, item in overrides.items()})
    return value


def config(**overrides):
    values = {
        "boundary": ArrivalBoundary(0, 0, 10),
        "minimum_track_observations": 1,
        "minimum_pre_arrival_observations": 1,
    }
    values.update(overrides)
    return ReplayConfig(**values)


def test_replay_is_globally_sorted_and_ties_use_source_row(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("late", "2023-01-01 02:00:00.000000001", 2),
            row("tie-first", "2023-01-01 01:00:00.000000002", 2),
            row("tie-second", "2023-01-01 01:00:00.000000002", 2),
        ],
    )

    observations = list(iter_replay_observations(path, config()))

    assert [item.vessel_id for item in observations] == ["tie-first", "tie-second", "late"]
    assert [item.source_row_number for item in observations] == [3, 4, 2]
    assert all(item.observed_at.tzinfo is UTC for item in observations)


def test_causal_eta_does_not_change_when_future_rows_change(tmp_path):
    common = [
        row("v1", "2023-01-01 00:00:00", 1),
        row("v1", "2023-01-01 01:00:00", 0.5),
    ]
    path_a = write_csv(tmp_path, common + [row("v1", "2023-01-01 02:00:00", 0)])
    first_a = next(iter_replay_observations(path_a, config()))
    eta_a = causal_eta(first_a, config().boundary)

    path_b = write_csv(tmp_path, common + [row("v1", "2023-01-01 20:00:00", -20)])
    first_b = next(iter_replay_observations(path_b, config()))
    eta_b = causal_eta(first_b, config().boundary)

    assert eta_a == eta_b


def test_recognised_ais_sentinels_are_unavailable(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row(
                "v1",
                "2023-01-01 00:00:00",
                1,
                speed=102.3,
                Cog=360,
                TrueHeading=511,
                RateOfTurn=-128,
                NavigationalStatus=15,
                EtaMonth=0,
            )
        ],
    )

    observation = next(iter_replay_observations(path, config()))

    assert observation.speed_over_ground_knots is None
    assert observation.course_over_ground_degrees is None
    assert observation.true_heading_degrees is None
    assert observation.rate_of_turn is None
    assert observation.navigation_status is None
    assert observation.ais_reported_eta is None
    assert QualityFlag.SPEED_UNAVAILABLE in observation.quality_flags
    assert QualityFlag.COURSE_UNAVAILABLE in observation.quality_flags
    assert QualityFlag.HEADING_UNAVAILABLE in observation.quality_flags
    assert QualityFlag.RATE_OF_TURN_UNAVAILABLE in observation.quality_flags
    assert QualityFlag.IMPLAUSIBLE_SPEED not in observation.quality_flags


def test_low_quality_rows_are_preserved_and_can_be_excluded_from_events(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("sparse", "2023-01-01 00:00:00", 1, speed=60),
            row("sparse", "2023-01-01 01:00:00", 0),
        ],
    )
    replay_config = config(
        minimum_track_observations=10,
        excluded_quality_flags=frozenset(
            {QualityFlag.SPARSE_VESSEL_TRACK, QualityFlag.IMPLAUSIBLE_SPEED}
        ),
    )

    observations = list(iter_replay_observations(path, replay_config))
    result = assess_arrival_feasibility(path, replay_config)
    call = derive_arrival_calls(path, replay_config)[0]

    assert len(observations) == 2
    assert QualityFlag.SPARSE_VESSEL_TRACK in observations[0].quality_flags
    assert QualityFlag.IMPLAUSIBLE_SPEED in observations[0].quality_flags
    assert result.vessels_crossing_boundary == 1
    assert result.usable_derived_arrival_events == 0
    assert result.event_exclusion_reasons == {
        "fewer_than_10_vessel_observations": 1,
        "insufficient_eligible_pre_arrival_observations": 1,
    }
    assert call.arrival_updates[0].prediction_status is PredictionStatus.INELIGIBLE
    assert call.arrival_updates[0].predicted_arrival is None
    assert "implausible_speed" in call.arrival_updates[0].quality_reason_codes


def test_stale_and_long_gap_rows_are_preserved_and_flagged(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 1),
            row("v1", "2023-01-01 02:00:00", 0.5),
            row("v1", "2023-01-01 10:00:00", 0),
        ],
    )

    observations = list(iter_replay_observations(path, config()))

    assert len(observations) == 3
    assert observations[0].quality_flags == ()
    assert QualityFlag.STALE_OBSERVATION in observations[1].quality_flags
    assert QualityFlag.LONG_OBSERVATION_GAP not in observations[1].quality_flags
    assert QualityFlag.STALE_OBSERVATION in observations[2].quality_flags
    assert QualityFlag.LONG_OBSERVATION_GAP in observations[2].quality_flags


def test_feasibility_is_deterministic_and_names_event_as_derived(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 1),
            row("v1", "2023-01-01 01:00:00", 0.5),
            row("v1", "2023-01-01 02:00:00", 0),
        ],
    )
    replay_config = config(sufficient_arrival_events=1)

    first = assess_arrival_feasibility(path, replay_config)
    second = assess_arrival_feasibility(path, replay_config)

    assert first == second
    assert first.vessels_crossing_boundary == 1
    assert first.usable_derived_arrival_events == 1
    assert first.sufficient_for_historical_experiment
    event = first.example_eta_revisions[0]
    assert event.derived_geofence_arrival == datetime(2023, 1, 1, 2, tzinfo=UTC)
    assert event.observations_before_event == 2
    assert event.available_lookback == timedelta(hours=2)


def test_crossings_require_confirmed_reset_before_a_repeat_call(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("repeat", "2023-01-01 00:00:00", 0.10),
            row("repeat", "2023-01-01 00:10:00", 0.08),
            row("repeat", "2023-01-01 00:20:00", 0.10),
            row("repeat", "2023-01-01 00:30:00", 0.08),
            # One isolated point beyond the reset radius is insufficient.
            row("repeat", "2023-01-01 01:00:00", 0.13),
            row("repeat", "2023-01-01 01:10:00", 0.10),
            row("repeat", "2023-01-01 01:20:00", 0.08),
            # Two consecutive points beyond it rearm the vessel.
            row("repeat", "2023-01-01 02:00:00", 0.13),
            row("repeat", "2023-01-01 02:10:00", 0.12),
            row("repeat", "2023-01-01 02:20:00", 0.08),
        ],
    )

    result = assess_arrival_feasibility(path, config())
    calls = derive_arrival_calls(path, config())

    assert result.raw_candidate_crossings == 4
    assert result.crossings_suppressed_before_reset == 2
    assert result.accepted_calls == 2
    assert len(calls) == 2
    assert calls[0].vessel_id == calls[1].vessel_id == "repeat"
    assert calls[0].call_id != calls[1].call_id
    assert all(call.boundary_version == "exploratory-circle-v1" for call in calls)


def test_call_ids_and_predictions_are_deterministic(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.3, speed=12),
            row("v1", "2023-01-01 00:10:00", 0.2, speed=10),
            row("v1", "2023-01-01 00:20:00", 0, speed=8),
        ],
    )

    assert derive_arrival_calls(path, config()) == derive_arrival_calls(path, config())
    assert tuple(iter_arrival_updates(path, config())) == tuple(
        iter_arrival_updates(path, config())
    )


def test_update_predictions_do_not_use_future_points_or_crossing_time(tmp_path):
    early = [row("v1", "2023-01-01 00:00:00", 0.3, speed=12)]
    path_a = write_csv(
        tmp_path,
        early + [row("v1", "2023-01-01 01:00:00", 0, speed=2)],
    )
    update_a = tuple(iter_arrival_updates(path_a, config()))[0]
    path_b = write_csv(
        tmp_path,
        early
        + [
            row("v1", "2023-01-01 00:30:00", 0.2, speed=4),
            row("v1", "2023-01-01 02:00:00", 0, speed=20),
        ],
    )
    update_b = tuple(iter_arrival_updates(path_b, config()))[0]

    assert update_a.predicted_arrival == update_b.predicted_arrival
    assert update_a.reference_arrival == update_b.reference_arrival
    assert update_a.observed_at == update_b.observed_at
    assert update_a.source_observation == update_b.source_observation


def test_reference_is_first_eligible_prediction_and_ineligible_rows_are_retained_as_quality(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.3, speed=0),
            row("v1", "2023-01-01 00:10:00", 0.2, speed=10),
            row("v1", "2023-01-01 00:20:00", 0.25, speed=10),
            row("v1", "2023-01-01 00:30:00", 0.15, speed=8),
            row("v1", "2023-01-01 00:40:00", 0, speed=5),
        ],
    )
    call = derive_arrival_calls(path, config())[0]

    assert call.usable
    assert call.first_eligible_pre_event_observation.observed_at == datetime(
        2023, 1, 1, 0, 10, tzinfo=UTC
    )
    assert call.eligible_pre_event_observations == 2
    assert "zero_or_near_zero_speed" in call.quality_reason_codes
    assert "moving_away_from_boundary" in call.quality_reason_codes
    assert len(call.arrival_updates) == 4
    assert call.arrival_updates[0].prediction_status is PredictionStatus.INELIGIBLE
    assert call.arrival_updates[0].predicted_arrival is None
    assert call.arrival_updates[0].reference_arrival is None
    first_available = call.arrival_updates[1]
    assert first_available.prediction_status is PredictionStatus.AVAILABLE
    assert first_available.reference_arrival == first_available.predicted_arrival
    assert call.arrival_updates[2].prediction_status is PredictionStatus.INELIGIBLE
    assert call.arrival_updates[2].predicted_arrival is None
    assert "moving_away_from_boundary" in call.arrival_updates[2].quality_reason_codes
    assert call.arrival_updates[3].reference_arrival == first_available.reference_arrival


def test_stale_observation_is_not_used_for_prediction(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.3),
            row("v1", "2023-01-01 02:00:00", 0.2),
            row("v1", "2023-01-01 02:10:00", 0),
        ],
    )
    call = derive_arrival_calls(path, config())[0]

    assert call.usable
    assert len(call.arrival_updates) == 2
    assert call.arrival_updates[0].observed_at == datetime(2023, 1, 1, tzinfo=UTC)
    assert call.arrival_updates[1].prediction_status is PredictionStatus.INELIGIBLE
    assert call.arrival_updates[1].predicted_arrival is None
    assert "stale_observation" in call.arrival_updates[1].quality_reason_codes
    assert QualityFlag.STALE_OBSERVATION.value in call.quality_reason_codes
    assert call.data_quality is DataQuality.DEGRADED


def test_update_stream_is_stably_sorted_and_preserves_provenance_and_flags(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("later-call", "2023-01-01 00:00:00", 0.3),
            row("first-call", "2023-01-01 00:00:00", 0.2, TrueHeading=511),
            row("first-call", "2023-01-01 00:20:00", 0),
            row("later-call", "2023-01-01 00:30:00", 0),
        ],
    )
    updates = tuple(iter_arrival_updates(path, config()))

    assert [update.vessel_id for update in updates] == ["later-call", "first-call"]
    assert [update.source_observation.source_row_number for update in updates] == [2, 3]
    flagged = updates[1]
    assert flagged.source_type == "real_ais_observation"
    assert flagged.observation_age_minutes == 0
    assert flagged.source_observation.true_heading_degrees is None
    assert QualityFlag.HEADING_UNAVAILABLE in flagged.source_observation.quality_flags
    assert QualityFlag.HEADING_UNAVAILABLE.value in flagged.quality_reason_codes
    assert flagged.data_quality is DataQuality.DEGRADED
    assert "derived_geofence_arrival" not in {
        field.name for field in fields(CausalArrivalUpdate)
    }


def test_unavailable_or_implausible_speed_can_exclude_a_call_without_fabrication(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.2, speed=102.3),
            row("v1", "2023-01-01 00:10:00", 0),
        ],
    )
    call = derive_arrival_calls(path, config())[0]

    assert not call.usable
    assert len(call.arrival_updates) == 1
    assert call.arrival_updates[0].prediction_status is PredictionStatus.INELIGIBLE
    assert call.arrival_updates[0].predicted_arrival is None
    assert call.arrival_updates[0].reference_arrival is None
    assert "speed_unavailable" in call.arrival_updates[0].quality_reason_codes
    assert call.first_eligible_pre_event_observation is None
    assert "speed_unavailable" in call.quality_reason_codes
    assert "insufficient_eligible_pre_arrival_observations" in call.exclusion_reasons


def test_watcher_projection_has_no_retrospective_crossing_outcome(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.3),
            row("v1", "2023-01-01 00:10:00", 0),
        ],
    )

    update = tuple(iter_causal_arrival_updates(path, config()))[0]

    assert isinstance(update, CausalArrivalUpdate)
    assert not hasattr(update, "derived_geofence_arrival")
    assert derive_arrival_calls(path, config())[0].derived_geofence_arrival > update.observed_at


def test_long_gap_starts_a_new_reference_segment(tmp_path):
    path = write_csv(
        tmp_path,
        [
            row("v1", "2023-01-01 00:00:00", 0.5, speed=10),
            row("v1", "2023-01-01 08:00:00", 0.3, speed=10),
            row("v1", "2023-01-01 08:10:00", 0.2, speed=8),
            row("v1", "2023-01-01 08:20:00", 0.15, speed=6),
            row("v1", "2023-01-01 08:30:00", 0, speed=5),
        ],
    )
    call = derive_arrival_calls(path, config())[0]

    assert [update.observed_at.hour for update in call.arrival_updates] == [8, 8, 8]
    gap_update, reference_update, later_update = call.arrival_updates
    assert gap_update.prediction_status is PredictionStatus.INELIGIBLE
    assert gap_update.predicted_arrival is None
    assert gap_update.reference_arrival is None
    assert "long_observation_gap" in gap_update.quality_reason_codes
    assert reference_update.prediction_status is PredictionStatus.AVAILABLE
    assert reference_update.reference_arrival == reference_update.predicted_arrival
    assert later_update.reference_arrival == reference_update.reference_arrival
    assert call.first_eligible_pre_event_observation == reference_update.source_observation
    assert call.pre_event_lookback == timedelta(minutes=20)


def test_future_observations_cannot_change_predictions_at_or_before_t(tmp_path):
    shared = [
        row("v1", "2023-01-01 00:00:00", 0.3, speed=12),
        row("v1", "2023-01-01 00:10:00", 0.2, speed=8),
    ]
    path_a = write_csv(
        tmp_path,
        shared + [row("v1", "2023-01-01 00:20:00", 0, speed=5)],
    )
    before = tuple(iter_causal_arrival_updates(path_a, config()))
    path_b = write_csv(
        tmp_path,
        shared
        + [
            row("v1", "2023-01-01 00:15:00", 0.15, speed=2),
            row("v1", "2023-01-01 00:50:00", 0, speed=1),
        ],
    )
    after = tuple(iter_causal_arrival_updates(path_b, config()))

    cutoff = datetime(2023, 1, 1, 0, 10, tzinfo=UTC)
    causal_fields = lambda update: (
        update.observed_at,
        update.prediction_status,
        update.reference_arrival,
        update.predicted_arrival,
        update.quality_reason_codes,
        update.source_observation,
    )
    assert [causal_fields(update) for update in before if update.observed_at <= cutoff] == [
        causal_fields(update) for update in after if update.observed_at <= cutoff
    ]

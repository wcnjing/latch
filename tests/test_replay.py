import csv
from datetime import UTC, datetime, timedelta

from latch.replay import (
    ArrivalBoundary,
    QualityFlag,
    ReplayConfig,
    assess_arrival_feasibility,
    causal_eta,
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

    assert len(observations) == 2
    assert QualityFlag.SPARSE_VESSEL_TRACK in observations[0].quality_flags
    assert QualityFlag.IMPLAUSIBLE_SPEED in observations[0].quality_flags
    assert result.vessels_crossing_boundary == 1
    assert result.usable_derived_arrival_events == 0
    assert result.event_exclusion_reasons == {"fewer_than_10_vessel_observations": 1}


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

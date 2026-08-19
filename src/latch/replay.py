"""Disk-backed AIS replay and exploratory arrival-event feasibility.

The primary CSV timestamp has no documented timezone.  UTC is the current,
explicitly unconfirmed default assumption.  The arrival boundary is likewise
an exploratory project input, not an official PSA terminal or berth boundary.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from enum import StrEnum
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo


class QualityFlag(StrEnum):
    SPARSE_VESSEL_TRACK = "fewer_than_10_vessel_observations"
    STALE_OBSERVATION = "stale_observation"
    LONG_OBSERVATION_GAP = "long_observation_gap"
    IMPLAUSIBLE_SPEED = "implausible_speed"
    HEADING_UNAVAILABLE = "heading_unavailable"
    RATE_OF_TURN_UNAVAILABLE = "rate_of_turn_unavailable"


@dataclass(frozen=True, slots=True)
class ArrivalBoundary:
    """Exploratory circular arrival boundary; never an official PSA boundary."""

    latitude: float = 1.264
    longitude: float = 103.840
    radius_km: float = 5.0
    label: str = "exploratory_singapore_waypoint_not_official"

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("boundary latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("boundary longitude must be between -180 and 180")
        if self.radius_km <= 0:
            raise ValueError("boundary radius_km must be positive")


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """Replay assumptions and quality thresholds.

    ``assumed_timezone`` applies only because the primary timestamp is naive.
    UTC is an unconfirmed assumption inferred from the separate Rounded_time
    field in the assessed dataset.
    """

    assumed_timezone: str = "UTC"
    timezone_assumption_confirmed: bool = False
    stale_after: timedelta = timedelta(minutes=60)
    long_gap_after: timedelta = timedelta(hours=6)
    implausible_speed_knots: float = 50.0
    minimum_track_observations: int = 10
    minimum_pre_arrival_observations: int = 3
    minimum_eta_speed_knots: float = 0.5
    sufficient_arrival_events: int = 30
    boundary: ArrivalBoundary = ArrivalBoundary()
    excluded_quality_flags: frozenset[QualityFlag] = frozenset()
    temp_directory: Path | None = None

    def __post_init__(self) -> None:
        if self.timezone_assumption_confirmed and self.assumed_timezone == "UTC":
            # Confirmation is metadata supplied by a caller; no validation of
            # the claim is possible here, so deliberately do not infer it.
            pass
        if self.stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        if self.long_gap_after < self.stale_after:
            raise ValueError("long_gap_after must be >= stale_after")
        if self.minimum_track_observations < 1:
            raise ValueError("minimum_track_observations must be positive")

    @property
    def timezone(self) -> tzinfo:
        return UTC if self.assumed_timezone == "UTC" else ZoneInfo(self.assumed_timezone)


@dataclass(frozen=True, slots=True)
class VesselObservation:
    vessel_id: str
    observed_at: datetime
    source_row_number: int
    latitude: float
    longitude: float
    speed_over_ground_knots: float | None
    course_over_ground_degrees: float | None
    true_heading_degrees: float | None
    rate_of_turn: float | None
    navigation_status: int | None
    vessel_type: int | None
    ais_reported_eta: datetime | None
    quality_flags: tuple[QualityFlag, ...]


@dataclass(frozen=True, slots=True)
class EtaRevision:
    observed_at: datetime
    estimated_arrival: datetime
    distance_to_boundary_km: float
    speed_over_ground_knots: float


@dataclass(frozen=True, slots=True)
class DerivedArrivalEvent:
    vessel_id: str
    derived_geofence_arrival: datetime
    observations_before_event: int
    available_lookback: timedelta
    usable: bool
    exclusion_reasons: tuple[str, ...]
    eta_revisions: tuple[EtaRevision, ...]


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    vessels_assessed: int
    observations_assessed: int
    vessels_crossing_boundary: int
    usable_derived_arrival_events: int
    sufficient_for_historical_experiment: bool
    event_sufficiency_threshold: int
    observations_before_event: dict[str, float]
    available_lookback_hours: dict[str, float]
    quality_flag_counts: dict[str, int]
    event_exclusion_reasons: dict[str, int]
    example_eta_revisions: tuple[DerivedArrivalEvent, ...]
    assumed_timezone: str
    timezone_assumption_confirmed: bool
    boundary: ArrivalBoundary

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        for event in value["example_eta_revisions"]:
            event["derived_geofence_arrival"] = event[
                "derived_geofence_arrival"
            ].isoformat()
            event["available_lookback"] = event["available_lookback"].total_seconds()
            for revision in event["eta_revisions"]:
                revision["observed_at"] = revision["observed_at"].isoformat()
                revision["estimated_arrival"] = revision[
                    "estimated_arrival"
                ].isoformat()
        return value


_FRACTION_AFTER_MICROSECONDS = re.compile(r"(\.\d{6})\d+")
_AIS_SPEED_UNAVAILABLE = 102.3
_AIS_COURSE_UNAVAILABLE = 360.0
_AIS_HEADING_UNAVAILABLE = 511.0
_AIS_RATE_OF_TURN_UNAVAILABLE = -128.0
_AIS_NAVIGATION_STATUS_UNAVAILABLE = 15


def parse_primary_timestamp(value: str, assumed_timezone: tzinfo = UTC) -> datetime:
    """Parse the naive source timestamp and attach an explicit assumption."""

    normalized = _FRACTION_AFTER_MICROSECONDS.sub(r"\1", value.strip())
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=assumed_timezone)
    return parsed.astimezone(assumed_timezone)


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def _parse_ais_eta(row: dict[str, str], observed_at: datetime) -> datetime | None:
    """Infer the closest year using only this row and its observation time."""

    try:
        month = int(float(row["EtaMonth"]))
        day = int(float(row["EtaDay"]))
        hour = int(float(row["EtaHour"]))
        minute = int(float(row["EtaMinute"]))
    except (KeyError, TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    candidates: list[datetime] = []
    for year in (observed_at.year - 1, observed_at.year, observed_at.year + 1):
        try:
            candidates.append(datetime(year, month, day, hour, minute, tzinfo=observed_at.tzinfo))
        except ValueError:
            continue
    return min(candidates, key=lambda candidate: abs(candidate - observed_at), default=None)


def _create_replay_database(csv_path: Path, config: ReplayConfig) -> tuple[sqlite3.Connection, Path]:
    """Stream selected CSV fields into a temporary disk-backed sort index."""

    descriptor, database_name = tempfile.mkstemp(
        prefix="latch_ais_replay_",
        suffix=".sqlite3",
        dir=config.temp_directory,
    )
    os.close(descriptor)
    database_path = Path(database_name)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=FILE;
        CREATE TABLE observations (
            source_row INTEGER PRIMARY KEY,
            vessel_id TEXT NOT NULL,
            observed_sort TEXT NOT NULL,
            observed_epoch REAL NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            speed REAL,
            course REAL,
            heading REAL,
            rate_of_turn REAL,
            navigation_status INTEGER,
            vessel_type INTEGER,
            ais_eta_epoch REAL
        );
        """
    )
    batch: list[tuple[object, ...]] = []
    try:
        with csv_path.open("r", encoding="ascii", newline="") as source:
            reader = csv.DictReader(source)
            required = {"UserID", "timestamp", "Latitude", "Longitude"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                missing = sorted(required.difference(reader.fieldnames or ()))
                raise ValueError(f"CSV missing required columns: {missing}")
            for source_row, row in enumerate(reader, start=2):
                observed_at = parse_primary_timestamp(row["timestamp"], config.timezone)
                ais_eta = _parse_ais_eta(row, observed_at)
                batch.append(
                    (
                        source_row,
                        row["UserID"],
                        row["timestamp"].strip(),
                        observed_at.timestamp(),
                        float(row["Latitude"]),
                        float(row["Longitude"]),
                        _optional_float(row.get("speed")),
                        _optional_float(row.get("Cog")),
                        _optional_float(row.get("TrueHeading")),
                        _optional_float(row.get("RateOfTurn")),
                        int(float(row["NavigationalStatus"]))
                        if row.get("NavigationalStatus")
                        else None,
                        int(float(row["ShipType"])) if row.get("ShipType") else None,
                        ais_eta.timestamp() if ais_eta else None,
                    )
                )
                if len(batch) >= 10_000:
                    connection.executemany(
                        "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    batch.clear()
            if batch:
                connection.executemany(
                    "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
        connection.executescript(
            """
            CREATE INDEX observations_replay_order
                ON observations(observed_sort, source_row);
            CREATE INDEX observations_vessel
                ON observations(vessel_id);
            CREATE TEMP TABLE vessel_counts AS
                SELECT vessel_id, COUNT(*) AS observation_count
                FROM observations
                GROUP BY vessel_id;
            CREATE INDEX vessel_counts_id ON vessel_counts(vessel_id);
            """
        )
        connection.commit()
        return connection, database_path
    except BaseException:
        connection.close()
        database_path.unlink(missing_ok=True)
        raise


def iter_replay_observations(
    csv_path: str | Path, config: ReplayConfig = ReplayConfig()
) -> Iterator[VesselObservation]:
    """Yield a global stable timeline, sorted by time then source row.

    The source is streamed into a temporary SQLite database, making peak
    Python memory independent of CSV row count.  Low-quality rows are yielded
    with flags; configured exclusions are applied by evaluation, not here.
    """

    connection, database_path = _create_replay_database(Path(csv_path), config)
    prior_by_vessel: dict[str, datetime] = {}
    query = """
        SELECT o.source_row, o.vessel_id, o.observed_epoch,
               o.latitude, o.longitude, o.speed, o.course, o.heading,
               o.rate_of_turn, o.navigation_status, o.vessel_type,
               o.ais_eta_epoch, c.observation_count
        FROM observations AS o
        JOIN vessel_counts AS c USING (vessel_id)
        ORDER BY o.observed_sort, o.source_row
    """
    try:
        for row in connection.execute(query):
            (
                source_row,
                vessel_id,
                observed_epoch,
                latitude,
                longitude,
                speed,
                course,
                heading,
                rate_of_turn,
                navigation_status,
                vessel_type,
                ais_eta_epoch,
                observation_count,
            ) = row
            observed_at = datetime.fromtimestamp(observed_epoch, config.timezone)
            flags: list[QualityFlag] = []
            if observation_count < config.minimum_track_observations:
                flags.append(QualityFlag.SPARSE_VESSEL_TRACK)
            previous = prior_by_vessel.get(vessel_id)
            if previous is not None:
                gap = observed_at - previous
                if gap > config.stale_after:
                    flags.append(QualityFlag.STALE_OBSERVATION)
                if gap > config.long_gap_after:
                    flags.append(QualityFlag.LONG_OBSERVATION_GAP)
            prior_by_vessel[vessel_id] = observed_at

            if speed == _AIS_SPEED_UNAVAILABLE:
                speed = None
            elif speed is not None and speed > config.implausible_speed_knots:
                flags.append(QualityFlag.IMPLAUSIBLE_SPEED)
            if course == _AIS_COURSE_UNAVAILABLE:
                course = None
            if heading == _AIS_HEADING_UNAVAILABLE:
                heading = None
                flags.append(QualityFlag.HEADING_UNAVAILABLE)
            if rate_of_turn == _AIS_RATE_OF_TURN_UNAVAILABLE:
                rate_of_turn = None
                flags.append(QualityFlag.RATE_OF_TURN_UNAVAILABLE)
            if navigation_status == _AIS_NAVIGATION_STATUS_UNAVAILABLE:
                navigation_status = None
            ais_eta = (
                datetime.fromtimestamp(ais_eta_epoch, config.timezone)
                if ais_eta_epoch is not None
                else None
            )
            yield VesselObservation(
                vessel_id=vessel_id,
                observed_at=observed_at,
                source_row_number=source_row,
                latitude=latitude,
                longitude=longitude,
                speed_over_ground_knots=speed,
                course_over_ground_degrees=course,
                true_heading_degrees=heading,
                rate_of_turn=rate_of_turn,
                navigation_status=navigation_status,
                vessel_type=vessel_type,
                ais_reported_eta=ais_eta,
                quality_flags=tuple(flags),
            )
    finally:
        connection.close()
        database_path.unlink(missing_ok=True)


def haversine_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    earth_radius_km = 6_371.0088
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_km * math.asin(math.sqrt(value))


def causal_eta(observation: VesselObservation, boundary: ArrivalBoundary, minimum_speed_knots: float = 0.5) -> EtaRevision | None:
    """Straight-line boundary ETA from only the current observation."""

    speed = observation.speed_over_ground_knots
    if speed is None or speed < minimum_speed_knots:
        return None
    distance_to_center = haversine_km(
        observation.latitude,
        observation.longitude,
        boundary.latitude,
        boundary.longitude,
    )
    distance_to_boundary = max(0.0, distance_to_center - boundary.radius_km)
    hours = distance_to_boundary / (speed * 1.852)
    return EtaRevision(
        observed_at=observation.observed_at,
        estimated_arrival=observation.observed_at + timedelta(hours=hours),
        distance_to_boundary_km=distance_to_boundary,
        speed_over_ground_knots=speed,
    )


@dataclass(slots=True)
class _TrackState:
    first_observation: datetime
    observations_seen: int = 0
    previous_distance_km: float | None = None
    arrived: bool = False
    revisions: deque[EtaRevision] | None = None


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"minimum": 0.0, "median": 0.0, "mean": 0.0, "maximum": 0.0}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    return {
        "minimum": min(ordered),
        "median": median,
        "mean": sum(ordered) / len(ordered),
        "maximum": max(ordered),
    }


def assess_arrival_feasibility(
    csv_path: str | Path,
    config: ReplayConfig = ReplayConfig(),
    *,
    example_vessels: int = 5,
    revisions_per_example: int = 5,
) -> FeasibilityResult:
    """Assess first outside-to-inside crossing per vessel.

    A crossing is named ``derived_geofence_arrival`` and never
    ``actual_arrival``.  ETA revisions are calculated as each observation is
    emitted, before any later observation is visible.
    """

    states: dict[str, _TrackState] = {}
    events: list[DerivedArrivalEvent] = []
    quality_counts: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    observations = 0
    for observation in iter_replay_observations(csv_path, config):
        observations += 1
        quality_counts.update(flag.value for flag in observation.quality_flags)
        state = states.get(observation.vessel_id)
        if state is None:
            state = _TrackState(
                first_observation=observation.observed_at,
                revisions=deque(maxlen=revisions_per_example),
            )
            states[observation.vessel_id] = state
        distance = haversine_km(
            observation.latitude,
            observation.longitude,
            config.boundary.latitude,
            config.boundary.longitude,
        )
        revision = causal_eta(observation, config.boundary, config.minimum_eta_speed_knots)
        if revision is not None and distance > config.boundary.radius_km:
            assert state.revisions is not None
            state.revisions.append(revision)

        crossing = (
            not state.arrived
            and state.previous_distance_km is not None
            and state.previous_distance_km > config.boundary.radius_km
            and distance <= config.boundary.radius_km
        )
        if crossing:
            reasons: list[str] = []
            if state.observations_seen < config.minimum_pre_arrival_observations:
                reasons.append("insufficient_pre_arrival_observations")
            reasons.extend(
                flag.value
                for flag in observation.quality_flags
                if flag in config.excluded_quality_flags
            )
            exclusions.update(reasons)
            assert state.revisions is not None
            events.append(
                DerivedArrivalEvent(
                    vessel_id=observation.vessel_id,
                    derived_geofence_arrival=observation.observed_at,
                    observations_before_event=state.observations_seen,
                    available_lookback=observation.observed_at - state.first_observation,
                    usable=not reasons,
                    exclusion_reasons=tuple(reasons),
                    eta_revisions=tuple(state.revisions),
                )
            )
            state.arrived = True
        state.observations_seen += 1
        state.previous_distance_km = distance

    usable = [event for event in events if event.usable]
    examples = tuple(
        sorted(usable, key=lambda event: (event.derived_geofence_arrival, event.vessel_id))[
            :example_vessels
        ]
    )
    observation_counts = [float(event.observations_before_event) for event in usable]
    lookbacks = [event.available_lookback.total_seconds() / 3_600 for event in usable]
    return FeasibilityResult(
        vessels_assessed=len(states),
        observations_assessed=observations,
        vessels_crossing_boundary=len(events),
        usable_derived_arrival_events=len(usable),
        sufficient_for_historical_experiment=len(usable) >= config.sufficient_arrival_events,
        event_sufficiency_threshold=config.sufficient_arrival_events,
        observations_before_event=_summary(observation_counts),
        available_lookback_hours=_summary(lookbacks),
        quality_flag_counts=dict(sorted(quality_counts.items())),
        event_exclusion_reasons=dict(sorted(exclusions.items())),
        example_eta_revisions=examples,
        assumed_timezone=config.assumed_timezone,
        timezone_assumption_confirmed=config.timezone_assumption_confirmed,
        boundary=config.boundary,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_boundary = ArrivalBoundary()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--latitude", type=float, default=default_boundary.latitude)
    parser.add_argument("--longitude", type=float, default=default_boundary.longitude)
    parser.add_argument("--radius-km", type=float, default=default_boundary.radius_km)
    parser.add_argument("--sufficient-events", type=int, default=30)
    return parser


def main() -> None:
    args = _parser().parse_args()
    boundary = ArrivalBoundary(args.latitude, args.longitude, args.radius_km)
    config = ReplayConfig(
        assumed_timezone=args.timezone,
        boundary=boundary,
        sufficient_arrival_events=args.sufficient_events,
        excluded_quality_flags=frozenset(
            {
                QualityFlag.SPARSE_VESSEL_TRACK,
                QualityFlag.LONG_OBSERVATION_GAP,
                QualityFlag.IMPLAUSIBLE_SPEED,
            }
        ),
    )
    print(json.dumps(assess_arrival_feasibility(args.csv_path, config).as_dict(), indent=2))


if __name__ == "__main__":
    main()

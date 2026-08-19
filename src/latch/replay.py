"""Disk-backed AIS replay and exploratory arrival-event feasibility.

The primary CSV timestamp has no documented timezone.  UTC is the current,
explicitly unconfirmed default assumption.  The arrival boundary is likewise
an exploratory project input, not an official PSA terminal or berth boundary.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, replace
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
    SPEED_UNAVAILABLE = "speed_unavailable"
    COURSE_UNAVAILABLE = "course_unavailable"
    HEADING_UNAVAILABLE = "heading_unavailable"
    RATE_OF_TURN_UNAVAILABLE = "rate_of_turn_unavailable"


class DataQuality(StrEnum):
    GOOD = "good"
    DEGRADED = "degraded"
    EXCLUDED = "excluded"


class PredictionStatus(StrEnum):
    AVAILABLE = "available"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True, slots=True)
class ArrivalBoundary:
    """Exploratory circular arrival boundary; never an official PSA boundary."""

    latitude: float = 1.264
    longitude: float = 103.840
    radius_km: float = 5.0
    label: str = "exploratory_singapore_waypoint_not_official"
    version: str = "exploratory-circle-v1"

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("boundary latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("boundary longitude must be between -180 and 180")
        if self.radius_km <= 0:
            raise ValueError("boundary radius_km must be positive")
        if not self.version.strip():
            raise ValueError("boundary version must not be empty")


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
    boundary_reset_distance_km: float = 2.0
    reset_confirmation_observations: int = 2
    moving_away_tolerance_km: float = 0.05
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
        if self.minimum_pre_arrival_observations < 1:
            raise ValueError("minimum_pre_arrival_observations must be positive")
        if self.minimum_eta_speed_knots <= 0:
            raise ValueError("minimum_eta_speed_knots must be positive")
        if self.boundary_reset_distance_km <= 0:
            raise ValueError("boundary_reset_distance_km must be positive")
        if self.reset_confirmation_observations < 1:
            raise ValueError("reset_confirmation_observations must be positive")
        if self.moving_away_tolerance_km < 0:
            raise ValueError("moving_away_tolerance_km must not be negative")

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
class CausalArrivalUpdate:
    """Causal values from a retrospectively segmented historical call.

    Historical call membership is segmented retrospectively, but every value
    that can influence a prediction is causal at ``observed_at``.
    """

    call_id: str
    vessel_id: str
    observed_at: datetime
    prediction_status: PredictionStatus
    reference_arrival: datetime | None
    predicted_arrival: datetime | None
    data_quality: DataQuality
    quality_reason_codes: tuple[str, ...]
    source_type: str
    boundary_version: str
    source_observation: VesselObservation


@dataclass(frozen=True, slots=True)
class DerivedArrivalEvent:
    vessel_id: str
    call_id: str
    derived_geofence_arrival: datetime
    first_eligible_pre_event_observation: VesselObservation | None
    eligible_pre_event_observations: int
    pre_event_lookback: timedelta
    benchmark_eligible: bool
    exclusion_reasons: tuple[str, ...]
    quality_reason_codes: tuple[str, ...]
    data_quality: DataQuality
    boundary_version: str
    crossing_source_row_number: int
    arrival_updates: tuple[CausalArrivalUpdate, ...]
    eta_revisions: tuple[EtaRevision, ...]


@dataclass(frozen=True, slots=True)
class ValidationSample:
    category: str
    vessel_id: str
    call_id: str | None
    observed_at: datetime
    note: str


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    vessels_assessed: int
    observations_assessed: int
    vessels_crossing_boundary: int
    raw_candidate_crossings: int
    crossings_suppressed_before_reset: int
    accepted_calls: int
    benchmark_eligible_calls: int
    excluded_calls: int
    sufficient_for_historical_experiment: bool
    event_sufficiency_threshold: int
    eligible_pre_event_observations: dict[str, float]
    pre_event_lookback_hours: dict[str, float]
    quality_flag_counts: dict[str, int]
    event_exclusion_reasons: dict[str, int]
    events_by_day: dict[str, int]
    call_data_quality_distribution: dict[str, int]
    all_accepted_arrival_update_status_distribution: dict[str, int]
    benchmark_eligible_arrival_update_status_distribution: dict[str, int]
    example_eta_revisions: tuple[DerivedArrivalEvent, ...]
    validation_samples: tuple[ValidationSample, ...]
    assumed_timezone: str
    timezone_assumption_confirmed: bool
    boundary: ArrivalBoundary
    boundary_reset_distance_km: float
    reset_confirmation_observations: int

    def as_dict(self) -> dict[str, object]:
        value = _json_value(asdict(self))
        assert isinstance(value, dict)
        return value


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
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


def calculate_data_age_minutes(
    observed_at: datetime,
    assessed_at: datetime,
) -> float:
    """Return downstream data age at assessment time in elapsed minutes."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ValueError("assessed_at must be timezone-aware")
    if assessed_at < observed_at:
        raise ValueError("assessed_at must not be before observed_at")
    return (assessed_at - observed_at).total_seconds() / 60


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _required_float(value: str | None, field: str, source_row: int) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"CSV row {source_row} has no finite {field}")
    return parsed


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
                vessel_id = row["UserID"].strip()
                if not vessel_id:
                    raise ValueError(f"CSV row {source_row} has no vessel ID")
                observed_at = parse_primary_timestamp(row["timestamp"], config.timezone)
                latitude = _required_float(row["Latitude"], "latitude", source_row)
                longitude = _required_float(row["Longitude"], "longitude", source_row)
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise ValueError(
                        f"CSV row {source_row} has invalid latitude/longitude"
                    )
                ais_eta = _parse_ais_eta(row, observed_at)
                batch.append(
                    (
                        source_row,
                        vessel_id,
                        row["timestamp"].strip(),
                        observed_at.timestamp(),
                        latitude,
                        longitude,
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
               o.ais_eta_epoch
        FROM observations AS o
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
            ) = row
            observed_at = datetime.fromtimestamp(observed_epoch, config.timezone)
            flags: list[QualityFlag] = []
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
                flags.append(QualityFlag.SPEED_UNAVAILABLE)
            elif speed is not None and speed > config.implausible_speed_knots:
                flags.append(QualityFlag.IMPLAUSIBLE_SPEED)
            elif speed is None:
                flags.append(QualityFlag.SPEED_UNAVAILABLE)
            if course == _AIS_COURSE_UNAVAILABLE:
                course = None
                flags.append(QualityFlag.COURSE_UNAVAILABLE)
            elif course is None:
                flags.append(QualityFlag.COURSE_UNAVAILABLE)
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


def causal_eta(
    observation: VesselObservation,
    boundary: ArrivalBoundary,
    minimum_speed_knots: float = 0.5,
    maximum_speed_knots: float | None = None,
) -> EtaRevision | None:
    """Straight-line boundary ETA from only the current observation."""

    speed = observation.speed_over_ground_knots
    if (
        speed is None
        or speed < minimum_speed_knots
        or (maximum_speed_knots is not None and speed > maximum_speed_knots)
    ):
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
    previous_distance_km: float | None = None
    observations_seen: int = 0
    armed: bool = False
    episode_observations: list[tuple[VesselObservation, float]] | None = None
    reset_confirmation_observations: list[tuple[VesselObservation, float]] | None = None


def _percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "minimum": 0.0,
            "p05": 0.0,
            "p25": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "p95": 0.0,
            "mean": 0.0,
            "maximum": 0.0,
        }
    ordered = sorted(values)
    return {
        "minimum": min(ordered),
        "p05": _percentile(ordered, 0.05),
        "p25": _percentile(ordered, 0.25),
        "median": _percentile(ordered, 0.5),
        "p75": _percentile(ordered, 0.75),
        "p95": _percentile(ordered, 0.95),
        "mean": sum(ordered) / len(ordered),
        "maximum": max(ordered),
    }


def _call_id(observation: VesselObservation, boundary: ArrivalBoundary) -> str:
    identity = "|".join(
        (
            boundary.version,
            observation.vessel_id,
            observation.observed_at.isoformat(),
            str(observation.source_row_number),
        )
    )
    return f"call_{hashlib.sha256(identity.encode()).hexdigest()[:20]}"


def _observation_reason_codes(
    observation: VesselObservation,
    distance_km: float,
    previous_distance_km: float | None,
    config: ReplayConfig,
) -> tuple[str, ...]:
    reasons = {flag.value for flag in observation.quality_flags}
    speed = observation.speed_over_ground_knots
    if speed is None:
        reasons.add("speed_unavailable")
    elif speed < config.minimum_eta_speed_knots:
        reasons.add("zero_or_near_zero_speed")
    elif speed > config.implausible_speed_knots:
        reasons.add("implausible_speed")
    if (
        previous_distance_km is not None
        and distance_km > previous_distance_km + config.moving_away_tolerance_km
    ):
        reasons.add("moving_away_from_boundary")
    return tuple(sorted(reasons))


_PREDICTION_BLOCKING_REASONS = frozenset(
    {
        "speed_unavailable",
        "zero_or_near_zero_speed",
        "implausible_speed",
        "stale_observation",
        "long_observation_gap",
        "moving_away_from_boundary",
    }
)


def _event_from_crossing(
    state: _TrackState,
    crossing: VesselObservation,
    config: ReplayConfig,
    revisions_per_example: int,
) -> DerivedArrivalEvent:
    call_id = _call_id(crossing, config.boundary)
    available: list[tuple[VesselObservation, EtaRevision]] = []
    updates: list[CausalArrivalUpdate] = []
    observations = state.episode_observations or []
    episode_reasons: set[str] = set()
    previous_episode_distance: float | None = None
    reference: datetime | None = None
    for observation, distance in observations:
        reason_codes = _observation_reason_codes(
            observation, distance, previous_episode_distance, config
        )
        episode_reasons.update(reason_codes)
        revision = causal_eta(
            observation,
            config.boundary,
            config.minimum_eta_speed_knots,
            config.implausible_speed_knots,
        )
        is_available = (
            revision is not None
            and not _PREDICTION_BLOCKING_REASONS.intersection(reason_codes)
        )
        if is_available:
            assert revision is not None
            available.append((observation, revision))
            if reference is None:
                reference = revision.estimated_arrival
        updates.append(
            CausalArrivalUpdate(
                call_id=call_id,
                vessel_id=crossing.vessel_id,
                observed_at=observation.observed_at,
                prediction_status=(
                    PredictionStatus.AVAILABLE
                    if is_available
                    else PredictionStatus.INELIGIBLE
                ),
                reference_arrival=reference,
                predicted_arrival=(revision.estimated_arrival if is_available else None),
                data_quality=(
                    DataQuality.DEGRADED if reason_codes else DataQuality.GOOD
                ),
                quality_reason_codes=reason_codes,
                source_type="real_ais_observation",
                boundary_version=config.boundary.version,
                source_observation=observation,
            )
        )
        previous_episode_distance = distance

    exclusion_reasons: set[str] = set()
    if len(available) < config.minimum_pre_arrival_observations:
        exclusion_reasons.add("insufficient_eligible_pre_arrival_observations")
    exclusion_reasons.update(
        flag.value
        for flag in crossing.quality_flags
        if flag in config.excluded_quality_flags
    )
    episode_reasons.update(flag.value for flag in crossing.quality_flags)
    quality = (
        DataQuality.EXCLUDED
        if exclusion_reasons
        else DataQuality.DEGRADED
        if episode_reasons
        else DataQuality.GOOD
    )
    first_observation = available[0][0] if available else None
    lookback = (
        crossing.observed_at - first_observation.observed_at
        if first_observation is not None
        else timedelta(0)
    )
    revisions = tuple(item[1] for item in available[-revisions_per_example:])
    return DerivedArrivalEvent(
        vessel_id=crossing.vessel_id,
        call_id=call_id,
        derived_geofence_arrival=crossing.observed_at,
        first_eligible_pre_event_observation=first_observation,
        eligible_pre_event_observations=len(available),
        pre_event_lookback=lookback,
        benchmark_eligible=not exclusion_reasons,
        exclusion_reasons=tuple(sorted(exclusion_reasons)),
        quality_reason_codes=tuple(sorted(episode_reasons)),
        data_quality=quality,
        boundary_version=config.boundary.version,
        crossing_source_row_number=crossing.source_row_number,
        arrival_updates=tuple(updates),
        eta_revisions=revisions,
    )


@dataclass(frozen=True, slots=True)
class _Analysis:
    result: FeasibilityResult
    calls: tuple[DerivedArrivalEvent, ...]


def _sample_for_event(category: str, event: DerivedArrivalEvent, note: str) -> ValidationSample:
    return ValidationSample(
        category=category,
        vessel_id=event.vessel_id,
        call_id=event.call_id,
        observed_at=event.derived_geofence_arrival,
        note=note,
    )


def _analyse_arrivals(
    csv_path: str | Path,
    config: ReplayConfig,
    *,
    example_vessels: int,
    revisions_per_example: int,
) -> _Analysis:
    """Build deterministic approach episodes, calls, and causal updates."""

    states: dict[str, _TrackState] = {}
    events: list[DerivedArrivalEvent] = []
    quality_counts: Counter[str] = Counter()
    exclusions: Counter[str] = Counter()
    suppression_samples: list[ValidationSample] = []
    observations_assessed = 0
    raw_crossings = 0
    suppressed_crossings = 0
    reset_radius = config.boundary.radius_km + config.boundary_reset_distance_km

    for observation in iter_replay_observations(csv_path, config):
        observations_assessed += 1
        quality_counts.update(flag.value for flag in observation.quality_flags)
        distance = haversine_km(
            observation.latitude,
            observation.longitude,
            config.boundary.latitude,
            config.boundary.longitude,
        )
        state = states.setdefault(observation.vessel_id, _TrackState())
        state.observations_seen += 1
        previous_distance = state.previous_distance_km

        if previous_distance is None:
            if distance > config.boundary.radius_km:
                state.armed = True
                state.episode_observations = [(observation, distance)]
            state.previous_distance_km = distance
            continue

        long_gap = QualityFlag.LONG_OBSERVATION_GAP in observation.quality_flags
        if state.armed and long_gap:
            # A discontinuity invalidates the earlier approach segment. Keep
            # the gap-bearing outside observation itself for audit, but it is
            # ineligible to predict and cannot become the new reference.
            state.episode_observations = (
                [(observation, distance)]
                if distance > config.boundary.radius_km
                else []
            )

        crossing = (
            previous_distance > config.boundary.radius_km
            and distance <= config.boundary.radius_km
        )
        if crossing:
            raw_crossings += 1
            if state.armed:
                event = _event_from_crossing(
                    state, observation, config, revisions_per_example
                )
                events.append(event)
                state.armed = False
                state.episode_observations = None
                state.reset_confirmation_observations = []
            else:
                suppressed_crossings += 1
                state.reset_confirmation_observations = []
                if len(suppression_samples) < 3:
                    suppression_samples.append(
                        ValidationSample(
                            category="suspected_duplicate_recrossing",
                            vessel_id=observation.vessel_id,
                            call_id=None,
                            observed_at=observation.observed_at,
                            note=(
                                "outside-to-inside recrossing ignored because the vessel "
                                "had not completed the configured reset confirmation "
                                f"beyond {reset_radius:.2f} km from the centre"
                            ),
                        )
                    )
        elif distance > config.boundary.radius_km:
            if not state.armed:
                if distance >= reset_radius:
                    confirmations = state.reset_confirmation_observations
                    if confirmations is None or long_gap:
                        confirmations = []
                    confirmations.append((observation, distance))
                    state.reset_confirmation_observations = confirmations
                    if (
                        len(confirmations)
                        >= config.reset_confirmation_observations
                    ):
                        state.armed = True
                        state.episode_observations = list(confirmations)
                        state.reset_confirmation_observations = []
                else:
                    state.reset_confirmation_observations = []
            if state.armed:
                assert state.episode_observations is not None
                if (
                    not state.episode_observations
                    or state.episode_observations[-1][0] != observation
                ):
                    state.episode_observations.append((observation, distance))
        state.previous_distance_km = distance

    sparse_reason = QualityFlag.SPARSE_VESSEL_TRACK.value
    for state in states.values():
        if state.observations_seen < config.minimum_track_observations:
            quality_counts[sparse_reason] += state.observations_seen
    for index, event in enumerate(events):
        if (
            states[event.vessel_id].observations_seen
            >= config.minimum_track_observations
        ):
            continue
        event_reasons = set(event.quality_reason_codes)
        event_reasons.add(sparse_reason)
        exclusion_reasons = set(event.exclusion_reasons)
        if QualityFlag.SPARSE_VESSEL_TRACK in config.excluded_quality_flags:
            exclusion_reasons.add(sparse_reason)
        events[index] = replace(
            event,
            benchmark_eligible=not exclusion_reasons,
            exclusion_reasons=tuple(sorted(exclusion_reasons)),
            quality_reason_codes=tuple(sorted(event_reasons)),
            data_quality=(
                DataQuality.EXCLUDED
                if exclusion_reasons
                else DataQuality.DEGRADED
            ),
        )

    exclusions.update(
        reason for event in events for reason in event.exclusion_reasons
    )

    events.sort(
        key=lambda event: (
            event.derived_geofence_arrival,
            event.crossing_source_row_number,
            event.call_id,
        )
    )
    benchmark_eligible = [event for event in events if event.benchmark_eligible]
    event_days = Counter(event.derived_geofence_arrival.date().isoformat() for event in events)
    data_quality = Counter(event.data_quality.value for event in events)
    all_accepted_update_statuses = Counter(
        update.prediction_status.value
        for event in events
        for update in event.arrival_updates
    )
    benchmark_eligible_update_statuses = Counter(
        update.prediction_status.value
        for event in benchmark_eligible
        for update in event.arrival_updates
    )
    observation_counts = [
        float(event.eligible_pre_event_observations) for event in benchmark_eligible
    ]
    lookbacks = [
        event.pre_event_lookback.total_seconds() / 3_600
        for event in benchmark_eligible
    ]

    samples: list[ValidationSample] = list(suppression_samples)
    categories: dict[str, DerivedArrivalEvent | None] = {
        "normal_approach": next(
            (
                event
                for event in benchmark_eligible
                if event.data_quality is DataQuality.GOOD
            ),
            None,
        ),
        "sparse_track": next(
            (
                event
                for event in events
                if QualityFlag.SPARSE_VESSEL_TRACK.value in event.quality_reason_codes
            ),
            None,
        ),
        "stale_track": next(
            (
                event
                for event in events
                if QualityFlag.STALE_OBSERVATION.value in event.quality_reason_codes
            ),
            None,
        ),
        "moving_away": next(
            (
                event
                for event in events
                if "moving_away_from_boundary" in event.quality_reason_codes
            ),
            None,
        ),
    }
    notes = {
        "normal_approach": (
            "benchmark-eligible approach with no detected quality degradation"
        ),
        "sparse_track": "call retains the sparse-vessel-track provenance flag",
        "stale_track": "episode contains an observation following the stale threshold",
        "moving_away": "moving-away observation was retained but not used for prediction",
    }
    for category, event in categories.items():
        if event is not None:
            samples.append(_sample_for_event(category, event, notes[category]))
    calls_per_vessel = Counter(event.vessel_id for event in events)
    repeated = next(
        (event for event in events if calls_per_vessel[event.vessel_id] > 1), None
    )
    if repeated is not None:
        samples.append(
            _sample_for_event(
                "repeated_visit",
                repeated,
                f"vessel has {calls_per_vessel[repeated.vessel_id]} separately reset calls",
            )
        )

    examples = tuple(benchmark_eligible[:example_vessels])
    result = FeasibilityResult(
        vessels_assessed=len(states),
        observations_assessed=observations_assessed,
        vessels_crossing_boundary=len({event.vessel_id for event in events}),
        raw_candidate_crossings=raw_crossings,
        crossings_suppressed_before_reset=suppressed_crossings,
        accepted_calls=len(events),
        benchmark_eligible_calls=len(benchmark_eligible),
        excluded_calls=len(events) - len(benchmark_eligible),
        sufficient_for_historical_experiment=(
            len(benchmark_eligible) >= config.sufficient_arrival_events
        ),
        event_sufficiency_threshold=config.sufficient_arrival_events,
        eligible_pre_event_observations=_summary(observation_counts),
        pre_event_lookback_hours=_summary(lookbacks),
        quality_flag_counts=dict(sorted(quality_counts.items())),
        event_exclusion_reasons=dict(sorted(exclusions.items())),
        events_by_day=dict(sorted(event_days.items())),
        call_data_quality_distribution=dict(sorted(data_quality.items())),
        all_accepted_arrival_update_status_distribution=dict(
            sorted(all_accepted_update_statuses.items())
        ),
        benchmark_eligible_arrival_update_status_distribution=dict(
            sorted(benchmark_eligible_update_statuses.items())
        ),
        example_eta_revisions=examples,
        validation_samples=tuple(samples),
        assumed_timezone=config.assumed_timezone,
        timezone_assumption_confirmed=config.timezone_assumption_confirmed,
        boundary=config.boundary,
        boundary_reset_distance_km=config.boundary_reset_distance_km,
        reset_confirmation_observations=config.reset_confirmation_observations,
    )
    return _Analysis(result=result, calls=tuple(events))


def assess_arrival_feasibility(
    csv_path: str | Path,
    config: ReplayConfig = ReplayConfig(),
    *,
    example_vessels: int = 5,
    revisions_per_example: int = 5,
) -> FeasibilityResult:
    """Report validated calls around the exploratory, non-official boundary."""

    return _analyse_arrivals(
        csv_path,
        config,
        example_vessels=example_vessels,
        revisions_per_example=revisions_per_example,
    ).result


def derive_arrival_calls(
    csv_path: str | Path,
    config: ReplayConfig = ReplayConfig(),
) -> tuple[DerivedArrivalEvent, ...]:
    """Return accepted calls, including excluded calls and their reasons."""

    return _analyse_arrivals(
        csv_path, config, example_vessels=0, revisions_per_example=5
    ).calls


def iter_retrospectively_segmented_arrival_updates(
    csv_path: str | Path,
    config: ReplayConfig = ReplayConfig(),
) -> Iterator[CausalArrivalUpdate]:
    """Yield updates from every accepted retrospectively segmented call.

    The values in each update are causal, but membership in this historical
    stream is known only after a later boundary crossing defines the call. The
    projection deliberately contains no crossing or benchmark outcome.
    """

    calls = derive_arrival_calls(csv_path, config)
    updates = [update for call in calls for update in call.arrival_updates]
    yield from sorted(
        updates,
        key=lambda update: (
            update.observed_at,
            update.source_observation.source_row_number,
            update.call_id,
        ),
    )


def iter_eligible_benchmark_updates(
    csv_path: str | Path,
    config: ReplayConfig = ReplayConfig(),
) -> Iterator[CausalArrivalUpdate]:
    """Yield updates only from retrospectively benchmark-eligible calls."""

    calls = derive_arrival_calls(csv_path, config)
    updates = [
        update
        for call in calls
        if call.benchmark_eligible
        for update in call.arrival_updates
    ]
    yield from sorted(
        updates,
        key=lambda update: (
            update.observed_at,
            update.source_observation.source_row_number,
            update.call_id,
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_boundary = ArrivalBoundary()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--latitude", type=float, default=default_boundary.latitude)
    parser.add_argument("--longitude", type=float, default=default_boundary.longitude)
    parser.add_argument("--radius-km", type=float, default=default_boundary.radius_km)
    parser.add_argument("--boundary-version", default=default_boundary.version)
    parser.add_argument("--reset-distance-km", type=float, default=2.0)
    parser.add_argument("--reset-confirmation-observations", type=int, default=2)
    parser.add_argument("--moving-away-tolerance-km", type=float, default=0.05)
    parser.add_argument("--sufficient-events", type=int, default=30)
    return parser


def main() -> None:
    args = _parser().parse_args()
    boundary = ArrivalBoundary(
        latitude=args.latitude,
        longitude=args.longitude,
        radius_km=args.radius_km,
        version=args.boundary_version,
    )
    config = ReplayConfig(
        assumed_timezone=args.timezone,
        boundary=boundary,
        boundary_reset_distance_km=args.reset_distance_km,
        reset_confirmation_observations=args.reset_confirmation_observations,
        moving_away_tolerance_km=args.moving_away_tolerance_km,
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

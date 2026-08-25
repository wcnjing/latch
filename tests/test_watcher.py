"""A-to-B bridge tests. The seam that had never existed in one tree."""

import inspect
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from latch.connections import ConnectionParams, connection_for
from latch.events import ReasonCode, RiskSeverity, WatcherConfidence
from latch.models import TerminalResolution
from latch.replay import DataQuality, DerivedArrivalEvent, PredictionStatus
from latch.synthetic import (
    ImpactBand,
    ProcessScenario,
    TransferMode,
    generate_synthetic_benchmark,
)
from latch.watcher import (
    AssessmentStatus,
    ArrivalSignal,
    WatcherConfig,
    assess_connection,
    assess_derived_reference_delay,
    compute_slack,
    events_from_signals,
    latest_available_predictions,
    risk_event_from_assessment,
    to_risk_event,
)
from scripts.make_synthetic_benchmark import tiny_fixture_config, tiny_fixture_updates

T0 = datetime(2023, 10, 1, tzinfo=UTC)


@dataclass
class FakeSignal:
    """Stands in for A's CausalArrivalUpdate. Only the protocol fields matter."""

    call_id: str = "call_abc123def456"
    vessel_id: str = "v1"
    observed_at: datetime = T0
    predicted_arrival: datetime | None = T0 + timedelta(hours=2)
    reference_arrival: datetime | None = T0 + timedelta(hours=2)
    data_quality: str = "good"
    quality_reason_codes: tuple[str, ...] = ()


def conn(call_id: str = "call_abc123def456", **kw):
    return connection_for(call_id, "v1", T0 + timedelta(hours=2), ConnectionParams(**kw))


def test_a_signal_satisfies_the_structural_protocol():
    """A can rename or extend its class; only these fields are load-bearing."""
    assert isinstance(FakeSignal(), ArrivalSignal)


def test_no_prediction_yields_no_event():
    """An ineligible observation is not an arrival at an unknown time — it is
    no estimate at all. Substituting one would invent what A refused to guess."""
    signal = FakeSignal(predicted_arrival=None)
    assert compute_slack(signal, conn()) is None
    assert to_risk_event(signal, conn()) is None


def test_slack_shrinks_as_the_vessel_slips():
    """The core behaviour. The cutoff is anchored to the *original* expected
    arrival, so a later prediction eats into slack rather than moving the window."""
    connection = conn()
    early = to_risk_event(FakeSignal(), connection)
    late = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=9)), connection
    )

    assert late.current_plan_slack_hours < early.current_plan_slack_hours
    assert late.no_itt_slack_hours < early.no_itt_slack_hours


def test_a_slipping_vessel_eventually_becomes_at_risk():
    # Window pinned wide so the run starts SAFE regardless of which window the
    # hash would have drawn — the progression is what is under test, not the
    # synthetic draw.
    connection = conn(min_connection_window_h=32.0, max_connection_window_h=34.0)

    # Slip fractions of the connection's own window rather than fixed hours,
    # so the progression still spans SAFE to AT_RISK if the params change.
    window_h = (connection.outbound_cutoff - T0).total_seconds() / 3600.0
    slips = [window_h * f for f in (0.05, 0.35, 0.65, 0.85, 1.05)]
    states = [
        to_risk_event(
            FakeSignal(predicted_arrival=T0 + timedelta(hours=h)), connection
        ).state
        for h in slips
    ]
    assert states[0] is RiskSeverity.SAFE
    assert RiskSeverity.AT_RISK in states
    # severity is monotone: it never recovers while the vessel keeps slipping
    order = [RiskSeverity.SAFE, RiskSeverity.WATCH, RiskSeverity.AT_RISK]
    assert [order.index(s) for s in states] == sorted(order.index(s) for s in states)


def first_matching(requires_transfer: bool):
    """Find a call id whose synthetic connection has the shape we need.

    Deterministic search rather than a hardcoded id, so the test keeps working
    if the generator changes — and skips nothing.
    """
    for i in range(200):
        candidate = connection_for(f"call_probe_{i}", "v1", T0 + timedelta(hours=2))
        if candidate.requires_transfer is requires_transfer:
            return candidate
    raise AssertionError(f"no connection found with requires_transfer={requires_transfer}")


def test_transfer_time_is_the_gap_between_the_two_slack_figures():
    """This is the signal the whole ladder turns on, so it has to be exact."""
    transferring = first_matching(requires_transfer=True)

    event = to_risk_event(FakeSignal(call_id=transferring.call_id), transferring)
    gap = event.no_itt_slack_hours - event.current_plan_slack_hours
    assert gap == pytest.approx(transferring.params.planned_transfer_h)
    assert event.itt_cost_hours == pytest.approx(gap)


def test_same_terminal_connection_has_no_transfer_cost():
    same = first_matching(requires_transfer=False)
    event = to_risk_event(FakeSignal(call_id=same.call_id), same)
    assert event.no_itt_slack_hours == pytest.approx(event.current_plan_slack_hours)
    assert not event.avoidable_by_terminal_prevention


def test_terminals_are_declared_simulated():
    """They came from the synthetic layer, and that lowers confidence
    downstream. Enforced by the pipeline rather than asserted on a slide."""
    event = to_risk_event(FakeSignal(), conn())
    assert event.terminal_resolution is TerminalResolution.SIMULATED
    assert event.to_connection_risk().inbound.terminal_resolution is (
        TerminalResolution.SIMULATED
    )


def test_watcher_confidence_follows_a_data_quality():
    for quality, expected in (
        ("good", WatcherConfidence.HIGH),
        ("degraded", WatcherConfidence.MEDIUM),
        ("excluded", WatcherConfidence.LOW),
    ):
        event = to_risk_event(FakeSignal(data_quality=quality), conn())
        assert event.watcher_confidence is expected


def test_unknown_quality_gets_no_benefit_of_the_doubt():
    """Absent or unrecognised provenance is weaker than stated-poor provenance."""
    assert (
        to_risk_event(FakeSignal(data_quality="something_new"), conn()).watcher_confidence
        is WatcherConfidence.LOW
    )


def test_eta_slip_is_reported_only_when_it_exceeds_noise():
    connection = conn()
    steady = to_risk_event(FakeSignal(), connection)
    assert ReasonCode.INBOUND_ETA_SLIP not in steady.reason_codes

    slipped = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=5)), connection
    )
    assert ReasonCode.INBOUND_ETA_SLIP in slipped.reason_codes


def test_data_quality_codes_are_not_smuggled_in_as_causes():
    """They describe how good the observation was, not why cargo is at risk,
    and they already reach the agent through confidence. Folding them in would
    double-count uncertainty as causation."""
    event = to_risk_event(
        FakeSignal(quality_reason_codes=("stale_observation", "long_observation_gap")),
        conn(),
    )
    assert all(isinstance(c, ReasonCode) for c in event.reason_codes)
    assert "stale_observation" not in [c.value for c in event.reason_codes]


def test_one_connection_per_call_across_its_updates():
    """Regenerating per update would move the cutoff with the vessel and no
    connection would ever come under threat."""
    signals = [
        FakeSignal(
            observed_at=T0 + timedelta(hours=h),
            predicted_arrival=T0 + timedelta(hours=2 + h),
        )
        for h in range(6)
    ]
    events = list(events_from_signals(signals))
    assert len({e.ucid for e in events}) == 1
    slacks = [e.current_plan_slack_hours for e in events]
    assert slacks == sorted(slacks, reverse=True)


def test_signals_without_any_anchor_are_skipped():
    signals = [FakeSignal(predicted_arrival=None, reference_arrival=None)]
    assert list(events_from_signals(signals)) == []


def test_adapted_events_reach_the_agent_end_to_end():
    """The whole point: real-shaped arrival timing to an agent decision."""
    from latch.llm import FakeModel
    from latch.runner import AutoApprove, CustomerAccepts, handle
    from latch.trace import TraceStore

    connection = conn()
    event = to_risk_event(
        FakeSignal(predicted_arrival=T0 + timedelta(hours=20)), connection
    )
    assert event.state is RiskSeverity.AT_RISK

    client = FakeModel(
        {
            "triage": {"worth_deliberating": True, "reason": "scripted"},
            "deliberation": {
                "chosen_plan_id": "",
                "ranking": [],
                "rationale": "scripted",
            },
        }
    )
    outcome = handle(
        event,
        client=client,
        store=TraceStore(),
        approvals=AutoApprove(),
        customer=CustomerAccepts(),
    )
    assert outcome.resolution is not None
    assert outcome.trace.trigger["terminal_resolution"] == "simulated"


# --- PR #4: causal two-vessel connection assessments -----------------------


def pr4_benchmark():
    return generate_synthetic_benchmark(tiny_fixture_updates(), tiny_fixture_config())


def pr4_config(
    warning_margin: timedelta = timedelta(hours=2),
    delay_threshold: timedelta = timedelta(minutes=15),
    scenario: ProcessScenario = ProcessScenario.REFERENCE,
) -> WatcherConfig:
    return WatcherConfig(warning_margin, delay_threshold, scenario)


def connection_with(*, same_terminal: bool, box_count: bool | None = None):
    for connection in pr4_benchmark().connections:
        same = connection.origin.terminal == connection.destination.terminal
        boxes_match = box_count is None or (connection.box_count is not None) is box_count
        if same is same_terminal and boxes_match:
            return connection
    raise AssertionError("fixture has no matching PR #3 connection")


def first_update(call_id: str):
    return min(
        (update for update in tiny_fixture_updates() if update.call_id == call_id),
        key=lambda update: (
            update.observed_at,
            update.source_observation.source_row_number,
        ),
    )


def pair_for_slack(connection, current_plan_slack: timedelta):
    projection = connection.reference_projection
    inbound = first_update(connection.assignment.inbound_source_call_id)
    outbound = first_update(connection.assignment.outbound_source_call_id)
    assert inbound.predicted_arrival is not None
    outbound_prediction = (
        inbound.predicted_arrival
        + projection.cargo_ready_offset
        + projection.transfer_duration
        + current_plan_slack
        + projection.cargo_cutoff_lead
    )
    return inbound, replace(outbound, predicted_arrival=outbound_prediction)


def assessed_after(updates):
    return max(update.observed_at for update in updates) + timedelta(hours=1)


def test_watcher_config_rejects_negative_experimental_thresholds():
    with pytest.raises(ValueError, match="warning_margin"):
        WatcherConfig(timedelta(microseconds=-1), timedelta(0))
    with pytest.raises(ValueError, match="reference_delay_threshold"):
        WatcherConfig(timedelta(0), timedelta(microseconds=-1))


def test_prediction_selection_is_causal_stable_and_keeps_earlier_available():
    updates = list(tiny_fixture_updates())
    call_id = updates[0].call_id
    first, later = [update for update in updates if update.call_id == call_id]
    cutoff = later.observed_at + timedelta(minutes=1)
    ineligible_observation = replace(
        later.source_observation,
        observed_at=later.observed_at + timedelta(seconds=1),
        source_row_number=later.source_observation.source_row_number + 10_000,
    )
    ineligible = replace(
        later,
        observed_at=ineligible_observation.observed_at,
        prediction_status=PredictionStatus.INELIGIBLE,
        predicted_arrival=None,
        source_observation=ineligible_observation,
    )
    future_observation = replace(
        later.source_observation,
        observed_at=cutoff + timedelta(hours=1),
        source_row_number=later.source_observation.source_row_number + 20_000,
    )
    future = replace(
        later,
        observed_at=future_observation.observed_at,
        predicted_arrival=later.predicted_arrival + timedelta(days=30),
        source_observation=future_observation,
    )
    combined = updates + [ineligible, future]

    selected = latest_available_predictions(combined, assessed_at=cutoff)
    permuted = latest_available_predictions(reversed(combined), assessed_at=cutoff)

    assert selected == permuted
    assert selected[call_id] == later
    assert selected[call_id] != first
    assert selected[call_id] != future


@pytest.mark.parametrize("leg", ["inbound", "outbound"])
def test_future_prediction_cannot_change_earlier_connection_assessment(leg):
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=-1))
    cutoff = assessed_after(pair)
    target = pair[0] if leg == "inbound" else pair[1]
    future_observation = replace(
        target.source_observation,
        observed_at=cutoff + timedelta(hours=1),
        source_row_number=target.source_observation.source_row_number + 50_000,
    )
    future = replace(
        target,
        observed_at=future_observation.observed_at,
        predicted_arrival=target.predicted_arrival + timedelta(days=90),
        source_observation=future_observation,
    )

    before = assess_connection(
        connection, pair, assessed_at=cutoff, config=pr4_config()
    )
    after = assess_connection(
        connection, pair + (future,), assessed_at=cutoff, config=pr4_config()
    )
    assert before == after


def test_inbound_delay_reduces_both_slacks_by_exactly_the_delay():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=3))
    assessed_at = assessed_after(pair)
    initial = assess_connection(connection, pair, assessed_at=assessed_at, config=pr4_config())
    delay = timedelta(minutes=47)
    delayed_pair = (replace(pair[0], predicted_arrival=pair[0].predicted_arrival + delay), pair[1])
    delayed = assess_connection(
        connection, delayed_pair, assessed_at=assessed_at, config=pr4_config()
    )
    assert initial.slack is not None and delayed.slack is not None
    assert initial.slack.current_plan_slack - delayed.slack.current_plan_slack == delay
    assert initial.slack.no_itt_slack - delayed.slack.no_itt_slack == delay


def test_outbound_delay_improves_slack_exactly_and_can_recover_risk():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(minutes=-30))
    assessed_at = assessed_after(pair)
    risky = assess_connection(connection, pair, assessed_at=assessed_at, config=pr4_config())
    recovery = timedelta(hours=3)
    recovered_pair = (pair[0], replace(pair[1], predicted_arrival=pair[1].predicted_arrival + recovery))
    recovered = assess_connection(
        connection, recovered_pair, assessed_at=assessed_at, config=pr4_config()
    )
    assert risky.slack is not None and recovered.slack is not None
    assert recovered.slack.current_plan_slack - risky.slack.current_plan_slack == recovery
    assert recovered.slack.no_itt_slack - risky.slack.no_itt_slack == recovery
    assert risky.severity is RiskSeverity.AT_RISK
    assert recovered.severity is RiskSeverity.SAFE


def test_inter_terminal_no_itt_gain_is_exact_transfer_duration():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=-1))
    result = assess_connection(connection, pair, assessed_at=assessed_after(pair), config=pr4_config())
    assert result.slack is not None
    assert result.slack.no_itt_slack - result.slack.current_plan_slack == result.slack.transfer_duration


def test_same_terminal_invariant_and_counterfactual_are_preserved():
    connection = connection_with(same_terminal=True)
    pair = pair_for_slack(connection, timedelta(hours=-1))
    result = assess_connection(connection, pair, assessed_at=assessed_after(pair), config=pr4_config())
    assert result.slack is not None
    assert result.transfer_mode is TransferMode.NONE
    assert result.slack.transfer_duration == timedelta(0)
    assert result.slack.current_plan_slack == result.slack.no_itt_slack
    assert not result.avoidable_by_terminal_prevention


def test_malformed_same_terminal_projection_fails_instead_of_being_repaired():
    connection = connection_with(same_terminal=True)
    reference = connection.reference_projection
    malformed = replace(
        connection,
        process_projections=tuple(
            replace(item, transfer_mode=TransferMode.ROAD, transfer_duration=timedelta(hours=1))
            if item is reference
            else item
            for item in connection.process_projections
        ),
    )
    pair = pair_for_slack(connection, timedelta(hours=1))
    with pytest.raises(ValueError, match="same-terminal"):
        assess_connection(malformed, pair, assessed_at=assessed_after(pair), config=pr4_config())


def test_counterfactual_includes_zero_no_itt_but_excludes_zero_current_plan():
    connection = connection_with(same_terminal=False)
    transfer = connection.reference_projection.transfer_duration
    rescued_pair = pair_for_slack(connection, -transfer)
    rescued = assess_connection(
        connection,
        rescued_pair,
        assessed_at=assessed_after(rescued_pair),
        config=pr4_config(),
    )
    zero_pair = pair_for_slack(connection, timedelta(0))
    zero = assess_connection(
        connection,
        zero_pair,
        assessed_at=assessed_after(zero_pair),
        config=pr4_config(),
    )
    assert rescued.slack is not None and rescued.slack.no_itt_slack == timedelta(0)
    assert rescued.slack.current_plan_slack < timedelta(0)
    assert rescued.avoidable_by_terminal_prevention
    assert zero.slack is not None and zero.slack.current_plan_slack == timedelta(0)
    assert zero.severity is RiskSeverity.AT_RISK
    assert not zero.avoidable_by_terminal_prevention


@pytest.mark.parametrize(
    ("missing_leg", "reason"),
    [
        ("inbound", ReasonCode.INBOUND_PREDICTION_UNAVAILABLE),
        ("outbound", ReasonCode.OUTBOUND_PREDICTION_UNAVAILABLE),
    ],
)
def test_missing_leg_produces_unavailable_without_agent_event(missing_leg, reason):
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=1))
    updates = (pair[1],) if missing_leg == "inbound" else (pair[0],)
    result = assess_connection(
        connection, updates, assessed_at=assessed_after(updates), config=pr4_config()
    )
    assert result.status is AssessmentStatus.UNAVAILABLE
    assert result.severity is None
    assert result.slack is None
    assert not result.avoidable_by_terminal_prevention
    assert reason in result.reason_codes
    assert risk_event_from_assessment(result) is None


def test_risk_boundaries_and_warning_configuration_do_not_change_arithmetic():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=2))
    assessed_at = assessed_after(pair)
    equal_margin = assess_connection(
        connection, pair, assessed_at=assessed_at, config=pr4_config(timedelta(hours=2))
    )
    smaller_margin = assess_connection(
        connection, pair, assessed_at=assessed_at, config=pr4_config(timedelta(hours=1))
    )
    assert equal_margin.severity is RiskSeverity.WATCH
    assert smaller_margin.severity is RiskSeverity.SAFE
    assert equal_margin.slack == smaller_margin.slack


def test_derived_reference_delay_baseline_boundaries_and_input_surface():
    inbound = tiny_fixture_updates()[0]
    delayed = replace(
        inbound,
        predicted_arrival=inbound.reference_arrival + timedelta(hours=2),
        data_quality=DataQuality.DEGRADED,
        quality_reason_codes=("heading_unavailable",),
    )
    result = assess_derived_reference_delay(
        delayed,
        assessed_at=delayed.observed_at,
        threshold=timedelta(hours=2),
    )
    unavailable = assess_derived_reference_delay(
        None,
        assessed_at=delayed.observed_at,
        threshold=timedelta(hours=2),
    )
    assert result.delay == timedelta(hours=2)
    assert result.alert is True
    assert result.data_quality is DataQuality.DEGRADED
    assert unavailable.delay is None and unavailable.alert is None
    assert set(inspect.signature(assess_derived_reference_delay).parameters) == {
        "inbound",
        "assessed_at",
        "threshold",
    }


def test_derived_reference_delay_rejects_future_input_directly():
    inbound = tiny_fixture_updates()[0]
    assessed_at = inbound.observed_at
    future = replace(
        inbound,
        call_id="call_future_metadata_must_not_escape",
        observed_at=assessed_at + timedelta(seconds=1),
        data_quality=DataQuality.DEGRADED,
        quality_reason_codes=("future_quality_must_not_escape",),
    )

    with pytest.raises(ValueError, match="future inbound observation"):
        assess_derived_reference_delay(
            future,
            assessed_at=assessed_at,
            threshold=timedelta(minutes=15),
        )


def test_baseline_is_unchanged_when_connection_outbound_process_and_boxes_change():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=-1))
    assessed_at = assessed_after(pair)
    before = assess_connection(connection, pair, assessed_at=assessed_at, config=pr4_config())
    changed_projection = tuple(
        replace(
            item,
            cargo_ready_offset=item.cargo_ready_offset + timedelta(hours=7),
            cargo_cutoff_lead=item.cargo_cutoff_lead + timedelta(hours=8),
            transfer_duration=item.transfer_duration + timedelta(hours=9),
        )
        for item in connection.process_projections
    )
    changed_connection = replace(
        connection,
        impact_band=ImpactBand.SMALL,
        box_count=999,
        process_projections=changed_projection,
    )
    changed_outbound = replace(
        pair[1], predicted_arrival=pair[1].predicted_arrival + timedelta(days=3)
    )
    after = assess_connection(
        changed_connection,
        (pair[0], changed_outbound),
        assessed_at=assessed_at,
        config=pr4_config(),
    )
    assert before.baseline == after.baseline
    assert before.slack != after.slack


def test_selected_quality_uses_weaker_leg_without_conflating_synthetic_provenance():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=1))
    degraded = replace(
        pair[1],
        data_quality=DataQuality.DEGRADED,
        quality_reason_codes=("heading_unavailable",),
    )
    result = assess_connection(
        connection,
        (pair[0], degraded),
        assessed_at=assessed_after(pair),
        config=pr4_config(),
    )
    event = risk_event_from_assessment(result)
    assert result.data_quality is DataQuality.DEGRADED
    assert result.outbound_quality_reason_codes == ("heading_unavailable",)
    assert result.origin.terminal_resolution is TerminalResolution.SIMULATED
    assert event is not None and event.watcher_confidence is WatcherConfidence.MEDIUM


def test_assessment_is_deterministic_immutable_and_preserves_pr3_ucid():
    connection = connection_with(same_terminal=False, box_count=True)
    updates = tiny_fixture_updates()
    connection_before = connection
    updates_before = updates
    assessed_at = assessed_after(updates)
    first = assess_connection(connection, updates, assessed_at=assessed_at, config=pr4_config())
    second = assess_connection(connection, tuple(reversed(updates)), assessed_at=assessed_at, config=pr4_config())
    event = risk_event_from_assessment(first)
    assert first == second
    assert connection == connection_before
    assert updates == updates_before
    assert first.ucid == connection.identity.ucid
    assert event is not None and event.ucid == connection.identity.ucid
    assert event.connection_id == connection.identity.ucid
    assert event.assumptions.any_synthetic
    assert "not a PSA operating rule" in event.assumptions.transfer_scenario


def test_retrospective_call_outcome_fields_cannot_change_causal_assessment():
    connection = connection_with(same_terminal=False)
    pair = pair_for_slack(connection, timedelta(hours=-1))
    assessed_at = assessed_after(pair)

    retrospective = DerivedArrivalEvent(
        vessel_id=pair[0].vessel_id,
        call_id=pair[0].call_id,
        derived_geofence_arrival=assessed_at + timedelta(hours=1),
        first_eligible_pre_event_observation=pair[0].source_observation,
        eligible_pre_event_observations=1,
        pre_event_lookback=timedelta(hours=1),
        benchmark_eligible=True,
        exclusion_reasons=(),
        quality_reason_codes=(),
        data_quality=DataQuality.GOOD,
        boundary_version=pair[0].boundary_version,
        crossing_source_row_number=pair[0].source_observation.source_row_number + 1,
        arrival_updates=(pair[0],),
        eta_revisions=(),
    )
    changed_outcome = replace(
        retrospective,
        derived_geofence_arrival=retrospective.derived_geofence_arrival
        + timedelta(days=90),
        benchmark_eligible=False,
        exclusion_reasons=("retrospective_only",),
        quality_reason_codes=("future_full_call_result",),
        data_quality=DataQuality.EXCLUDED,
        crossing_source_row_number=retrospective.crossing_source_row_number + 50_000,
    )

    before = assess_connection(
        connection,
        (retrospective.arrival_updates[0], pair[1]),
        assessed_at=assessed_at,
        config=pr4_config(),
    )
    after = assess_connection(
        connection,
        (changed_outcome.arrival_updates[0], pair[1]),
        assessed_at=assessed_at,
        config=pr4_config(),
    )
    assert before == after


def test_boxless_assessment_never_invents_agent_volume():
    connection = connection_with(same_terminal=True, box_count=False)
    pair = pair_for_slack(connection, timedelta(hours=1))
    result = assess_connection(
        connection, pair, assessed_at=assessed_after(pair), config=pr4_config()
    )
    assert result.status is AssessmentStatus.AVAILABLE
    assert result.box_count is None
    assert risk_event_from_assessment(result) is None

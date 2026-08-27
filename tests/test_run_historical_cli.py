"""Parser regressions for the historical runner's distinct population bounds."""

import pytest

from latch.historical_eval import DEFAULT_SOURCE_CALL_LIMIT, MAX_SOURCE_CALL_LIMIT
from scripts.run_historical import (
    DEFAULT_LEGACY_ARRIVAL_UPDATE_LIMIT,
    build_parser,
    parse_cli_args,
)


def test_watcher_eval_rejects_explicit_legacy_limit(capsys):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--mode", "watcher-eval", "--limit", "100"])

    assert raised.value.code == 2
    assert (
        "--limit applies to the legacy agent run only; watcher-eval reads the "
        "full CSV and is bounded by --benchmark-call-limit"
        in capsys.readouterr().err
    )


def test_legacy_limit_keeps_its_default_and_accepts_an_explicit_value():
    assert parse_cli_args([]).limit == DEFAULT_LEGACY_ARRIVAL_UPDATE_LIMIT
    assert parse_cli_args(["--limit", "123"]).limit == 123


@pytest.mark.parametrize("value", ["1", str(MAX_SOURCE_CALL_LIMIT + 1)])
def test_benchmark_call_limit_rejects_values_outside_quadratic_safety_bound(
    value, capsys
):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--mode", "watcher-eval", "--benchmark-call-limit", value])

    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert f"between 2 and {MAX_SOURCE_CALL_LIMIT} inclusive" in error
    assert "explicit quadratic-generator safety bound" in error


def test_benchmark_call_limit_accepts_both_bounds_and_defaults_to_current_maximum():
    assert parse_cli_args(["--mode", "watcher-eval"]).benchmark_call_limit == (
        DEFAULT_SOURCE_CALL_LIMIT
    )
    assert parse_cli_args(
        ["--mode", "watcher-eval", "--benchmark-call-limit", "2"]
    ).benchmark_call_limit == 2
    assert parse_cli_args(
        [
            "--mode",
            "watcher-eval",
            "--benchmark-call-limit",
            str(MAX_SOURCE_CALL_LIMIT),
        ]
    ).benchmark_call_limit == MAX_SOURCE_CALL_LIMIT


def test_help_distinguishes_legacy_read_limit_from_watcher_population_bound():
    help_text = build_parser().format_help()

    assert "legacy arrival-update read limit" in help_text
    assert "accepted-call population bound for watcher-eval" in help_text
    assert f"default: {DEFAULT_SOURCE_CALL_LIMIT}, also the current maximum" in help_text

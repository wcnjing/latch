from pathlib import Path

import pytest

from latch.watcher_refinement_eval import (
    EXPERIMENTAL_WARNING_MARGINS,
    FROZEN_BASELINE_THRESHOLD,
    FROZEN_EVALUATION_HORIZONS,
    FROZEN_PR5_REFERENCE_MARGIN,
)
from scripts.run_watcher_refinement import build_parser, parse_cli_args


def test_cli_requires_a_caller_specified_output_path():
    with pytest.raises(SystemExit) as raised:
        parse_cli_args([])
    assert raised.value.code == 2


def test_cli_has_no_default_tracked_artifact_and_accepts_safe_path(tmp_path):
    output = tmp_path / "review-me.json"
    args = parse_cli_args(["--output", str(output)])
    assert args.output == output
    assert not output.exists()
    assert "artifacts/historical" not in str(args.output)


@pytest.mark.parametrize(
    "name",
    (
        "historical-watcher-report.json",
        "historical-watcher-report-v2.json",
    ),
)
def test_cli_rejects_pr5_report_targets(name, tmp_path):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--output", str(tmp_path / name)])
    assert raised.value.code == 2


def test_cli_exposes_no_margin_baseline_topology_or_process_tuning_flags():
    options = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert options == {"-h", "--help", "--csv", "--output"}


def test_cli_uses_frozen_experiment_declaration():
    assert tuple(value.total_seconds() / 3600 for value in EXPERIMENTAL_WARNING_MARGINS) == (
        0.0,
        1.0,
        2.0,
        3.0,
        4.0,
    )
    assert tuple(value.total_seconds() / 3600 for value in FROZEN_EVALUATION_HORIZONS) == (
        6.0,
        3.0,
        1.0,
    )
    assert FROZEN_PR5_REFERENCE_MARGIN.total_seconds() / 3600 == 2.0
    assert FROZEN_BASELINE_THRESHOLD.total_seconds() / 60 == 15.0


def test_help_states_separate_report_contract_and_no_default_artifact():
    help_text = build_parser().format_help()
    assert "watcher-refinement-report-v1" in help_text
    assert "no default tracked artifact" in help_text

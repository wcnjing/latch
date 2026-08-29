import pytest

from latch.terminal_prevention_challenge import (
    CHALLENGE_CURATION_LABEL,
    TERMINAL_PREVENTION_CHALLENGE_VERSION,
)
from scripts.run_terminal_prevention_challenge import (
    build_parser,
    parse_cli_args,
)


def test_cli_requires_caller_specified_output():
    with pytest.raises(SystemExit) as raised:
        parse_cli_args([])
    assert raised.value.code == 2


def test_cli_accepts_temporary_challenge_path_without_creating_it(tmp_path):
    output = tmp_path / "terminal-challenge.json"
    args = parse_cli_args(["--output", str(output)])
    assert args.output == output
    assert not output.exists()


@pytest.mark.parametrize(
    "path",
    (
        "artifacts/historical/terminal-prevention-challenge-v1.json",
        "historical-watcher-report-v2.json",
        "watcher-refinement-report-v1.json",
        "fixtures/synthetic/challenge.json",
    ),
)
def test_cli_rejects_historical_and_fixture_targets(path):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--output", path])
    assert raised.value.code == 2


def test_cli_exposes_no_scenario_assumption_policy_or_target_tuning_flags():
    options = {
        option
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert options == {"-h", "--help", "--csv", "--output"}


def test_help_names_separate_curated_contract():
    help_text = build_parser().format_help()
    assert TERMINAL_PREVENTION_CHALLENGE_VERSION in help_text
    assert "historical artifacts" in help_text
    assert "DELIBERATELY CURATED" in CHALLENGE_CURATION_LABEL

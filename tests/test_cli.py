import json
import shutil
from pathlib import Path

import pytest

from squander import __version__
from squander.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"
REPO_PRICES = Path(__file__).parent.parent / "prices.yaml"


@pytest.fixture
def logs_dir(tmp_path):
    project_dir = tmp_path / "-Users-someone-myproject"
    project_dir.mkdir()
    shutil.copy(FIXTURE, project_dir / "fixture-session-001.jsonl")
    return tmp_path


def run_analyze(capsys, *extra_args):
    code = main(["analyze", *extra_args])
    assert code == 0
    return capsys.readouterr().out


def test_json_output_shape(logs_dir, capsys):
    out = run_analyze(
        capsys, "--logs-dir", str(logs_dir), "--prices", str(REPO_PRICES), "--json"
    )
    payload = json.loads(out)
    assert set(payload) == {"sessions", "findings"}
    assert len(payload["sessions"]) == 1

    session = payload["sessions"][0]
    assert session["session_id"] == "fixture-session-001"
    assert session["project"] == "myproject"
    assert session["api_calls"] == 3
    assert session["input_tokens"] == 2 + 15 + 800
    assert session["cost_usd"] == pytest.approx(0.003834, abs=1e-6)
    # The tiny fixture session has no large context runs.
    assert payload["findings"] == []


def test_table_output_includes_session_row(logs_dir, capsys):
    out = run_analyze(
        capsys, "--logs-dir", str(logs_dir), "--prices", str(REPO_PRICES)
    )
    assert "fixture-" in out
    assert "myproject" in out
    assert "All token counts are exact" in out


def test_missing_logs_dir_errors(tmp_path, capsys):
    code = main(["analyze", "--logs-dir", str(tmp_path / "nope")])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_empty_logs_dir_json(tmp_path, capsys):
    out = run_analyze(
        capsys, "--logs-dir", str(tmp_path), "--prices", str(REPO_PRICES), "--json"
    )
    assert json.loads(out) == {"sessions": [], "findings": []}


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_missing_prices_file_errors_cleanly(logs_dir, capsys):
    code = main(
        ["analyze", "--logs-dir", str(logs_dir), "--prices", "/nope/prices.yaml"]
    )
    assert code == 1
    assert "error" in capsys.readouterr().err.lower()


def test_malformed_prices_file_errors_cleanly(logs_dir, tmp_path, capsys):
    bad_prices = tmp_path / "bad_prices.yaml"
    bad_prices.write_text("models:\n  broken-model:\n    input: 1.00\n")
    code = main(
        ["analyze", "--logs-dir", str(logs_dir), "--prices", str(bad_prices)]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "error" in err.lower()
    assert "bad_prices.yaml" in err

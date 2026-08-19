from __future__ import annotations

import pytest

from aarya_voice_lab.cli.main import PLANNED_COMMANDS, main
from aarya_voice_lab.core.paths import PROJECT_ROOT


def test_system_info_command(capsys):
    assert main(["system-info"]) == 0
    assert "AARYA Voice Lab" in capsys.readouterr().out


def test_system_info_json(capsys):
    assert main(["system-info", "--json"]) == 0
    assert '"os"' in capsys.readouterr().out


def test_validate_environment_command():
    assert main(["validate-environment"]) == 0


def test_validate_config_command(capsys):
    assert main(["validate-config"]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_manifest_on_template(capsys):
    path = PROJECT_ROOT / "manifests" / "templates" / "example_dataset_manifest.json"
    assert main(["validate-manifest", str(path)]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_manifest_missing_file():
    assert main(["validate-manifest", "/nonexistent/manifest.json"]) == 2


def test_validate_manifest_detects_invalid_record(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"segment_id": "x", "source_file_id": "y"}', encoding="utf-8")
    assert main(["validate-manifest", str(bad)]) == 1


@pytest.mark.parametrize("command", PLANNED_COMMANDS)
def test_planned_commands_refuse_to_run(command, capsys):
    """Critical guard: no future/unimplemented command may silently
    succeed, which could imply that private recordings were processed."""
    assert main([command]) == 3
    assert "PLANNED" in capsys.readouterr().err


def test_benchmark_help_exits_zero():
    assert main(["benchmark"]) == 0


def test_experiment_help_exits_zero():
    assert main(["experiment"]) == 0


def test_unknown_command_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code != 0

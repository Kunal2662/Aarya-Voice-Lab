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


def test_voice_engine_status_command(capsys):
    """Phase 1 of the 8-phase release plan -- this command had zero
    test coverage despite being 'the one honest place to see every
    provider's actual capability state.'"""
    assert main(["voice-engine-status"]) == 0
    out = capsys.readouterr().out
    assert "Real Voice Model Engine" in out
    assert "Embedding providers:" in out
    assert "Generation provider" in out
    assert "Training provider" in out


def test_voice_engine_status_json_reports_all_three_provider_kinds(capsys):
    import json

    assert main(["voice-engine-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "embedding_providers" in payload
    assert "generation_provider" in payload
    assert "training_provider" in payload
    assert len(payload["embedding_providers"]) >= 2  # synthetic + local-neural-embedding


def test_voice_engine_status_never_fabricates_available_on_this_checkout(capsys):
    """This checkout has no torch/nemo_toolkit/transformers/soundfile
    installed and no .envs/env-nemo built (confirmed empirically, not
    assumed) -- the real, non-synthetic providers must honestly report
    a non-AVAILABLE state, never a fabricated success. A synthetic
    provider's SYNTHETIC_ONLY state is not a claim of real availability
    and is excluded from this check."""
    import json

    assert main(["voice-engine-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    for report in payload["embedding_providers"]:
        if report["is_synthetic"]:
            continue
        assert report["state"] != "AVAILABLE", (
            f"provider {report['name']!r} reported AVAILABLE but no real embedding "
            "runtime is installed on this checkout"
        )

    assert payload["generation_provider"]["backend_state"] != "AVAILABLE"
    assert payload["training_provider"]["state"] != "AVAILABLE"


def test_release_check_command_passes_on_the_real_checkout(capsys):
    """Phase 7 of the 8-phase release plan: this checkout's own
    directories and schema version already satisfy its declared release
    layout -- a real, current-state assertion, not a fixture."""
    assert main(["release-check"]) == 0
    out = capsys.readouterr().out
    assert "Release Readiness Check" in out
    assert "Release readiness: PASSED" in out


def test_release_check_json(capsys):
    import json

    assert main(["release-check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["layout_problems"] == []
    assert payload["schema_compatible"] is True


def test_voice_engine_status_reports_missing_requirements_when_not_configured(capsys):
    import json

    assert main(["voice-engine-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    if payload["training_provider"]["state"] == "NOT_CONFIGURED":
        assert payload["training_provider"]["missing_requirements"]
    if payload["generation_provider"]["backend_state"] not in ("AVAILABLE",):
        # Real, human-readable explanation must exist -- never a bare state with no detail.
        assert payload["generation_provider"].get("detail")

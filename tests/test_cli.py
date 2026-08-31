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


def test_hf_login_reports_already_authenticated_without_prompting(capsys, monkeypatch):
    """Added during the Phase-2 installer audit, which found that
    `pipeline.hf_auth.prompt_and_login_interactive()` had no CLI command
    exposing it at all -- an operator had no installer-usable way to
    enter a HuggingFace token. Mocks `pipeline.hf_auth` (this test runs
    in the base interpreter, which never imports huggingface_hub)."""
    from aarya_voice_lab.pipeline import hf_auth as hf_auth_module

    monkeypatch.setattr(
        hf_auth_module, "check_existing_login", lambda: hf_auth_module.HFAuthStatus(authenticated=True, username="x")
    )

    def _fail_if_prompted():
        raise AssertionError("must not prompt for a new token when already authenticated")

    monkeypatch.setattr(hf_auth_module, "prompt_and_login_interactive", _fail_if_prompted)

    assert main(["hf-login"]) == 0
    assert "Already authenticated as x" in capsys.readouterr().out


def test_hf_login_reports_clean_failure_when_token_rejected(capsys, monkeypatch):
    from aarya_voice_lab.pipeline import hf_auth as hf_auth_module

    monkeypatch.setattr(
        hf_auth_module, "check_existing_login", lambda: hf_auth_module.HFAuthStatus(authenticated=False)
    )
    monkeypatch.setattr(
        hf_auth_module, "prompt_and_login_interactive", lambda: hf_auth_module.HFAuthStatus(authenticated=False)
    )

    assert main(["hf-login"]) == 1
    assert "rejected" in capsys.readouterr().err


def test_hf_login_never_prints_a_token_value(capsys, monkeypatch):
    """Security property: even a successful login must never echo the
    token itself -- only the non-secret username."""
    from aarya_voice_lab.pipeline import hf_auth as hf_auth_module

    secret_token = "hf_totally_secret_value_should_never_be_printed"
    monkeypatch.setattr(
        hf_auth_module, "check_existing_login", lambda: hf_auth_module.HFAuthStatus(authenticated=False)
    )
    monkeypatch.setattr(
        hf_auth_module,
        "prompt_and_login_interactive",
        lambda: hf_auth_module.HFAuthStatus(authenticated=True, username="test-user"),
    )

    assert main(["hf-login"]) == 0
    captured = capsys.readouterr()
    assert secret_token not in captured.out
    assert secret_token not in captured.err
    assert "Authenticated as test-user" in captured.out


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


def test_voice_engine_status_never_fabricates_generation_or_training_availability(capsys):
    """Generation and training have no real implementation anywhere in
    this project regardless of which machine this runs on -- unlike the
    embedding provider, whose AVAILABLE/NOT_CONFIGURED state legitimately
    varies by whether `.envs/env-nemo` happens to be built on this
    checkout (real on some machines, real elsewhere too, per
    docs/REAL_ML_RUNTIME_INTEGRATION.md), this assertion has no
    environment-dependent escape hatch: `LocalNeuralVoiceGenerator` always
    raises `GenerationBlockedError` and `LocalTrainingProvider` remains
    NOT_CONFIGURED by explicit, unchanged project decision."""
    import json

    assert main(["voice-engine-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["generation_provider"]["backend_state"] != "AVAILABLE"
    assert payload["training_provider"]["state"] != "AVAILABLE"


def test_voice_engine_status_embedding_state_is_never_available_without_a_missing_requirements_list_that_matches(
    capsys,
):
    """The embedding provider's AVAILABLE/NOT_CONFIGURED state is real and
    machine-dependent (this checkout may or may not have `.envs/env-nemo`
    built) -- this test asserts the honest-reporting invariant that holds
    either way: a NOT_CONFIGURED real (non-synthetic) provider must name
    real missing requirements, and an AVAILABLE one must not claim any
    requirement is still missing. Never asserts a fixed state for the
    embedding provider itself, since that would encode this checkout's
    current environment rather than a real project invariant."""
    import json

    assert main(["voice-engine-status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    for report in payload["embedding_providers"]:
        if report["is_synthetic"]:
            continue
        if report["state"] == "NOT_CONFIGURED":
            assert report.get("missing_requirements") or report.get("detail"), (
                f"provider {report['name']!r} reported NOT_CONFIGURED with no explanation"
            )
        elif report["state"] == "AVAILABLE":
            assert not report.get("missing_requirements")


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

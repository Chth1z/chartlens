from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_eval_cli_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "run-ocr-eval.py"
    spec = importlib.util.spec_from_file_location("run_ocr_eval_cli", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_ocr_eval_cli_exits_nonzero_for_stale_sidecar(monkeypatch, capsys):
    module = _load_eval_cli_module()

    def fake_run_ocr_evaluation_profile(profile_id: str) -> dict:
        return {
            "summary": {
                "hard_blocker": "stale_ocr_sidecar",
                "blocker_message": "expected ocr-canonical-layout-v3; restart with .\\stop.cmd, then .\\start.cmd",
            }
        }

    monkeypatch.setattr(module, "run_ocr_evaluation_profile", fake_run_ocr_evaluation_profile)
    monkeypatch.setattr(module.sys, "argv", ["run-ocr-eval.py", "--profile-id", "synthetic_medical_directml"])

    assert module.main() == 2
    assert "ocr-canonical-layout-v3" in capsys.readouterr().out


def test_run_ocr_eval_cli_exits_nonzero_for_unreachable_sidecar(monkeypatch, capsys):
    module = _load_eval_cli_module()

    def fake_run_ocr_evaluation_profile(profile_id: str) -> dict:
        return {
            "summary": {
                "hard_blocker": "ocr_sidecar_preflight_failed",
                "blocker_message": "OCR sidecar 未运行或无法连接",
            }
        }

    monkeypatch.setattr(module, "run_ocr_evaluation_profile", fake_run_ocr_evaluation_profile)
    monkeypatch.setattr(module.sys, "argv", ["run-ocr-eval.py", "--profile-id", "synthetic_medical_directml"])

    assert module.main() == 2
    assert "OCR sidecar" in capsys.readouterr().out


def test_run_ocr_eval_cli_exits_nonzero_for_template_without_explicit_blocker_report(monkeypatch):
    module = _load_eval_cli_module()

    def fake_run_ocr_evaluation_profile(profile_id: str) -> dict:
        return {
            "summary": {
                "hard_blocker": "template_profile",
                "blocker_message": "This OCR evaluation profile is a manifest template.",
            }
        }

    monkeypatch.setattr(module, "run_ocr_evaluation_profile", fake_run_ocr_evaluation_profile)
    monkeypatch.setattr(module.sys, "argv", ["run-ocr-eval.py", "--profile-id", "real_hardware_case_template"])

    assert module.main() == 2


def test_run_ocr_eval_cli_allows_template_blocker_report_when_requested(monkeypatch):
    module = _load_eval_cli_module()

    def fake_run_ocr_evaluation_profile(profile_id: str) -> dict:
        return {
            "summary": {
                "hard_blocker": "template_profile",
                "blocker_message": "This OCR evaluation profile is a manifest template.",
            }
        }

    monkeypatch.setattr(module, "run_ocr_evaluation_profile", fake_run_ocr_evaluation_profile)
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["run-ocr-eval.py", "--profile-id", "real_hardware_case_template", "--allow-empty-hardware-profile"],
    )

    assert module.main() == 0

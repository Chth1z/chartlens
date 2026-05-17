from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ocr_engine.regression import run_ocr_evaluation_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EYEX OCR regression profile.")
    parser.add_argument("--profile-id", default="mock_general", help="OCR evaluation profile id")
    parser.add_argument(
        "--allow-empty-hardware-profile",
        action="store_true",
        help="Print an explicit blocker report instead of failing for blocked hardware, template, or preflight profiles.",
    )
    args = parser.parse_args()
    result = run_ocr_evaluation_profile(args.profile_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    summary = result.get("summary", {})
    hard_blocker = str(summary.get("hard_blocker") or "")
    if hard_blocker and not args.allow_empty_hardware_profile:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entry point for EYEX field extraction evaluation profiles.

Report schema is the same as the FastAPI `/api/evals/profiles/{id}/run`
endpoint plus a top-level ``schema_version`` key. See
`backend/app/services/extraction_eval.py` for the canonical builder.

Exit codes:
- 0: profile evaluated and report printed.
- 2: profile is blocked (no gold cases or one or more cases not processed).
  Pass ``--allow-blocked`` to print the blocker report and exit 0 anyway,
  for example when running the runner only to inspect the gold contract.

The runner does not process cases. Upload and process the gold cases first
through the normal pipeline, then run this CLI to score the stored results.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.services.extraction_eval import run_extraction_evaluation_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EYEX field extraction evaluation profile.")
    parser.add_argument("--profile-id", default="mock_general", help="Evaluation profile id under config/evaluation_profiles/")
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Print the blocker report and exit 0 even when the profile has no gold cases or referenced cases are missing from the database.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Where to write the JSON report. '-' writes to stdout (default).",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        report = run_extraction_evaluation_profile(args.profile_id, db=db)
    finally:
        db.close()

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(rendered)
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered, encoding="utf-8")

    summary = report.get("summary", {})
    hard_blocker = str(summary.get("hard_blocker") or "")
    if hard_blocker and not args.allow_blocked:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

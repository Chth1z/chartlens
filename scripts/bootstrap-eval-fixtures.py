"""Bootstrap evaluation profile fixtures into the database.

Reads the gold cases declared in `config/evaluation_profiles/<profile_id>.yaml`,
matches each `case_id` to a text fixture under
`config/evaluation_profiles/fixtures/<profile_id>/<case_id>.txt`, processes
the case through the standard pipeline using `ConservativeLocalProvider`
(rule-only, no remote LLM), and persists the validated field results.

Usage:
    python scripts/bootstrap-eval-fixtures.py --profile-id mock_general
    python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline

Adding `--baseline` writes a JSON baseline of the post-processing extraction
eval report to `config/evaluation_profiles/baselines/<profile_id>.json`. The
baseline is the canonical "before" reference for any future precision task
that targets this profile (per AGENTS.md Precision Tasks).

Exit codes:
- 0: all gold cases processed (and baseline written if requested).
- 2: at least one fixture file is missing.
- 3: the eval runner reported a hard blocker (unexpected; usually means a
  fixture failed to process). Re-run with verbose backend logs to debug.
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

from app.core.config_loader import load_evaluation_profile  # noqa: E402
from app.core.database import (  # noqa: E402
    CaseRecord,
    FieldResultRecord,
    ModelCallRecord,
    ProcessingEventRecord,
    ProcessingRunRecord,
    ReviewAuditRecord,
    SessionLocal,
    init_db,
)
from app.services.extraction_eval import run_extraction_evaluation_profile  # noqa: E402
from app.services.llm_provider.local_extraction import ConservativeLocalProvider  # noqa: E402
from app.services.pipeline import process_case  # noqa: E402


def fixtures_dir(profile_id: str) -> Path:
    return ROOT / "config" / "evaluation_profiles" / "fixtures" / profile_id


def baselines_dir() -> Path:
    return ROOT / "config" / "evaluation_profiles" / "baselines"


def fixture_path(profile_id: str, case_id: str) -> Path:
    return fixtures_dir(profile_id) / f"{case_id}.txt"


def _cleanup_case(db, case_id: str) -> None:
    db.query(ModelCallRecord).filter(ModelCallRecord.case_id == case_id).delete()
    db.query(ProcessingEventRecord).filter(ProcessingEventRecord.case_id == case_id).delete()
    db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == case_id).delete()
    db.query(ReviewAuditRecord).filter(ReviewAuditRecord.case_id == case_id).delete()
    db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
    db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
    db.commit()


def _bootstrap_case(db, case_id: str, fixture: Path) -> None:
    _cleanup_case(db, case_id)
    case = CaseRecord(
        case_id=case_id,
        filename=fixture.name,
        file_hash=case_id,
        file_path=str(fixture),
        status="queued",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    process_case(db, case, semantic_provider=ConservativeLocalProvider())


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap eval profile fixtures into the local database.")
    parser.add_argument("--profile-id", default="mock_general")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="After processing, run the extraction eval and write the report to config/evaluation_profiles/baselines/<profile>.json.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Delete the matching case rows without reprocessing. Useful before switching providers or running a full re-baseline.",
    )
    args = parser.parse_args()

    init_db()
    profile = load_evaluation_profile(args.profile_id)
    fixtures_root = fixtures_dir(args.profile_id)
    if not profile.gold_cases:
        print(f"profile '{args.profile_id}' has no gold cases; nothing to bootstrap.", file=sys.stderr)
        return 0

    missing: list[str] = []
    for gold_case in profile.gold_cases:
        path = fixture_path(args.profile_id, gold_case.case_id)
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
    if missing:
        print("missing fixture files:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        for gold_case in profile.gold_cases:
            path = fixture_path(args.profile_id, gold_case.case_id)
            if args.clean_only:
                _cleanup_case(db, gold_case.case_id)
                print(f"cleaned: {gold_case.case_id}")
                continue
            _bootstrap_case(db, gold_case.case_id, path)
            print(f"processed: {gold_case.case_id}")
    finally:
        db.close()

    if args.clean_only:
        return 0

    if not args.baseline:
        return 0

    db = SessionLocal()
    try:
        report = run_extraction_evaluation_profile(args.profile_id, db=db)
    finally:
        db.close()

    summary = report.get("summary", {})
    if summary.get("hard_blocker"):
        print(f"baseline run reported hard_blocker={summary['hard_blocker']}", file=sys.stderr)
        return 3

    baselines_root = baselines_dir()
    baselines_root.mkdir(parents=True, exist_ok=True)
    target = baselines_root / f"{args.profile_id}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"baseline written: {target.relative_to(ROOT)}")
    print(
        "summary: "
        f"accuracy={summary.get('accuracy', 0.0):.4f} "
        f"auto_accept_precision={summary.get('auto_accept_precision', 0.0):.4f} "
        f"evidence_coverage={summary.get('evidence_coverage', 0.0):.4f} "
        f"unknown_misfill_rate={summary.get('unknown_misfill_rate', 0.0):.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

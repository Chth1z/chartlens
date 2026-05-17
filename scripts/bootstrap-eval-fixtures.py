"""Bootstrap evaluation profile fixtures into the database.

Reads the gold cases declared in `config/evaluation_profiles/<profile_id>.yaml`,
matches each `case_id` to a text fixture under
`config/evaluation_profiles/fixtures/<profile_id>/<case_id>.txt`, processes
the case through the standard pipeline using the chosen provider, and
persists the validated field results.

Usage:
    python scripts/bootstrap-eval-fixtures.py --profile-id mock_general
    python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --baseline
    python scripts/bootstrap-eval-fixtures.py --profile-id mock_general --provider llm --baseline

The `--provider` flag selects which semantic provider drives the LLM
evidence-collection / adjudication path:
- `rule` (default): use `ConservativeLocalProvider`. Deterministic, zero
  token cost, no network. Output baseline file: `<profile>.json`.
- `llm`: use `build_semantic_provider()` which respects the active model
  profile (default: `EYEX_MODEL_PROFILE` from settings, overridden by
  `var/storage/model_selection.json` when present). Goes through the
  configured remote provider, captures real token cost. Output baseline
  file: `<profile>_llm.json` so the rule-only baseline floor is never
  overwritten.

Adding `--baseline` writes a JSON baseline of the post-processing eval
report to `config/evaluation_profiles/baselines/<profile_id>[_llm].json`.
The baseline is the canonical "before" reference for any future precision
task that targets this profile (per AGENTS.md Precision Tasks).

Exit codes:
- 0: all gold cases processed (and baseline written if requested).
- 2: at least one fixture file is missing.
- 3: the eval runner reported a hard blocker (unexpected; usually means a
  fixture failed to process). Re-run with verbose backend logs to debug.
- 4: --provider llm was requested but no API key resolved through the
  active model profile. Configure the key first (provider settings UI or
  .env) and re-run.
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
from app.services.llm_provider.fallback import build_semantic_provider  # noqa: E402
from app.services.llm_provider.local_extraction import ConservativeLocalProvider  # noqa: E402
from app.services.llm_provider.types import SemanticExtractionProvider  # noqa: E402
from app.services.model_auth import api_keys_for_profile  # noqa: E402
from app.services.model_selection import get_active_model_profile  # noqa: E402
from app.services.pipeline import process_case  # noqa: E402


def fixtures_dir(profile_id: str) -> Path:
    return ROOT / "config" / "evaluation_profiles" / "fixtures" / profile_id


def baselines_dir() -> Path:
    return ROOT / "config" / "evaluation_profiles" / "baselines"


def fixture_path(profile_id: str, case_id: str) -> Path:
    return fixtures_dir(profile_id) / f"{case_id}.txt"


def baseline_path(profile_id: str, provider_kind: str) -> Path:
    suffix = "_llm" if provider_kind == "llm" else ""
    return baselines_dir() / f"{profile_id}{suffix}.json"


def _make_provider(provider_kind: str) -> SemanticExtractionProvider:
    if provider_kind == "rule":
        return ConservativeLocalProvider()
    if provider_kind == "llm":
        # build_semantic_provider() reads active model profile + auth state.
        # No new state mutations here.
        return build_semantic_provider()
    raise ValueError(f"unknown provider kind: {provider_kind!r}")


def _verify_llm_key() -> tuple[bool, str]:
    """Verify a key is resolvable for the current active model profile.

    Returns (ok, label). label is a redacted description never containing
    the key value itself.
    """
    try:
        profile = get_active_model_profile()
    except Exception as exc:
        return False, f"active profile load failed: {exc}"
    keys = api_keys_for_profile(profile)
    if not keys:
        return False, f"no API key resolved for profile '{profile.profile_id}' ({profile.provider})"
    first = keys[0]
    fingerprint = first[:2] + "..." + first[-2:] if len(first) > 6 else "***"
    return True, f"profile={profile.profile_id} provider={profile.provider} key_fingerprint={fingerprint}"


def _cleanup_case(db, case_id: str) -> None:
    db.query(ModelCallRecord).filter(ModelCallRecord.case_id == case_id).delete()
    db.query(ProcessingEventRecord).filter(ProcessingEventRecord.case_id == case_id).delete()
    db.query(ProcessingRunRecord).filter(ProcessingRunRecord.case_id == case_id).delete()
    db.query(ReviewAuditRecord).filter(ReviewAuditRecord.case_id == case_id).delete()
    db.query(FieldResultRecord).filter(FieldResultRecord.case_id == case_id).delete()
    db.query(CaseRecord).filter(CaseRecord.case_id == case_id).delete()
    db.commit()


def _bootstrap_case(db, case_id: str, fixture: Path, provider: SemanticExtractionProvider) -> None:
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
    process_case(db, case, semantic_provider=provider)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap eval profile fixtures into the local database.")
    parser.add_argument("--profile-id", default="mock_general")
    parser.add_argument(
        "--provider",
        choices=("rule", "llm"),
        default="rule",
        help="Semantic provider: 'rule' for ConservativeLocalProvider (default), 'llm' for build_semantic_provider().",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="After processing, run the extraction eval and write the report to config/evaluation_profiles/baselines/<profile_id>[_llm].json.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Delete the matching case rows without reprocessing. Useful before switching providers or running a full re-baseline.",
    )
    args = parser.parse_args()

    init_db()

    if args.provider == "llm":
        ok, label = _verify_llm_key()
        if not ok:
            print(f"FAIL: --provider llm requested but no key available. {label}", file=sys.stderr)
            return 4
        print(f"using LLM provider: {label}")

    profile = load_evaluation_profile(args.profile_id)
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

    if args.clean_only:
        db = SessionLocal()
        try:
            for gold_case in profile.gold_cases:
                _cleanup_case(db, gold_case.case_id)
                print(f"cleaned: {gold_case.case_id}")
        finally:
            db.close()
        return 0

    db = SessionLocal()
    try:
        for gold_case in profile.gold_cases:
            path = fixture_path(args.profile_id, gold_case.case_id)
            # Build a fresh provider per case so any per-call usage counter
            # is not aggregated across cases inside a single provider object.
            provider = _make_provider(args.provider)
            _bootstrap_case(db, gold_case.case_id, path, provider)
            print(f"processed [{args.provider}]: {gold_case.case_id}")
    finally:
        db.close()

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

    target = baseline_path(args.profile_id, args.provider)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Tag the baseline with provider kind so the on-disk file is self-describing.
    if isinstance(report.get("profile"), dict):
        report["profile"]["semantic_provider_kind"] = args.provider
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"baseline written: {target.relative_to(ROOT)}")
    print(
        "summary: "
        f"accuracy={summary.get('accuracy', 0.0):.4f} "
        f"auto_accept_precision={summary.get('auto_accept_precision', 0.0):.4f} "
        f"evidence_coverage={summary.get('evidence_coverage', 0.0):.4f} "
        f"unknown_misfill_rate={summary.get('unknown_misfill_rate', 0.0):.4f} "
        f"input_tokens={summary.get('input_tokens', 0)} "
        f"output_tokens={summary.get('output_tokens', 0)} "
        f"cost_usd={summary.get('cost_usd', 0.0):.6f}"
    )
    if args.provider == "llm" and summary.get("input_tokens", 0) == 0:
        print(
            "WARN: --provider llm requested but the baseline recorded zero input tokens. "
            "The active model profile's adapter likely does not implement collect_evidence(), "
            "so the evidence-first path silently fell back to local rule extraction. See "
            "docs/ARCHITECTURE.md (Boundary Contracts > EvidenceCandidate) and "
            "docs/ROADMAP.md E1-011 for the implementation gap.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from pathlib import Path


def test_production_services_do_not_import_legacy_ocr_or_provider_bridges():
    root = Path(__file__).resolve().parents[1] / "app"
    assert not (root / "services" / "intelligent_ocr.py").exists()
    assert not (root / "services" / "provider.py").exists()

    legacy_patterns = (
        "app.services.intelligent_ocr",
        "from app.services import intelligent_ocr",
        "app.services.provider",
        "from app.services.provider",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in legacy_patterns):
            offenders.append(str(path.relative_to(root.parents[0])))

    assert offenders == []

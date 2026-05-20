"""Optional Presidio-based PHI detection layer.

Provides a second-pass NER-based de-identification using Microsoft Presidio.
Enabled via EYEX_PRESIDIO_ENABLED=true. When presidio-analyzer is not installed,
the module gracefully returns empty results.

This layer runs AFTER the existing regex-based deidentify.py pass and catches
PHI that regex patterns miss (non-standard formats, contextual person names,
addresses without standard prefixes).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.settings import settings

logger = logging.getLogger(__name__)

_analyzer_instance = None
_initialization_attempted = False


@dataclass
class PresidioFinding:
    """A PHI finding from Presidio analysis."""
    entity_type: str
    text: str
    start: int
    end: int
    score: float


def presidio_enabled() -> bool:
    """Check if Presidio de-identification is enabled."""
    return getattr(settings, "presidio_enabled", False)


def presidio_available() -> bool:
    """Check if presidio-analyzer is installed."""
    try:
        import presidio_analyzer  # noqa: F401
        return True
    except ImportError:
        return False


def analyze_text(text: str) -> list[PresidioFinding]:
    """Run Presidio analysis on text. Returns PHI findings.

    Returns empty list if:
    - Presidio is disabled
    - presidio-analyzer is not installed
    - Analysis fails for any reason
    """
    if not presidio_enabled():
        return []

    analyzer = _get_analyzer()
    if analyzer is None:
        return []

    try:
        results = analyzer.analyze(
            text=text,
            language="zh",
            entities=[
                "PERSON",
                "PHONE_NUMBER",
                "ID_NUMBER",
                "LOCATION",
                "MEDICAL_RECORD",
            ],
            score_threshold=0.6,
        )
        return [
            PresidioFinding(
                entity_type=r.entity_type,
                text=text[r.start:r.end],
                start=r.start,
                end=r.end,
                score=r.score,
            )
            for r in results
        ]
    except Exception as exc:
        logger.warning("Presidio analysis failed: %s", exc)
        return []


def redact_with_presidio(text: str) -> str:
    """Apply Presidio-based redaction to text.

    Replaces detected PHI with type-specific placeholders.
    Returns original text if Presidio is disabled or unavailable.
    """
    findings = analyze_text(text)
    if not findings:
        return text

    # Sort by position (reverse) to replace from end to start
    findings.sort(key=lambda f: f.start, reverse=True)

    result = text
    for finding in findings:
        replacement = _replacement_for_type(finding.entity_type)
        result = result[:finding.start] + replacement + result[finding.end:]

    return result


def presidio_risk_findings(text: str) -> list[str]:
    """Return entity types found by Presidio (for risk scoring).

    Used by the online LLM gate to detect residual PHI that regex missed.
    """
    findings = analyze_text(text)
    return list(dict.fromkeys(f.entity_type for f in findings))


def _replacement_for_type(entity_type: str) -> str:
    """Map entity type to redaction placeholder."""
    replacements = {
        "PERSON": "[PERSON]",
        "PHONE_NUMBER": "[PHONE]",
        "ID_NUMBER": "[ID]",
        "LOCATION": "[ADDRESS]",
        "MEDICAL_RECORD": "[MRN]",
    }
    return replacements.get(entity_type, "[REDACTED]")


def _get_analyzer():
    """Get or create the Presidio analyzer instance (lazy singleton)."""
    global _analyzer_instance, _initialization_attempted

    if _analyzer_instance is not None:
        return _analyzer_instance

    if _initialization_attempted:
        return None

    _initialization_attempted = True

    try:
        from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        # Try to use spaCy if available, otherwise use pattern-only mode
        try:
            configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "zh", "model_name": "zh_core_web_sm"}],
            }
            nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
            analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["zh"])
        except Exception:
            # Fall back to pattern-only analyzer (no spaCy model needed)
            analyzer = AnalyzerEngine(supported_languages=["zh"])

        # Add custom Chinese recognizers
        _add_chinese_recognizers(analyzer)

        _analyzer_instance = analyzer
        logger.info("Presidio analyzer initialized successfully")
        return _analyzer_instance

    except Exception as exc:
        logger.warning("Failed to initialize Presidio analyzer: %s", exc)
        return None


def _add_chinese_recognizers(analyzer) -> None:
    """Add custom pattern recognizers for Chinese medical PHI."""
    from presidio_analyzer import PatternRecognizer, Pattern

    # Chinese ID card (18 digits, last may be X)
    id_card_recognizer = PatternRecognizer(
        supported_entity="ID_NUMBER",
        supported_language="zh",
        patterns=[
            Pattern(
                name="chinese_id_card",
                regex=r"\b\d{17}[\dXx]\b",
                score=0.85,
            ),
        ],
        context=["身份证", "证件号", "身份证号"],
    )

    # Chinese phone numbers
    phone_recognizer = PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        supported_language="zh",
        patterns=[
            Pattern(
                name="chinese_mobile",
                regex=r"(?<!\d)1[3-9]\d{9}(?!\d)",
                score=0.85,
            ),
            Pattern(
                name="chinese_landline",
                regex=r"(?<!\d)\d{3,4}[- ]?\d{7,8}(?!\d)",
                score=0.6,
            ),
        ],
        context=["电话", "联系电话", "手机", "联系方式"],
    )

    # Medical record numbers
    mrn_recognizer = PatternRecognizer(
        supported_entity="MEDICAL_RECORD",
        supported_language="zh",
        patterns=[
            Pattern(
                name="hospital_mrn",
                regex=r"(?:住院号|病案号|门诊号)[:：]?\s*\d{4,12}",
                score=0.9,
            ),
        ],
    )

    # Chinese addresses (broader than the regex in deidentify.py)
    address_recognizer = PatternRecognizer(
        supported_entity="LOCATION",
        supported_language="zh",
        patterns=[
            Pattern(
                name="chinese_address",
                regex=r"(?:居住在|住在|家住|现住|地址[:：]?)[^\n，,；;。]{2,50}(?:省|市|区|县|镇|乡|街道|街|路|园|院|村|号|楼|室)",
                score=0.7,
            ),
        ],
    )

    for recognizer in [id_card_recognizer, phone_recognizer, mrn_recognizer, address_recognizer]:
        analyzer.registry.add_recognizer(recognizer)


def reset_analyzer() -> None:
    """Reset the analyzer instance (for testing)."""
    global _analyzer_instance, _initialization_attempted
    _analyzer_instance = None
    _initialization_attempted = False

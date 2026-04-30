from __future__ import annotations

import re

from app.domain.models import DocumentIR, DocumentIRBlock, DocumentProfile

ID_CARD = re.compile(r"\b\d{17}[\dXx]\b")
PHONE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|\d{3,4}[- ]?\d{7,8})(?!\d)")
DEFAULT_INLINE_LABELS = ("姓名", "身份证号", "身份证", "电话", "联系电话", "住院号", "门诊号", "病案号", "住址", "家庭住址", "联系人")
RESIDUAL_ADDRESS = re.compile(
    r"(?:居住在|住在|家住|现住|地址[:：]?)"
    r"[^，,；;\s。]{2,40}(?:省|市|区|县|镇|乡|街道|街|路|园|院|村|号)"
)


def deidentify_text(text: str, profile: DocumentProfile) -> str:
    scrubbed = text
    for pattern, replacement in _redaction_patterns(profile):
        scrubbed = pattern.sub(replacement, scrubbed)
    labels = tuple(dict.fromkeys([*DEFAULT_INLINE_LABELS, *profile.excluded_phi_labels, *profile.phi_inline_labels]))
    for label in labels:
        scrubbed = re.sub(rf"({re.escape(label)}\s*[:：]\s*)[^，,；;\s。]+", rf"\1[REDACTED]", scrubbed)
    return scrubbed


def deidentify_document_ir(document_ir: DocumentIR, profile: DocumentProfile) -> DocumentIR:
    blocks: list[DocumentIRBlock] = []
    risk_findings: list[str] = []
    blocking_patterns = _online_blocking_patterns(profile)
    for block in document_ir.blocks:
        for key, pattern in blocking_patterns:
            if pattern.search(block.text):
                risk_findings.append(key)
        blocks.append(block.model_copy(update={"text": deidentify_text(block.text, profile)}))
    unique_findings = list(dict.fromkeys(risk_findings))
    metadata = {
        **_deidentify_metadata(document_ir.metadata, profile),
        "deidentification": {
            "risk_score": len(unique_findings),
            "risk_findings": unique_findings,
            "online_llm_allowed": not unique_findings,
        },
    }
    return document_ir.model_copy(update={"blocks": blocks, "metadata": metadata})


def _redaction_patterns(profile: DocumentProfile) -> list[tuple[re.Pattern, str]]:
    if profile.phi_patterns:
        patterns: list[tuple[re.Pattern, str]] = []
        for item in profile.phi_patterns:
            try:
                patterns.append((re.compile(item.pattern), item.replacement))
            except re.error:
                continue
        return patterns
    return [(ID_CARD, "[ID]"), (PHONE, "[PHONE]"), (RESIDUAL_ADDRESS, "[ADDRESS]")]


def _online_blocking_patterns(profile: DocumentProfile) -> list[tuple[str, re.Pattern]]:
    patterns: list[tuple[str, re.Pattern]] = []
    for item in profile.phi_patterns:
        if not item.blocks_online_llm:
            continue
        try:
            patterns.append((item.key, re.compile(item.pattern)))
        except re.error:
            continue
    if not patterns:
        patterns.append(("RESIDUAL_ADDRESS_PATTERN", RESIDUAL_ADDRESS))
    return patterns


def _deidentify_metadata(value, profile: DocumentProfile):
    if isinstance(value, str):
        return deidentify_text(value, profile)
    if isinstance(value, list):
        return [_deidentify_metadata(item, profile) for item in value]
    if isinstance(value, dict):
        return {key: _deidentify_metadata(item, profile) for key, item in value.items()}
    return value

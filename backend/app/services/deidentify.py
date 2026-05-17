from __future__ import annotations

import re
import hashlib

from app.domain.models import DocumentIR, DocumentIRBlock, DocumentProfile, FieldDefinition, PreRedactionDerivationRule

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
        safe_text = deidentify_text(block.text, profile)
        update = {"text": safe_text}
        if block.key_label and block.value_text is not None and safe_text != block.text:
            update["value_text"] = _redacted_value_text(block.key_label, block.value_text, profile)
        blocks.append(block.model_copy(update=update))
    blocks.extend(_pre_redaction_safe_blocks(document_ir))
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


def _pre_redaction_safe_blocks(document_ir: DocumentIR) -> list[DocumentIRBlock]:
    try:
        from app.core.config_loader import load_extraction_schema

        schema = load_extraction_schema()
    except Exception:
        return []

    safe_blocks: list[DocumentIRBlock] = []
    next_order = max((block.reading_order for block in document_ir.blocks), default=0) + 1
    for field in schema.fields:
        if not field.pre_redaction_derivations:
            continue
        match = _single_derivation_match(field, document_ir.blocks)
        if match is None:
            continue
        rule, source = match
        safe_text = rule.safe_text
        digest = hashlib.sha1(f"{field.key}:{rule.normalized_code}:{source.block_id}:{safe_text}".encode("utf-8")).hexdigest()
        safe_blocks.append(
            source.model_copy(
                update={
                    "block_id": f"b{next_order:04d}-derived-{digest[:8]}",
                    "reading_order": next_order,
                    "text": safe_text,
                    "confidence": rule.confidence,
                    "block_type": "key_value",
                    "source_engine": "pre_redaction_derivation",
                    "stage_source": "pre_redaction_derivation",
                    "quality_flags": [*source.quality_flags, "pre_redaction_safe_derivation"],
                }
            )
        )
        next_order += 1
    return safe_blocks


def _single_derivation_match(
    field: FieldDefinition,
    blocks: list[DocumentIRBlock],
) -> tuple[PreRedactionDerivationRule, DocumentIRBlock] | None:
    matches: list[tuple[PreRedactionDerivationRule, DocumentIRBlock]] = []
    for block in blocks:
        if field.source_sections and block.section_label not in field.source_sections:
            continue
        if block.section_label in field.excluded_sections:
            continue
        for rule in field.pre_redaction_derivations:
            if _derivation_rule_matches(rule, block.text):
                matches.append((rule, block))
    matched_codes = {rule.normalized_code for rule, _ in matches}
    if len(matched_codes) != 1:
        return None
    return max(matches, key=lambda item: (item[0].confidence, item[1].confidence, -item[1].reading_order))


def _derivation_rule_matches(rule: PreRedactionDerivationRule, text: str) -> bool:
    if any(term and term in text for term in rule.source_terms):
        return True
    for pattern_text in rule.source_patterns:
        try:
            if re.search(pattern_text, text):
                return True
        except re.error:
            continue
    return False


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


def _redacted_value_text(label: str, value: str, profile: DocumentProfile) -> str:
    sensitive_labels = set(DEFAULT_INLINE_LABELS)
    sensitive_labels.update(profile.excluded_phi_labels)
    sensitive_labels.update(profile.phi_inline_labels)
    return "[REDACTED]" if label in sensitive_labels else deidentify_text(value, profile)


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

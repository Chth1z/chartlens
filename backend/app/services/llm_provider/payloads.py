from __future__ import annotations
import json
import re
import base64
import hashlib
import mimetypes
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import httpx

from app.core.config_loader import load_document_profile, load_extraction_schema
from app.core.settings import settings
from app.domain.models import (
    DocumentIR, DocumentContext, DocumentIRBlock, EvidenceCandidate,
    ExtractedFact, ExtractionCandidate, FieldDecision, FieldDefinition,
    FieldGroup, RemoteExposurePolicy
)
from app.services.document_context import document_context_payload
from app.services.evidence import build_evidence_packs
from app.services.domain_profile import extraction_rules, extraction_system_prompt
from app.services.model_auth import api_keys_for_profile
from app.services.model_selection import get_active_model_profile, resolve_model_chain
from app.services.safe_errors import safe_error_message
from .parsing import _response_schema, _evidence_candidate_response_schema

DEFAULT_PROVIDER_GROUP_BUDGET = 3200

def _responses_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile=None,
) -> dict[str, Any]:
    model_profile = profile or get_active_model_profile()
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    payload: dict[str, Any] = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": extraction_system_prompt(document_profile),
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "eyex_group_extraction",
                "strict": True,
                "schema": _response_schema(),
            }
        },
        "store": False,
        "prompt_cache_key": model_profile.prompt_cache_key,
        "max_output_tokens": model_profile.max_output_tokens,
    }
    effort = model_profile.reasoning_effort or settings.openai_reasoning_effort
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def _responses_evidence_first_payload(
    *,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    model: str,
    profile=None,
) -> dict[str, Any]:
    model_profile = profile or get_active_model_profile()
    remote_policy = _remote_exposure_policy()
    user_payload = _evidence_first_user_payload(
        document_context=document_context,
        fields=fields,
        remote_policy=remote_policy,
    )
    content: list[dict[str, Any]] = [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}]
    model_inputs = model_profile.input or []
    if remote_policy.allow_page_images and ("image" in model_inputs or "vision" in model_inputs):
        content.extend(_responses_image_inputs(document_context))
    payload: dict[str, Any] = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": _evidence_first_system_prompt(document_context),
            },
            {"role": "user", "content": content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "eyex_evidence_collection",
                "strict": True,
                "schema": _evidence_candidate_response_schema(),
            }
        },
        "store": False,
        "prompt_cache_key": model_profile.prompt_cache_key,
        "max_output_tokens": model_profile.max_output_tokens,
    }
    effort = model_profile.reasoning_effort or settings.openai_reasoning_effort
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def _chat_completions_evidence_first_payload(
    *,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    model: str,
    profile=None,
) -> dict[str, Any]:
    """Build a /chat/completions payload that mirrors the Responses-API
    evidence-first contract. Used by `OpenAICompatibleChatProvider` so
    DeepSeek / OpenRouter / Moonshot / Qwen / Z.AI / Azure / Custom can
    actually participate in evidence collection.

    Two design invariants:

    1. The cacheable prefix is the system prompt + extraction rules +
       JSON schema descriptor. It is byte-stable across cases so DeepSeek's
       prompt cache (`api-docs.deepseek.com/guides/kv_cache`) can hit on
       repeat runs and bring the input-token cost down by ~90%.
    2. The per-case content (document_context + fields list) sits in the
       user message AFTER the cacheable prefix. The schema lives in the
       system message via a stringified description so it never changes
       between cases and never breaks the cache.
    """
    model_profile = profile or get_active_model_profile()
    remote_policy = _remote_exposure_policy()
    user_payload = _evidence_first_user_payload(
        document_context=document_context,
        fields=fields,
        remote_policy=remote_policy,
    )
    base_system = _evidence_first_system_prompt(document_context)
    schema_descriptor = json.dumps(
        _evidence_candidate_response_schema(), ensure_ascii=False, sort_keys=True
    )
    # The word "json" must appear in the system prompt for DeepSeek json_object
    # mode (per api-docs.deepseek.com/guides/json_mode). The descriptor below
    # also gives the model the exact target shape, which is the most reliable
    # way to get a usable response on chat-completions endpoints that do not
    # support strict json_schema mode.
    full_system = (
        base_system
        + "\n\n"
        + "Output one JSON object that strictly matches this schema:\n"
        + schema_descriptor
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": full_system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": model_profile.temperature,
        "max_tokens": model_profile.max_output_tokens,
    }


def _anthropic_evidence_first_payload(
    *,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    model: str,
    profile=None,
) -> dict[str, Any]:
    """Build an Anthropic Messages payload for evidence-first collection.

    Mirrors `_chat_completions_evidence_first_payload`. Two design
    invariants:

    1. Cacheable prefix discipline (system prompt + extraction rules +
       JSON schema descriptor) sits in the `system` field. Anthropic's
       prompt caching reads from `system` plus `messages` headers, so
       keeping the schema in `system` keeps it byte-stable across cases.
    2. Per-case content (document_context + fields list) sits in the
       single user message after the cacheable prefix.

    Anthropic does not support `response_format=json_object` directly;
    instead we put the schema descriptor inside the system prompt and
    request strict JSON-only output. Adapters parse the response with
    the same `_evidence_candidates_from_text` helper used for
    OpenAI-compatible chat.
    """
    model_profile = profile or get_active_model_profile()
    remote_policy = _remote_exposure_policy()
    user_payload = _evidence_first_user_payload(
        document_context=document_context,
        fields=fields,
        remote_policy=remote_policy,
    )
    base_system = _evidence_first_system_prompt(document_context)
    schema_descriptor = json.dumps(
        _evidence_candidate_response_schema(), ensure_ascii=False, sort_keys=True
    )
    full_system = (
        base_system
        + "\n\n"
        + "Output one JSON object that strictly matches this schema, "
        + "no prose, no markdown fences:\n"
        + schema_descriptor
    )
    return {
        "model": model,
        "max_tokens": model_profile.max_output_tokens,
        "temperature": model_profile.temperature,
        "system": full_system,
        "messages": [
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }


def _gemini_evidence_first_payload(
    *,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    model: str,
    profile=None,
) -> dict[str, Any]:
    """Build a Gemini generateContent payload for evidence-first collection.

    Uses Gemini's native structured-output capability:

    - `systemInstruction` carries the byte-stable prompt prefix so
      Gemini's context cache (Gemini API "Context caching") can hit
      across cases.
    - `responseMimeType=application/json` and `responseSchema` make
      Gemini emit one strict JSON object that matches the EYEX
      evidence-candidate schema. No fenced markdown to strip.

    Per-case content (document_context + fields list) sits in the user
    message AFTER the system instruction so the cacheable prefix is
    stable.
    """
    del model  # Gemini puts the model id in the URL path, not the payload.
    model_profile = profile or get_active_model_profile()
    remote_policy = _remote_exposure_policy()
    user_payload = _evidence_first_user_payload(
        document_context=document_context,
        fields=fields,
        remote_policy=remote_policy,
    )
    base_system = _evidence_first_system_prompt(document_context)
    return {
        "systemInstruction": {
            "parts": [{"text": base_system}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
            }
        ],
        "generationConfig": {
            "temperature": model_profile.temperature,
            "maxOutputTokens": model_profile.max_output_tokens,
            "responseMimeType": "application/json",
            "responseSchema": _gemini_response_schema(_evidence_candidate_response_schema()),
        },
    }


def _gemini_response_schema(json_schema: dict[str, Any]) -> dict[str, Any]:
    """Translate a JSON Schema fragment into Gemini's `responseSchema`
    dialect (a subset of OpenAPI 3.0). Drops fields Gemini does not
    accept, in particular `additionalProperties` and `enum` on null
    types. Recursive."""
    if not isinstance(json_schema, dict):
        return json_schema
    out: dict[str, Any] = {}
    for key, value in json_schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            # Gemini accepts a single type. Drop the null variant and
            # use `nullable: true` instead.
            non_null = [item for item in value if item != "null"]
            if non_null:
                out["type"] = non_null[0].upper() if isinstance(non_null[0], str) else non_null[0]
                if "null" in value:
                    out["nullable"] = True
            else:
                out["type"] = "STRING"
                out["nullable"] = True
            continue
        if key == "type" and isinstance(value, str):
            out["type"] = value.upper()
            continue
        if key in {"properties"} and isinstance(value, dict):
            out["properties"] = {
                prop_key: _gemini_response_schema(prop_value)
                for prop_key, prop_value in value.items()
            }
            continue
        if key == "items":
            out["items"] = _gemini_response_schema(value) if isinstance(value, dict) else value
            continue
        out[key] = value
    return out


def _chat_completions_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": f"{extraction_system_prompt(document_profile)} You must output JSON only.",
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": profile.temperature,
        "max_tokens": profile.max_output_tokens,
    }


def _anthropic_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "model": model,
        "max_tokens": profile.max_output_tokens,
        "temperature": profile.temperature,
        "system": f"{extraction_system_prompt(document_profile)} You must output one JSON object only.",
        "messages": [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
    }


def _gemini_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
    model: str,
    profile,
) -> dict[str, Any]:
    del model
    document_profile = _document_profile_for_ir(document_ir)
    user_payload = _llm_user_payload(document_ir=document_ir, group=group, fields=fields, blocks=blocks)
    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": f"{extraction_system_prompt(document_profile)} You must output one JSON object only."
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "temperature": profile.temperature,
            "maxOutputTokens": profile.max_output_tokens,
            "responseMimeType": "application/json",
        },
    }


def _evidence_first_system_prompt(document_context: DocumentContext) -> str:
    document_profile = _document_profile_for_context(document_context)
    base_prompt = extraction_system_prompt(document_profile)
    # Cacheable prefix invariants (E1-001):
    # - Byte-stable across cases: no document_id, no per-case content interpolated below.
    # - Field-level evidence_policy is the authoritative contract; this prompt
    #   describes how to read that contract uniformly across fields.
    # - The previous prompt told the model "missing means unknown", which
    #   conflicted with `implicit_negative_policy: section_complete_only` on
    #   chronic-disease and lifestyle fields. The conflict made the LLM choose
    #   safe-unknown for cases like `既往史：无特殊`. The new prompt promotes
    #   the per-field policy above the generic rule, so the same line
    #   produces a `0` candidate when (and only when) the schema field
    #   policy allows section-complete implicit negation.
    return "\n".join(
        [
            base_prompt,
            "",
            "你是医疗文档字段证据提取器，不是诊断助手。",
            "只收集候选证据，不要输出最终字段答案。",
            "",
            "证据绑定要求（每条候选必须满足）：",
            "- block_id 必须来自 document_context.pages[].blocks[].block_id。",
            "- evidence_text 必须从被引用 block 的 text 中逐字摘取，不可改写或拼接。",
            "- 每条候选必须包含 page、候选值、归一编码（normalized_code）。",
            "",
            "字段证据政策优先（这是 field.evidence_policy 的权威解读）：",
            "- 对每个字段，先读 fields[].evidence_policy.allowed_evidence_sources。",
            "  仅当某来源出现在该列表中时，才允许从该来源生成候选。",
            "- 对每个字段，先读 fields[].evidence_policy.implicit_negative_policy。",
            "  当且仅当其值为 section_complete_only 且 allowed_evidence_sources 包含",
            "  implicit_negative 时，下列模式构成有效的 normalized_code='0' 候选：",
            "    既往史：无特殊 / 既往史无特殊 / 既往史：未见异常 / 既往史无明显异常",
            "    个人史：无特殊 / 个人史无特殊",
            "    系统回顾：无特殊 / 病史：无特殊",
            "  这些模式覆盖该 section 内所有声明 section_complete_only 的字段；",
            "  source_type 标为 implicit_negative，evidence_text 摘取整段否定原文。",
            "  当 implicit_negative_policy 为 none 时，不得用 section-complete 模式生成候选。",
            "- 对每个字段，先读 fields[].evidence_policy.forbidden_document_regions",
            "  和 fields[].evidence_policy.forbidden_inference_sources。",
            "  来自这些区域或推理类型的证据必须在 forbidden_inference_flags 标记，",
            "  且不得作为 confirmed 候选。",
            "",
            "通用规则（在字段级政策不覆盖时适用）：",
            "- 缺少明确证据时不要猜测；返回空候选列表。",
            "- 禁止根据姓名、诊断名、科室名、药品、手术、常识推断患者身份、性别、年龄或病史。",
            "- 家属、配偶、父母、子女、孕产期、妊娠期描述属于 family_context；",
            "  其中提到的疾病、习惯不可作为患者本人的字段证据。",
            "  若错误纳入，必须在 forbidden_inference_flags 标记 family_context。",
            "- 否定句的范围只到本子句末尾（。；;\\n）。否认A、否认B 的下一句若叙述 C 阳性，",
            "  C 不受前句否定影响。",
            "- 当 OCR 文本与图像/版面不一致时，保留候选并将 visual_confirmed 设为 false；",
            "  不要尝试自行修复 OCR 错误。",
            "",
            "数值与编码要求：",
            "- normalized_code 必须出现在 fields[].allowed_codes 列表中；不允许新值。",
            "- 当字段类型为 enum 且 allowed_codes 含 '0' 与 '1' 时，否定证据用 '0'，肯定证据用 '1'。",
            "- 当无法在 allowed_codes 中匹配时，返回空候选（让本字段保持 unknown）。",
        ]
    )


def _evidence_first_user_payload(
    *,
    document_context: DocumentContext,
    fields: list[FieldDefinition],
    remote_policy: RemoteExposurePolicy | None = None,
) -> dict[str, Any]:
    document_profile = _document_profile_for_context(document_context)
    policy = remote_policy or _remote_exposure_policy()
    return {
        "task": "collect_field_evidence_candidates",
        "remote_context_mode": _remote_context_mode(policy),
        "remote_exposure_policy": policy.model_dump(),
        "rules": [
            "Return one valid JSON object only, with a top-level evidence_candidates array.",
            "Do not adjudicate final field values in this stage.",
            "Unknown or missing fields should simply have no candidate.",
            *extraction_rules(document_profile),
        ],
        "document_context": _remote_document_context_payload(document_context, policy),
        "fields": [_field_prompt_spec(field) for field in fields],
        "output_schema": _evidence_candidate_response_schema(),
    }


def _remote_exposure_policy() -> RemoteExposurePolicy:
    if _RUNTIME_EXPOSURE_POLICY_OVERRIDE is not None:
        return _RUNTIME_EXPOSURE_POLICY_OVERRIDE
    try:
        return load_extraction_schema().remote_exposure_policy
    except Exception:
        return RemoteExposurePolicy()


_RUNTIME_EXPOSURE_POLICY_OVERRIDE: RemoteExposurePolicy | None = None


def set_runtime_exposure_policy_override(policy: RemoteExposurePolicy | None) -> None:
    """Process-local override of the schema-derived RemoteExposurePolicy.

    Designed for the LLM-baseline bootstrap script and mock evaluation
    runs that need to send full DocumentContext to the remote model
    without modifying the live medical schema YAML. Production code paths
    (FastAPI request handlers, the case-processing worker pool) MUST NOT
    set this override; the per-schema policy in
    `config/extraction_schemas/<id>.yaml` is the only authoritative
    source for runtime behavior outside of evaluation tooling.

    Setting the override to None restores the schema-derived policy. The
    override is process-local and does not persist across restarts.

    See `docs/DECISIONS.md` 2026-05-01 "Remote medical extraction is
    safe-evidence-only by default" for the production policy that this
    override deliberately sidesteps in evaluation contexts only.
    """
    global _RUNTIME_EXPOSURE_POLICY_OVERRIDE
    _RUNTIME_EXPOSURE_POLICY_OVERRIDE = policy


def _requires_local_evidence_collection(policy: RemoteExposurePolicy) -> bool:
    return not (policy.allow_full_document_context and policy.allow_raw_block_text)


def _remote_context_mode(policy: RemoteExposurePolicy) -> str:
    if policy.allow_full_document_context and policy.allow_raw_block_text:
        return "full_document_context"
    if policy.allow_safe_evidence_candidates:
        return "safe_evidence_only"
    return "remote_disabled"


def _remote_document_context_payload(
    document_context: DocumentContext,
    policy: RemoteExposurePolicy,
) -> dict[str, Any]:
    if policy.allow_full_document_context and policy.allow_raw_block_text:
        return document_context_payload(document_context, include_images=policy.allow_page_images)
    return _safe_document_context_payload(document_context)


def _safe_document_context_payload(document_context: DocumentContext) -> dict[str, Any]:
    return {
        "document_id": document_context.document_id,
        "profile_id": document_context.profile_id,
        "context_version": document_context.metadata.get("context_version", "document-context-v1"),
        "remote_context_mode": "safe_evidence_only",
        "pages": [
            {
                "page": page.page,
                "width": page.width,
                "height": page.height,
                "dpi": page.dpi,
                "quality": page.quality,
                "block_count": len(page.blocks),
                "table_count": len(page.tables),
                "has_page_image": page.image is not None,
                "page_image_online_allowed": bool(page.image and page.image.online_allowed),
            }
            for page in document_context.pages
        ],
        "metadata": {
            "input_kind": document_context.metadata.get("input_kind"),
            "ocr_engine": document_context.metadata.get("ocr_engine"),
            "ocr_profile": document_context.metadata.get("ocr_profile"),
            "has_page_images": document_context.metadata.get("has_page_images", False),
            "page_images_online_allowed": document_context.metadata.get("page_images_online_allowed", False),
            "deidentification": document_context.metadata.get("deidentification", {}),
        },
    }


def _responses_image_inputs(document_context: DocumentContext) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for page in document_context.pages:
        image = page.image
        if image is None or not image.online_allowed or not image.path:
            continue
        image_url = _image_data_url(Path(image.path))
        if image_url:
            inputs.append({"type": "input_image", "image_url": image_url, "detail": "high"})
    return inputs


def _image_data_url(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except Exception:
        return None
    mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _llm_user_payload(
    *,
    document_ir: DocumentIR,
    group: FieldGroup,
    fields: list[FieldDefinition],
    blocks: list[DocumentIRBlock],
) -> dict[str, Any]:
    document_profile = _document_profile_for_ir(document_ir)
    return {
        "document_id": document_ir.document_id,
        "profile_id": document_ir.profile_id,
        "field_group": group.model_dump(),
        "rules": ["Return one valid JSON object only, with a top-level results array.", *extraction_rules(document_profile)],
        "output_schema": _response_schema(),
        "fields": [_field_prompt_spec(field) for field in fields],
        "evidence_packs": _field_evidence_pack_payload(fields, blocks),
    }


def _document_profile_for_context(document_context: DocumentContext):
    try:
        return load_document_profile(document_context.profile_id)
    except Exception:
        return None


def _document_profile_for_ir(document_ir: DocumentIR):
    try:
        return load_document_profile(document_ir.profile_id)
    except Exception:
        return None


def _field_prompt_spec(field: FieldDefinition) -> dict[str, Any]:
    return {
        "key": field.key,
        "label": field.label,
        "type": field.type,
        "allowed_codes": field.allowed_codes,
        "source_sections": field.source_sections,
        "excluded_sections": field.excluded_sections,
        "synonyms": field.synonyms,
        "negation_terms": field.negation_terms,
        "code_map": field.code_map,
        "extract_mode": field.extract_mode,
        "rule_patterns": [pattern.model_dump() for pattern in field.rule_patterns],
        "pre_redaction_derivations": [rule.model_dump() for rule in field.pre_redaction_derivations],
        "evidence_policy": field.evidence_policy.model_dump(),
    }


def _field_evidence_pack_payload(fields: list[FieldDefinition], blocks: list[DocumentIRBlock]) -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        payload[field.key] = [
            {
                "pack_hash": item.pack_hash,
                "rank": item.rank,
                "block_id": item.block_id,
                "text": item.text,
                "context_text": item.context_text,
                "page": item.page,
                "section_label": item.section_label,
                "document_kind": item.document_kind,
                "ocr_confidence": item.ocr_confidence,
                "score": item.score,
                "match_terms": item.match_terms,
                "score_reason": item.score_reason,
                "negated": item.negated,
                "uncertain": item.uncertain,
                "family_context": item.family_context,
                "token_estimate": item.token_estimate,
                "neighbor_block_ids": item.neighbor_block_ids,
            }
            for item in build_evidence_packs(None, field, blocks=blocks, group_budget=DEFAULT_PROVIDER_GROUP_BUDGET)
        ]
    return payload


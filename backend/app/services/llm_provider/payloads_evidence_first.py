from __future__ import annotations
import json
from typing import Any

from app.core.settings import settings
from app.domain.models import (
    DocumentContext, FieldDefinition, RemoteExposurePolicy,
)
from app.services.domain_profile import extraction_rules, extraction_system_prompt
from app.services.model_selection import get_active_model_profile
from .parsing import _evidence_candidate_response_schema
from .payloads import (
    _document_profile_for_context,
    _field_prompt_spec,
    _remote_context_mode,
    _remote_document_context_payload,
    _remote_exposure_policy,
    _responses_image_inputs,
)


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
            "evidence_text 必须为引用 block 的连续子串（最高优先级）：",
            "- evidence_text 必须是 document_context.pages[].blocks[] 中 block_id 与本候选",
            "  block_id 字段相等的那一条 block 的 text 字段中、字符级连续出现的一段子串。",
            "- 严禁改写、拼接、省略、调换语序、用同义词替换、补全省略号、合并多 block。",
            "  即使含义不变，只要在原始 block.text 中找不到逐字连续的同一段字符，就视为违规。",
            "- 当原文用顿号 / 等 / 及 等列举多项疾病、症状、习惯时，必须将整段否定或肯定的子句",
            "  原样摘取，不得只保留与本字段相关的那一项。",
            "    示例：原文为 “否认高血压病、糖尿病、冠心病等病史”。",
            "    无论本候选是 hypertension_history、diabetes_history 还是 heart_disease_history，",
            "    evidence_text 都必须是 “否认高血压病、糖尿病、冠心病等病史” 这一整段；",
            "    禁止改写为 “否认糖尿病”“否认高血压”“否认冠心病等” 之类的精简版本。",
            "- 当一条 block.text 跨多句时，可以截取其中任意连续的一段作为 evidence_text，",
            "  但截取的两端必须落在 block.text 的真实字符上，不得出现 block.text 中不存在的字符。",
            "- 同一 block 多次出现同一短语时，选最先出现的一处即可；不要为了”更短”而拼接。",
            "",
            "normalized_code 不是类型占位符（最高优先级）：",
            "- fields[].allowed_codes 中的字面量 'text' / 'integer' / 'float' / 'string' /",
            "  'number' / 'enum' 是字段值的”类型标记”，不是要逐字回填的合法值。",
            "- 当 allowed_codes 含 'text' 类占位符时，本字段是自由文本（如 hospital、备注）：",
            "  normalized_code 必须为患者文档里实际抽取到的字符串值（例如 “海安县中医院”、",
            "  “南京市第一人民医院”），且该字符串本身要在 evidence_text 里连续出现。",
            "  绝对不允许把 'text' / 'string' 这样的占位符当作 normalized_code。",
            "- 当 allowed_codes 含 'integer' / 'float' / 'number' 时，本字段是数值：",
            "  normalized_code 必须为实际数值的字符串形式（例如 '72'、'48.5'），",
            "  绝对不允许把 'integer' / 'float' / 'number' 当作 normalized_code 回填。",
            "- 当 allowed_codes 是真正的有限枚举（例如 ['0', '1', 'unknown']）时，照常",
            "  从中选取一个匹配项。",
            "- 当无法在文档中找到合法的实际值（自由文本字段找不到对应字符串、数值字段抽不到数字）时，",
            "  返回空候选让本字段保持 unknown；不要为了凑齐字段而回填占位符或编造值。",
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
            "  关键：当 既往史：无特殊（或同义模式）出现时，必须为该 section 涵盖的",
            "  每一个声明 section_complete_only 的字段都生成 normalized_code='0' 候选，",
            "  即使家族史/婚育史等其他 section 单独提及该疾病——患者本人的既往史已经",
            "  显式声明无特殊，家族史的提及只影响 family_context 标记，不影响患者本人",
            "  的 implicit_negative 命中。例如 既往史：无特殊 + 家族史：父亲有高血压病",
            "  应当为 hypertension_history、heart_disease_history、stroke_history、",
            "  tumor_history 等同 section 字段都返回 '0' 候选（来自既往史的 implicit_negative），",
            "  而不是因为家族史提到某病就让该字段返回 unknown。",
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

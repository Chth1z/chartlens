from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app.schemas.pipeline import FieldExtractionResult
from app.services.field_dictionary import FieldDictionary


def build_excel_workbook(
    case_id: str,
    dictionary: FieldDictionary,
    results: list[FieldExtractionResult],
) -> bytes:
    result_map = {result.field_key: result for result in results}
    workbook = Workbook()
    data_sheet = workbook.active
    data_sheet.title = "structured_data"

    headers = ["case_id", *dictionary.export_headers]
    data_sheet.append(headers)
    row = [case_id]
    for field in dictionary.fields:
        result = result_map.get(field.key)
        row.append(result.normalized_code if result else "unknown")
    data_sheet.append(row)

    audit_sheet = workbook.create_sheet("evidence_audit")
    audit_sheet.append(
        [
            "case_id",
            "field_key",
            "raw_value",
            "normalized_code",
            "confidence",
            "review_required",
            "page",
            "bbox",
            "evidence_text",
            "reasoning_summary",
            "error_code",
        ]
    )
    for result in results:
        audit_sheet.append(
            [
                case_id,
                result.field_key,
                result.raw_value,
                result.normalized_code,
                result.confidence,
                result.review_required,
                result.page,
                ",".join(str(value) for value in result.bbox),
                result.evidence_text,
                result.reasoning_summary,
                result.error_code,
            ]
        )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

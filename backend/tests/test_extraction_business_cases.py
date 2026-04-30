from app.core.config_loader import load_document_profile
from app.domain.models import DocumentIR, DocumentIRBlock
from app.services.deidentify import deidentify_document_ir
from app.services.pipeline import extract_document
from app.services.provider import ConservativeLocalProvider


def _ir(blocks: list[tuple[str, str]]) -> DocumentIR:
    return DocumentIR(
        document_id="case-fixture",
        profile_id="medical_inpatient_zh",
        source_filename="fixture.txt",
        blocks=[
            DocumentIRBlock(
                block_id=f"b{index}",
                page=1,
                reading_order=index,
                text=text,
                confidence=0.98,
                section_label=section,
            )
            for index, (section, text) in enumerate(blocks, start=1)
        ],
    )


def _extract(blocks: list[tuple[str, str]]):
    document_ir = deidentify_document_ir(_ir(blocks), load_document_profile())
    results = extract_document(document_ir, provider=ConservativeLocalProvider())
    return {result.field_key: result for result in results}


def test_not_mentioned_is_unknown_not_negative():
    results = _extract(
        [
            ("既往史", "既往史：否认高血压，否认糖尿病。"),
            ("个人史", "个人史：无烟酒不良嗜好。"),
        ]
    )

    assert results["hypertension_history"].normalized_code == "0"
    assert results["diabetes_history"].normalized_code == "0"
    assert results["smoking_history"].normalized_code == "0"
    assert results["drinking_history"].normalized_code == "0"
    assert results["hyperlipidemia_history"].normalized_code == "unknown"


def test_family_history_does_not_mark_patient_stroke_positive():
    results = _extract(
        [
            ("家族史", "家族史：其父有脑梗死病史。"),
            ("既往史", "既往史：否认高血压。"),
        ]
    )

    assert results["stroke_history"].normalized_code == "unknown"
    assert results["stroke_history"].error_code in {"NOT_MENTIONED", "NON_PATIENT_EXPERIENCER"}


def test_uncertain_condition_requires_review_and_unknown():
    results = _extract([("既往史", "既往史：糖尿病？待排，否认高血压。")])

    assert results["diabetes_history"].normalized_code == "unknown"
    assert results["diabetes_history"].review_required is True


def test_aneurysm_and_surgery_use_fact_then_code():
    results = _extract(
        [
            ("辅助检查", "CTA示前交通动脉瘤，考虑责任动脉瘤，蛛网膜下腔出血。"),
            ("手术记录", "先行脑室外引流术，后行前交通动脉瘤开颅夹闭术。"),
        ]
    )

    assert results["aneurysm_location"].normalized_code == "3"
    assert results["aneurysm_location"].facts
    assert results["surgery_method"].normalized_code == "开颅夹闭术"
    assert results["surgery_method"].facts


def test_gcs_derived_wfns_is_review_candidate():
    results = _extract([("体格检查", "体格检查：GCS 10分，可见局灶神经功能缺损。")])

    assert results["wfns_grade"].normalized_code == "4"
    assert results["wfns_grade"].status == "derived_candidate"
    assert results["wfns_grade"].review_required is True

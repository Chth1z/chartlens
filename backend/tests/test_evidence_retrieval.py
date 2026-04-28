from app.schemas.pipeline import OcrBlock
from app.services.evidence import retrieve_evidence
from app.services.field_dictionary import load_field_dictionary


def test_retrieve_evidence_prefers_matching_field_keywords():
    blocks = [
        OcrBlock(page=1, text="主诉：头痛伴恶心1天。", bbox=[0, 0, 100, 20], confidence=0.92),
        OcrBlock(page=1, text="既往史：高血压病史10年，否认脑卒中病史。", bbox=[0, 20, 100, 40], confidence=0.96),
        OcrBlock(page=2, text="出院情况：病情好转，予出院。", bbox=[0, 0, 100, 20], confidence=0.90),
    ]

    dictionary = load_field_dictionary()
    field = dictionary.by_key("hypertension_history")
    evidence = retrieve_evidence(field, blocks, limit=2)

    assert evidence[0].text == "既往史：高血压病史10年，否认脑卒中病史。"
    assert evidence[0].page == 1

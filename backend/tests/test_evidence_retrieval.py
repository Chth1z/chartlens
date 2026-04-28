from app.domain.clinical import OcrBlock
from app.domain.clinical import DocumentFragment
from app.application.evidence import retrieve_evidence
from app.infrastructure.config.field_dictionary import load_field_dictionary


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


def test_retrieve_evidence_excludes_configured_non_source_sections():
    blocks = [
        DocumentFragment(
            page=1,
            reading_order=1,
            text="家族史：父亲长期吸烟。",
            section_name="家族史",
            block_type="paragraph",
            confidence=0.96,
        ),
        DocumentFragment(
            page=1,
            reading_order=2,
            text="个人史：不吸烟，不饮酒。",
            section_name="个人史",
            block_type="paragraph",
            confidence=0.94,
        ),
    ]

    field = load_field_dictionary().by_key("smoking_history")
    evidence = retrieve_evidence(field, blocks, limit=5)

    assert [item.text for item in evidence] == ["个人史：不吸烟，不饮酒。"]


def test_gender_evidence_ignores_child_and_patient_description_substrings():
    field = load_field_dictionary().by_key("gender")
    blocks = [
        DocumentFragment(
            page=1,
            reading_order=1,
            text="婚姻史：已婚，配偶健康状况良好，家庭和睦，已有子女健康。",
            section_name="婚育史",
            block_type="paragraph",
            confidence=0.91,
        ),
        DocumentFragment(
            page=6,
            reading_order=2,
            text="病例摘要：患者：小红，老年女性患者，急性病程。",
            section_name="现病史",
            block_type="paragraph",
            confidence=0.89,
        ),
        DocumentFragment(
            page=1,
            reading_order=3,
            text="性别：女",
            section_name="基本信息",
            block_type="form_field",
            confidence=0.90,
        ),
    ]

    evidence = retrieve_evidence(field, blocks, limit=5)

    assert [item.text for item in evidence] == ["性别：女"]


def test_retrieve_evidence_finds_compound_no_smoking_drinking_phrase_for_both_fields():
    blocks = [
        DocumentFragment(
            page=4,
            reading_order=1,
            text="个人史：原籍生长，无外地长期居住史，无疫区、疫水接触史，无工业粉尘、毒物、放射性物质接触史，否认冶游史，无烟酒不良嗜好。",
            section_name="个人史",
            block_type="paragraph",
            confidence=0.94,
        ),
    ]
    dictionary = load_field_dictionary()

    smoking = retrieve_evidence(dictionary.by_key("smoking_history"), blocks)
    drinking = retrieve_evidence(dictionary.by_key("drinking_history"), blocks)

    assert smoking[0].text == blocks[0].text
    assert drinking[0].text == blocks[0].text

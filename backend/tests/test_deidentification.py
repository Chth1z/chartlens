from app.domain.deidentify import deidentify_text


def test_deidentify_text_replaces_direct_identifiers():
    text = "姓名：张三 住院号：0001234567 电话：13812345678 身份证：110101199003071234 地址：北京市海淀区"

    result = deidentify_text(text)

    assert "张三" not in result.redacted_text
    assert "13812345678" not in result.redacted_text
    assert "110101199003071234" not in result.redacted_text
    assert result.replacements["张三"] == "[姓名]"
    assert result.replacements["0001234567"] == "[住院号]"


def test_deidentify_text_keeps_clinical_evidence():
    text = "既往史：高血压病史10年，2型糖尿病8年，否认脑卒中病史。"

    result = deidentify_text(text)

    assert "高血压病史10年" in result.redacted_text
    assert "2型糖尿病8年" in result.redacted_text
    assert "否认脑卒中病史" in result.redacted_text

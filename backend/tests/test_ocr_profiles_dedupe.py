from __future__ import annotations

from app.services.ocr_engine import IntelligentOcrBlock
from app.services.ocr_engine.postprocessing import dedupe_ocr_blocks as _dedupe_ocr_blocks


def test_rapidocr_tile_fragments_stitch_into_complete_lines():
    blocks = [
        IntelligentOcrBlock(
            page=1,
            text="现病史：患者于1年前无明显诱因开始出现左下腹痛，呈",
            bbox=[706, 907, 1535, 945],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，",
            bbox=[949, 906, 1800, 948],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="既往史：否认“肝炎、肺结核”等传染病病史，否认“高",
            bbox=[699, 1306, 1535, 1349],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、",
            bbox=[946, 1311, 1795, 1347],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复",
            bbox=[630, 1364, 1535, 1406],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="手前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突",
            bbox=[945, 1363, 1800, 1408],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手",
            bbox=[631, 1422, 1535, 1464],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="，平卧位时消失，无不适症状，未到医院诊治。无外伤及于",
            bbox=[946, 1423, 1790, 1464],
            confidence=0.98,
        ),
        IntelligentOcrBlock(
            page=1,
            text="血、骨痛，无淋巴结肿大等。",
            bbox=[626, 2055, 1072, 2095],
            confidence=0.99,
        ),
        IntelligentOcrBlock(
            page=1,
            text="种大等。",
            bbox=[945, 2052, 1075, 2097],
            confidence=0.98,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "现病史：患者于1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，",
        "既往史：否认“肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、",
        "糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突",
        "出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手",
        "血、骨痛，无淋巴结肿大等。",
    ]
    assert deduped[0].bbox == [706.0, 906.0, 1800.0, 948.0]



def test_rapidocr_same_line_near_duplicates_collapse():
    blocks = [
        IntelligentOcrBlock(
            page=1,
            text="现病史",
            bbox=[168, 748, 278, 786],
            confidence=0.96,
        ),
        IntelligentOcrBlock(
            page=1,
            text="患者于一年前,外地出差回家自觉全身乏力、食欲不振,先以",
            bbox=[258, 747, 1015, 807],
            confidence=0.91,
        ),
        IntelligentOcrBlock(
            page=1,
            text="患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
            bbox=[287, 748, 1015, 807],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=1,
            text="红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、",
            bbox=[118, 1268, 991, 1321],
            confidence=0.94,
        ),
        IntelligentOcrBlock(
            page=1,
            text="红素51.3μmol/L，直接胆红素42.8μmol/1，ALT800U/L,HBsAg、HBeAg、",
            bbox=[117, 1267, 991, 1322],
            confidence=0.92,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "现病史",
        "患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
        "红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、",
    ]



def test_rapidocr_fuzzy_covered_line_alternatives_are_suppressed():
    blocks = [
        IntelligentOcrBlock(
            page=6,
            text="①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封",
            bbox=[619, 1899, 1535, 1941],
            confidence=0.99113,
        ),
        IntelligentOcrBlock(
            page=6,
            text="手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④",
            bbox=[617, 1954, 1535, 1998],
            confidence=0.96582,
        ),
        IntelligentOcrBlock(
            page=6,
            text="则行姑息性横结肠造口。",
            bbox=[618, 2012, 979, 2054],
            confidence=0.99752,
        ),
        IntelligentOcrBlock(
            page=6,
            text="直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann",
            bbox=[945, 1898, 1788, 1942],
            confidence=0.99194,
        ),
        IntelligentOcrBlock(
            page=6,
            text="造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者",
            bbox=[945, 1957, 1785, 1998],
            confidence=0.99187,
        ),
        IntelligentOcrBlock(
            page=6,
            text="。",
            bbox=[945, 2016, 984, 2062],
            confidence=0.99222,
        ),
        IntelligentOcrBlock(
            page=6,
            text="手术)；③先行横结肠造口，再二期行直肠癌根治性切除爪；",
            bbox=[620, 1972, 1500, 1999],
            confidence=0.93772,
        ),
        IntelligentOcrBlock(
            page=6,
            text="造口，再二期行直肠癌根治性切除爪；④肿瘤不能切除者",
            bbox=[945, 1972, 1782, 2000],
            confidence=0.95846,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann",
        "手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者",
        "则行姑息性横结肠造口。",
    ]



def test_rapidocr_fuzzy_overlap_stitches_without_repeating_middle_text():
    blocks = [
        IntelligentOcrBlock(
            page=6,
            text="肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤",
            bbox=[620, 1789, 1535, 1825],
            confidence=0.94384,
        ),
        IntelligentOcrBlock(
            page=6,
            text="解质及酸碱平衡素乱；④使用抗菌素；⑤低压洗肠：⑥积极",
            bbox=[945, 1783, 1788, 1830],
            confidence=0.91044,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤低压洗肠：⑥积极"
    ]



def test_rapidocr_tile_fragments_use_visual_order_when_engine_order_is_inverted():
    blocks = [
        IntelligentOcrBlock(
            page=2,
            text="，今予办理出院。]",
            bbox=[1344, 3139, 1762, 3282],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=2,
            text="换，加强营养支持治疗，患者恢复可，今予办",
            bbox=[620, 3143, 1535, 3283],
            confidence=0.94,
        ),
        IntelligentOcrBlock(
            page=2,
            text="出院情况：[患者一般情况尚可，生命体征平科",
            bbox=[622, 3282, 1535, 3428],
            confidence=0.94,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "换，加强营养支持治疗，患者恢复可，今予办",
        "，今予办理出院。]",
        "出院情况：[患者一般情况尚可，生命体征平科",
    ]



def test_rapidocr_does_not_reverse_stitch_visually_ordered_tile_fragments():
    blocks = [
        IntelligentOcrBlock(
            page=2,
            text="今予办理出院。]",
            bbox=[100, 900, 420, 940],
            confidence=0.93,
        ),
        IntelligentOcrBlock(
            page=2,
            text="换，加强营养支持治疗，患者恢复可，今予办理",
            bbox=[430, 900, 900, 940],
            confidence=0.94,
        ),
    ]

    deduped = _dedupe_ocr_blocks(blocks)

    assert [block.text for block in deduped] == [
        "今予办理出院。]",
        "换，加强营养支持治疗，患者恢复可，今予办理",
    ]



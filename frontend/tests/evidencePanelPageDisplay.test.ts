import { groupEvidenceByPage } from "../src/features/cases/EvidencePanel.js";
import type { DocumentFragment, EvidenceDisplayConfig } from "../src/shared/types/api";

const config: EvidenceDisplayConfig = {
  basic_field_labels: [],
  section_labels: [],
  inline_record_labels: [],
  section_tones: {},
  document_title_patterns: [],
  common_ocr_repairs: []
};

function fragment(page: number, readingOrder: number, text: string, bbox: number[] = []): DocumentFragment {
  return {
    page,
    reading_order: readingOrder,
    text,
    bbox,
    confidence: 0.92,
    section_name: "智能文档解析",
    block_type: "line",
    source_kind: "intelligent_document"
  };
}

function assertDeepEqual<T>(actual: T, expected: T, message: string) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${message}: expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`);
  }
}

const groups = groupEvidenceByPage(
  [fragment(5, 2, "第二段"), fragment(5, 1, "第一段"), fragment(7, 1, "第三段")],
  config
);

assertDeepEqual(
  groups.map((group) => group.page),
  [5, 7],
  "source page ids must be preserved for evidence matching"
);
assertDeepEqual(
  groups.map((group) => group.displayPage),
  [1, 2],
  "display pages must be contiguous even when source page ids are sparse"
);
assertDeepEqual(
  groups[0].items.map((item) => item.text),
  ["第一段第二段"],
  "items must still sort by reading order before rendering"
);

const geometryOrderGroups = groupEvidenceByPage(
  [
    fragment(2, 292, "，今予办理出院。]", [1344, 3139, 1762, 3282]),
    fragment(2, 295, "换，加强营养支持治疗，患者恢复可，今予办", [620, 3143, 1535, 3283]),
    fragment(2, 301, "出院情况：[患者一般情况尚可，生命体征平科", [622, 3282, 1535, 3428])
  ],
  { ...config, section_labels: ["出院情况"], inline_record_labels: ["出院情况"] }
);

assertDeepEqual(
  geometryOrderGroups[0].items.map((item) => item.text),
  ["换，加强营养支持治疗，患者恢复可，今予办", "，今予办理出院。]", "出院情况：[患者一般情况尚可，生命体征平科"],
  "bbox-backed OCR transcript items must use visual order and avoid reversed right-to-left synthesis when raw tile reading_order is inverted"
);

const stitchedGroups = groupEvidenceByPage(
  [
    fragment(1, 1, "现病史：患者于1年前无明显诱因开始出现左下腹痛，呈", [706, 907, 1535, 945]),
    fragment(1, 2, "1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，", [949, 906, 1800, 948]),
    fragment(1, 3, "既往史：否认“肝炎、肺结核”等传染病病史，否认“高", [699, 1306, 1535, 1349]),
    fragment(1, 4, "肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、", [946, 1311, 1795, 1347]),
    fragment(1, 5, "糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复", [630, 1364, 1535, 1406]),
    fragment(1, 6, "手前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突", [945, 1363, 1800, 1408]),
    fragment(1, 7, "出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手", [631, 1422, 1535, 1464]),
    fragment(1, 8, "，平卧位时消失，无不适症状，未到医院诊治。无外伤及于", [946, 1423, 1790, 1464])
  ],
  {
    ...config,
    section_labels: ["现病史", "既往史"],
    inline_record_labels: ["现病史", "既往史"]
  }
);

assertDeepEqual(
  stitchedGroups[0].items.map((item) => item.text),
  [
    "现病史：患者于1年前无明显诱因开始出现左下腹痛，呈胀痛，尚可忍受，",
    "既往史：否认“肝炎、肺结核”等传染病病史，否认“高血压病、冠心病、糖尿病”等病史。3年前出现右侧腹股沟区有一椭圆形的可复性肿块，站立时突出，可入同侧阴囊内，平卧位时消失，无不适症状，未到医院诊治。无外伤及手"
  ],
  "overlapping OCR tile fragments must stitch into complete same-line text before paragraph display"
);

const sectionAnchoredGroups = groupEvidenceByPage(
  [
    fragment(1, 1, "既往史：否认“肝炎、肺结核”等传染病病史，预防接种史不详。", [699, 1306, 1535, 1349]),
    fragment(1, 2, "系统回顾：", [696, 1539, 874, 1580]),
    fragment(1, 3, "头颅五官：无视力障碍，无耳聋、耳鸣、眩晕，无咽喉痛", [697, 1595, 1535, 1636]),
    fragment(1, 4, "血、骨痛，无淋巴结肿大等。", [626, 2055, 1072, 2095]),
    fragment(1, 5, "种大等。", [945, 2052, 1075, 2097]),
    fragment(1, 6, "1", [626, 2382, 645, 2417])
  ],
  {
    ...config,
    section_labels: ["既往史", "系统回顾"],
    inline_record_labels: ["既往史", "系统回顾", "头颅五官"]
  }
);

assertDeepEqual(
  sectionAnchoredGroups[0].items.map((item) => item.text),
  [
    "既往史：否认“肝炎、肺结核”等传染病病史，预防接种史不详。",
    "系统回顾：头颅五官：无视力障碍，无耳聋、耳鸣、眩晕，无咽喉痛",
    "血、骨痛，无淋巴结肿大等。"
  ],
  "standalone section anchors must split clinical sections and suppress fuzzy duplicate tile tails"
);

const nearDuplicateGroups = groupEvidenceByPage(
  [
    fragment(1, 1, "现病史", [168, 748, 278, 786]),
    fragment(1, 2, "患者于一年前,外地出差回家自觉全身乏力、食欲不振,先以", [258, 747, 1015, 807]),
    fragment(1, 3, "患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以", [287, 748, 1015, 807]),
    fragment(1, 4, "红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、", [118, 1268, 991, 1321]),
    fragment(1, 5, "红素51.3μmol/L，直接胆红素42.8μmol/1，ALT800U/L,HBsAg、HBeAg、", [117, 1267, 991, 1322]),
    fragment(1, 6, "-36-", [547, 1530, 600, 1556])
  ],
  {
    ...config,
    section_labels: ["现病史"],
    inline_record_labels: ["现病史"]
  }
);

assertDeepEqual(
  nearDuplicateGroups[0].items.map((item) => item.text),
  [
    "现病史：患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
    "红素51.3μmol/L，直接胆红素42.8μmol/l,ALT800U/L,HBsAg、HBeAg、"
  ],
  "near-duplicate OCR alternatives and footer page markers must not leak into the transcript"
);

const missingColonSectionGroups = groupEvidenceByPage(
  [
    fragment(1, 1, "主诉乏力、纳差、右上腹痛、腹胀一年，加重1周", [164, 699, 810, 762]),
    fragment(1, 2, "现病史", [168, 748, 278, 786]),
    fragment(1, 3, "患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以", [287, 748, 1015, 807]),
    fragment(1, 4, "既往史平素身体健康，3岁时曾患典型麻疹并发肺炎，5周治愈；4", [172, 1393, 979, 1443])
  ],
  {
    ...config,
    section_labels: ["主诉", "现病史", "既往史"],
    inline_record_labels: ["主诉", "现病史", "既往史"]
  }
);

assertDeepEqual(
  missingColonSectionGroups[0].items.map((item) => item.text),
  [
    "主诉：乏力、纳差、右上腹痛、腹胀一年，加重1周",
    "现病史：患者于一年前，外地出差回家自觉全身乏力、食欲不振，先以",
    "既往史：平素身体健康，3岁时曾患典型麻疹并发肺炎，5周治愈；4"
  ],
  "section headings with OCR-missing delimiters must render as separate clinical paragraphs"
);

const fuzzyCoveredLineGroups = groupEvidenceByPage(
  [
    fragment(6, 1, "①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封", [619, 1899, 1535, 1941]),
    fragment(6, 2, "手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④", [617, 1954, 1535, 1998]),
    fragment(6, 3, "则行姑息性横结肠造口。", [618, 2012, 979, 2054]),
    fragment(6, 30, "□。", [945, 2016, 984, 2062]),
    fragment(6, 4, "直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann", [945, 1898, 1788, 1942]),
    fragment(6, 5, "造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者", [945, 1957, 1785, 1998]),
    fragment(6, 6, "。", [945, 2016, 984, 2062]),
    fragment(6, 7, "手术)；③先行横结肠造口，再二期行直肠癌根治性切除爪；", [620, 1972, 1500, 1999]),
    fragment(6, 8, "造口，再二期行直肠癌根治性切除爪；④肿瘤不能切除者", [945, 1972, 1782, 2000])
  ],
  config
);

assertDeepEqual(
  fuzzyCoveredLineGroups[0].items.map((item) => item.text),
  [
    "①直肠癌根治术；②直肠癌切除，近端结肠造口，远端直肠封闭术（Hartmann手术）；③先行横结肠造口，再二期行直肠癌根治性切除术；④肿瘤不能切除者则行姑息性横结肠造口。"
  ],
  "same-line OCR alternatives covered by a longer stitched line must be suppressed even with one-character OCR drift"
);

const fuzzyOverlapGroups = groupEvidenceByPage(
  [
    fragment(6, 1, "肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤", [620, 1789, 1535, 1825]),
    fragment(6, 2, "解质及酸碱平衡素乱；④使用抗菌素；⑤低压洗肠：⑥积极", [945, 1783, 1788, 1830])
  ],
  config
);

assertDeepEqual(
  fuzzyOverlapGroups[0].items.map((item) => item.text),
  ["肠减压；③纠正水电解质及酸碱平衡紊乱；④使用抗菌素；⑤低压洗肠：⑥积极"],
  "same-line OCR fragments must stitch across fuzzy suffix-prefix overlap instead of duplicating the overlap"
);

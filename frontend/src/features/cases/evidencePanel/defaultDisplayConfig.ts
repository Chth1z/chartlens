import type { EvidenceDisplayConfig } from "../../../shared/types/api";

const BASIC_FIELD_LABELS = [
  "姓名",
  "性别",
  "年龄",
  "住址",
  "民族",
  "婚姻",
  "职业",
  "工作单位",
  "联系人",
  "病史陈述人",
  "可靠程度",
  "入院日期",
  "出院日期",
  "入院时间",
  "出院时间",
  "记录日期",
  "住院号",
  "科室"
];

const SECTION_LABELS = [
  "主诉",
  "现病史",
  "既往史",
  "系统回顾",
  "个人史",
  "婚育史",
  "月经史",
  "婚姻史",
  "家族史",
  "体格检查",
  "辅助检查",
  "专科检查",
  "诊疗经过",
  "入院情况",
  "出院情况",
  "出院记录",
  "出院医嘱",
  "手术记录",
  "病例摘要",
  "初步诊断",
  "门诊诊断",
  "入院诊断",
  "出院诊断"
];

const INLINE_RECORD_LABELS = [
  ...SECTION_LABELS,
  "生命体征",
  "一般状况",
  "皮肤黏膜",
  "淋巴结",
  "头颅及其器官",
  "头颅",
  "眼",
  "耳",
  "鼻",
  "口腔",
  "颈部",
  "胸部",
  "肺部",
  "心脏",
  "腹部",
  "肛门及外生殖器",
  "脊柱四肢",
  "神经系统",
  "专科情况",
  "辅助检查结果",
  "初步诊断",
  "诊断依据",
  "鉴别诊断",
  "诊疗计划"
];

export const DEFAULT_EVIDENCE_DISPLAY_CONFIG: EvidenceDisplayConfig = {
  basic_field_labels: BASIC_FIELD_LABELS,
  section_labels: SECTION_LABELS,
  inline_record_labels: INLINE_RECORD_LABELS,
  section_tones: {
    basic: ["基本", "首页", "信息", "姓名", "年龄", "性别"],
    present: ["主诉", "现病", "入院"],
    history: ["既往", "系统回顾", "个人", "家族", "婚育", "月经", "病史"],
    diagnosis: ["诊断", "出院", "医嘱"],
    exam: ["检验", "检查", "影像", "化验", "体格", "专科", "辅助"]
  },
  document_title_patterns: ["病历", "病案", "入院记录", "出院记录", "病程记录", "手术记录", "首页"],
  common_ocr_repairs: [
    { pattern: "(BP\\s*[：:]?\\s*\\d+\\s*\\/\\s*\\d+\\s*mmHg)\\s*般状况", replacement: "$1 一般状况" },
    { pattern: "(^|[。；;！？\\s])般状况(?=\\s*[：:])", replacement: "$1一般状况" }
  ]
};

export function mergeEvidenceDisplayConfig(config?: EvidenceDisplayConfig): EvidenceDisplayConfig {
  return {
    basic_field_labels: config?.basic_field_labels?.length
      ? config.basic_field_labels
      : DEFAULT_EVIDENCE_DISPLAY_CONFIG.basic_field_labels,
    section_labels: mergeUniqueText(config?.section_labels, DEFAULT_EVIDENCE_DISPLAY_CONFIG.section_labels),
    inline_record_labels: mergeUniqueText(config?.inline_record_labels, DEFAULT_EVIDENCE_DISPLAY_CONFIG.inline_record_labels),
    section_tones: mergeSectionTones(config?.section_tones),
    document_title_patterns: config?.document_title_patterns?.length
      ? config.document_title_patterns
      : DEFAULT_EVIDENCE_DISPLAY_CONFIG.document_title_patterns,
    common_ocr_repairs: config?.common_ocr_repairs?.length
      ? config.common_ocr_repairs
      : DEFAULT_EVIDENCE_DISPLAY_CONFIG.common_ocr_repairs
  };
}

function mergeUniqueText(primary: string[] | undefined, fallback: string[]) {
  return Array.from(new Set([...(primary ?? []), ...fallback].map((item) => item.trim()).filter(Boolean)));
}

function mergeSectionTones(configTones?: Record<string, string[]>) {
  const tones: Record<string, string[]> = { ...DEFAULT_EVIDENCE_DISPLAY_CONFIG.section_tones };
  Object.entries(configTones ?? {}).forEach(([tone, terms]) => {
    tones[tone] = mergeUniqueText(terms, tones[tone] ?? []);
  });
  return tones;
}

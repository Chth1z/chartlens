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

function fragment(page: number, readingOrder: number, text: string): DocumentFragment {
  return {
    page,
    reading_order: readingOrder,
    text,
    bbox: [],
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

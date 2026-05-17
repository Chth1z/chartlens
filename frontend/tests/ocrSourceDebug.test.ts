import {
  groupSourceEvidenceByPage,
  isSourceOverlayBlankClickClassName,
  sourceEvidenceImageStateKey
} from "../src/features/cases/EvidencePanel.js";
import type { DocumentFragment, EvidenceDisplayConfig } from "../src/shared/types/api";
// @ts-expect-error The lightweight frontend test runner executes in Node, but tsconfig intentionally omits Node types.
import { readFileSync } from "node:fs";

const config: EvidenceDisplayConfig = {
  basic_field_labels: [],
  section_labels: ["系统回顾"],
  inline_record_labels: ["系统回顾"],
  section_tones: {},
  document_title_patterns: [],
  common_ocr_repairs: []
};

function fragment(text: string, bbox: number[], readingOrder: number, confidence = 0.92): DocumentFragment {
  return {
    page: 6,
    reading_order: readingOrder,
    text,
    bbox,
    confidence,
    section_name: "智能文档解析",
    block_type: "line",
    source_kind: "intelligent_document"
  };
}

function dpiFragment(text: string, bbox: number[], readingOrder: number, renderDpi: number): DocumentFragment {
  return {
    ...fragment(text, bbox, readingOrder),
    render_dpi: renderDpi
  };
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const groups = groupSourceEvidenceByPage(
  [
    fragment("", [100, 2200, 900, 2234], 1),
    fragment("系统回顾：", [102, 320, 260, 360], 2),
    fragment("头颅五官：无视力障碍，无耳聋、耳鸣、眩晕", [102, 376, 930, 418], 3),
    fragment("头颅五官：无视力障碍，无耳聋、耳鸣、眩晕", [104, 377, 932, 419], 4),
    fragment("贴边文本", [1535, 500, 1800, 540], 5),
    fragment("低置信文本", [102, 562, 360, 602], 6, 0.58),
    fragment("1", [102, 2380, 130, 2418], 7)
  ],
  config
);

const group = groups[0];
assert(group, "source OCR page should be grouped");

const renderedText = group.items.map((item) => item.text);
assert(!renderedText.includes(""), "empty OCR boxes must not be rendered in source overlay");
assert(!renderedText.includes("1"), "footer page marker must not be rendered in source overlay");
assert(
  renderedText.filter((text) => text.includes("头颅五官")).length === 1,
  "near-duplicate same-line OCR alternatives must collapse before source overlay rendering"
);

assert(group.sourceDebug?.hiddenEmptyTextCount === 1, "source debug must count hidden empty OCR boxes");
assert(group.sourceDebug?.duplicateTextCount === 1, "source debug must count duplicate OCR text candidates");
assert(group.sourceDebug?.edgeTouchingBoxCount === 1, "source debug must count boxes touching tile/page edges");
assert(group.sourceDebug?.lowConfidenceCount === 1, "source debug must count low-confidence OCR lines");
assert(
  group.sourceDebug?.recommendedActions.includes("检查 crop/tile padding 或增大 tile_overlap"),
  "source debug must recommend crop/tile tuning for edge-touching boxes"
);

const distantHeaderGroups = groupSourceEvidenceByPage(
  [
    fragment("姓名：王××", [30, 72, 174, 104], 1),
    fragment("现住址：", [430, 72, 548, 104], 2),
    fragment("性别：男性", [30, 112, 146, 144], 3),
    fragment("入院日期：", [430, 112, 556, 144], 4)
  ],
  { ...config, basic_field_labels: ["姓名", "现住址", "性别", "入院日期"] }
);
const headerGroup = distantHeaderGroups[0];
assert(headerGroup, "source OCR header fields should be grouped");
assert(
  headerGroup.items.every((item) => !(item.text.includes("姓名") && item.text.includes("现住址"))),
  "source overlay must not stitch distant same-line header fields into one bbox"
);
const nameItem = headerGroup.items.find((item) => item.text.includes("姓名"));
const addressItem = headerGroup.items.find((item) => item.text.includes("现住址"));
assert(nameItem && addressItem, "distant header fields should remain individually selectable");
assert(nameItem.bbox[2] < 220, "name field bbox must not expand across the header row");
assert(addressItem.bbox[0] > 360, "address field bbox must keep its original column position");

const crossLabelCandidateGroups = groupSourceEvidenceByPage(
  [
    fragment("姓名：王××", [30, 72, 174, 104], 1),
    fragment("姓名：王×× 现住址：", [30, 72, 548, 104], 2),
    fragment("现住址：", [430, 72, 548, 104], 3)
  ],
  { ...config, basic_field_labels: ["姓名", "现住址"] }
);
const crossLabelGroup = crossLabelCandidateGroups[0];
assert(crossLabelGroup, "source OCR cross-label candidates should be grouped");
assert(
  !crossLabelGroup.items.some((item) => item.text.includes("姓名") && item.text.includes("现住址")),
  "source overlay must suppress multi-field raw candidates when individual field boxes exist"
);

const reversedTileGroups = groupSourceEvidenceByPage(
  [
    fragment("，今予办理出院。]", [1344, 3139, 1762, 3282], 292),
    fragment("换，加强营养支持治疗，患者恢复可，今予办", [620, 3143, 1535, 3283], 295),
    fragment("出院情况：[患者一般情况尚可，生命体征平科", [622, 3282, 1535, 3428], 301)
  ],
  config
);
const reversedTileGroup = reversedTileGroups[0];
assert(reversedTileGroup, "source OCR tile fragments should be grouped");
const reversedTileText = reversedTileGroup.items.map((item) => item.text);
assert(
  reversedTileText[0] === "换，加强营养支持治疗，患者恢复可，今予办",
  "same-line OCR tile fragments must be rendered left-to-right by bbox, not by raw engine reading_order"
);
assert(
  !reversedTileText.some((text) => text.startsWith("，今予办理出院。]换")),
  "source OCR cleanup must not synthesize reversed right-to-left line text"
);
assert(
  reversedTileText.at(-1)?.startsWith("出院情况"),
  "next visual line must remain after the same-line tile fragments"
);

const reverseOverlapGroups = groupSourceEvidenceByPage(
  [
    fragment("今予办理出院。]", [100, 900, 420, 940], 1),
    fragment("换，加强营养支持治疗，患者恢复可，今予办理", [430, 900, 900, 940], 2)
  ],
  config
);
const reverseOverlapText = reverseOverlapGroups[0]?.items.map((item) => item.text) ?? [];
assert(
  reverseOverlapText.length === 2 && reverseOverlapText[0] === "今予办理出院。]",
  "source OCR cleanup must not use reverse text overlap to join visually left-to-right boxes"
);

const metadataNoiseGroups = groupSourceEvidenceByPage(
  [
    fragment("-31-", [], 1),
    fragment("pp_structure_v3:0038:9f07ff85", [], 2),
    fragment("canonical_selected", [], 3),
    fragment("XXXX医院", [30, 72, 174, 104], 4),
    fragment("个人史", [30, 112, 146, 144], 5)
  ],
  config
);
const metadataNoiseGroup = metadataNoiseGroups[0];
assert(metadataNoiseGroup, "source OCR metadata noise page should be grouped");
const metadataNoiseText = metadataNoiseGroup.items.map((item) => item.text);
assert(!metadataNoiseText.includes("-31-"), "page markers must not render as source OCR text");
assert(!metadataNoiseText.some((text) => text.startsWith("pp_structure_v3:")), "internal candidate ids must not render as source OCR text");
assert(!metadataNoiseText.includes("canonical_selected"), "merge/debug flags must not render as source OCR text");
assert(metadataNoiseText.includes("XXXX医院"), "real OCR text must remain after filtering metadata noise");
assert(metadataNoiseText.includes("个人史"), "real section headings must remain after filtering metadata noise");

const originalStateKey = sourceEvidenceImageStateKey(
  groupSourceEvidenceByPage([dpiFragment("现病史：腹痛", [100, 200, 520, 240], 1, 300)], config)
);
const reprocessedStateKey = sourceEvidenceImageStateKey(
  groupSourceEvidenceByPage([dpiFragment("现病史：腹痛", [100, 200, 694, 320], 1, 400)], config)
);
assert(
  originalStateKey !== reprocessedStateKey,
  "source image metrics and failed preview state must reset when a case is reprocessed with new OCR DPI or bboxes"
);

const styles = readFileSync("src/styles.css", "utf-8");
const ocrImageBoxRule = styles.match(/\.ocr-image-box\s*\{(?<body>[\s\S]*?)\n\}/)?.groups?.body ?? "";
assert(
  ocrImageBoxRule.includes("background: transparent"),
  "OCR source overlay boxes must be outline-only by default so they do not obscure the original text"
);

const meaninglessOverlayGroups = groupSourceEvidenceByPage(
  [
    fragment("外科情况：腹胀，腹式呼吸存在，未见胃肠型及蠕动波", [60, 100, 720, 135], 1),
    fragment("右侧腹股沟区椭圆形肿块大小3×5cm，质软，无触痛", [60, 145, 680, 180], 2),
    fragment("4", [0, 215, 760, 330], 3),
    fragment("5", [470, 210, 980, 390], 4)
  ],
  config
);
const overlayGroup = meaninglessOverlayGroups[0];
assert(overlayGroup, "source OCR page with meaningless overlays should be grouped");
const overlayTexts = overlayGroup.items.map((item) => item.text);
assert(!overlayTexts.includes("4"), "single-character large overlay boxes must not render over source text");
assert(!overlayTexts.includes("5"), "large OCR noise boxes must not render even when they are not page footers");
assert(
  ((overlayGroup.sourceDebug as { suppressedMeaninglessBoxCount?: number } | undefined)?.suppressedMeaninglessBoxCount ?? 0) === 2,
  "source debug must count suppressed meaningless OCR overlay boxes"
);

const activeCopyTextRule =
  styles.match(/\.ocr-image-box\.active\s+\.ocr-copy-text,\s*\n\.ocr-image-box\[aria-current="true"\]\s+\.ocr-copy-text\s*\{(?<body>[\s\S]*?)\n\}/)?.groups
    ?.body ?? "";
assert(activeCopyTextRule.includes("color: var(--text-strong)"), "selected OCR source boxes must render their text inside the box");
assert(activeCopyTextRule.includes("-webkit-text-fill-color: currentColor"), "selected OCR text must be selectable and copyable in WebKit browsers");
assert(activeCopyTextRule.includes("pointer-events: auto"), "selected OCR text must accept direct text selection inside the box");

assert(isSourceOverlayBlankClickClassName("ocr-source-image"), "clicking the source image should clear the selected OCR box");
assert(isSourceOverlayBlankClickClassName("ocr-image-layer"), "clicking blank overlay space should clear the selected OCR box");
assert(!isSourceOverlayBlankClickClassName("ocr-image-box active"), "clicking an OCR box must keep that box selected");
assert(!isSourceOverlayBlankClickClassName("ocr-copy-text"), "selecting text inside an active OCR box must not clear the selection");

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  groupSourceEvidenceByPage,
  isSourceOverlayBlankClickClassName,
  sourceEvidenceImageStateKey
} from "../src/features/cases/EvidencePanel";
import type { DocumentFragment, EvidenceDisplayConfig } from "../src/shared/types/api";

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

describe("ocrSourceDebug", () => {
  it("should filter empty OCR boxes and footer page markers from source overlay", () => {
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
    expect(group).toBeDefined();

    const renderedText = group.items.map((item) => item.text);
    expect(renderedText).not.toContain("");
    expect(renderedText).not.toContain("1");
    expect(renderedText.filter((text) => text.includes("头颅五官")).length).toBe(1);
  });

  it("source debug must count hidden empty OCR boxes", () => {
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
    expect(group.sourceDebug?.hiddenEmptyTextCount).toBe(1);
    expect(group.sourceDebug?.duplicateTextCount).toBe(1);
    expect(group.sourceDebug?.edgeTouchingBoxCount).toBe(1);
    expect(group.sourceDebug?.lowConfidenceCount).toBe(1);
    expect(group.sourceDebug?.recommendedActions).toContain("检查 crop/tile padding 或增大 tile_overlap");
  });

  it("source overlay must not stitch distant same-line header fields into one bbox", () => {
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
    expect(headerGroup).toBeDefined();
    expect(headerGroup.items.every((item) => !(item.text.includes("姓名") && item.text.includes("现住址")))).toBe(true);

    const nameItem = headerGroup.items.find((item) => item.text.includes("姓名"));
    const addressItem = headerGroup.items.find((item) => item.text.includes("现住址"));
    expect(nameItem).toBeDefined();
    expect(addressItem).toBeDefined();
    expect(nameItem!.bbox[2]).toBeLessThan(220);
    expect(addressItem!.bbox[0]).toBeGreaterThan(360);
  });

  it("source overlay must suppress multi-field raw candidates when individual field boxes exist", () => {
    const crossLabelCandidateGroups = groupSourceEvidenceByPage(
      [
        fragment("姓名：王××", [30, 72, 174, 104], 1),
        fragment("姓名：王×× 现住址：", [30, 72, 548, 104], 2),
        fragment("现住址：", [430, 72, 548, 104], 3)
      ],
      { ...config, basic_field_labels: ["姓名", "现住址"] }
    );
    const crossLabelGroup = crossLabelCandidateGroups[0];
    expect(crossLabelGroup).toBeDefined();
    expect(crossLabelGroup.items.some((item) => item.text.includes("姓名") && item.text.includes("现住址"))).toBe(false);
  });

  it("same-line OCR tile fragments must be rendered left-to-right by bbox", () => {
    const reversedTileGroups = groupSourceEvidenceByPage(
      [
        fragment("，今予办理出院。]", [1344, 3139, 1762, 3282], 292),
        fragment("换，加强营养支持治疗，患者恢复可，今予办", [620, 3143, 1535, 3283], 295),
        fragment("出院情况：[患者一般情况尚可，生命体征平科", [622, 3282, 1535, 3428], 301)
      ],
      config
    );
    const reversedTileGroup = reversedTileGroups[0];
    expect(reversedTileGroup).toBeDefined();
    const reversedTileText = reversedTileGroup.items.map((item) => item.text);
    expect(reversedTileText[0]).toBe("换，加强营养支持治疗，患者恢复可，今予办");
    expect(reversedTileText.some((text) => text.startsWith("，今予办理出院。]换"))).toBe(false);
    expect(reversedTileText.at(-1)?.startsWith("出院情况")).toBe(true);
  });

  it("source OCR cleanup must not use reverse text overlap to join visually left-to-right boxes", () => {
    const reverseOverlapGroups = groupSourceEvidenceByPage(
      [
        fragment("今予办理出院。]", [100, 900, 420, 940], 1),
        fragment("换，加强营养支持治疗，患者恢复可，今予办理", [430, 900, 900, 940], 2)
      ],
      config
    );
    const reverseOverlapText = reverseOverlapGroups[0]?.items.map((item) => item.text) ?? [];
    expect(reverseOverlapText.length).toBe(2);
    expect(reverseOverlapText[0]).toBe("今予办理出院。]");
  });

  it("metadata noise must be filtered from source OCR text", () => {
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
    expect(metadataNoiseGroup).toBeDefined();
    const metadataNoiseText = metadataNoiseGroup.items.map((item) => item.text);
    expect(metadataNoiseText).not.toContain("-31-");
    expect(metadataNoiseText.some((text) => text.startsWith("pp_structure_v3:"))).toBe(false);
    expect(metadataNoiseText).not.toContain("canonical_selected");
    expect(metadataNoiseText).toContain("XXXX医院");
    expect(metadataNoiseText).toContain("个人史");
  });

  it("source image state key must reset when case is reprocessed with new OCR DPI", () => {
    const originalStateKey = sourceEvidenceImageStateKey(
      groupSourceEvidenceByPage([dpiFragment("现病史：腹痛", [100, 200, 520, 240], 1, 300)], config)
    );
    const reprocessedStateKey = sourceEvidenceImageStateKey(
      groupSourceEvidenceByPage([dpiFragment("现病史：腹痛", [100, 200, 694, 320], 1, 400)], config)
    );
    expect(originalStateKey).not.toBe(reprocessedStateKey);
  });

  it("OCR source overlay boxes must be outline-only by default", () => {
    const styles = readFileSync("src/styles/document.css", "utf-8");
    const ocrImageBoxRule = styles.match(/\.ocr-image-box\s*\{(?<body>[\s\S]*?)\n\}/)?.groups?.body ?? "";
    expect(ocrImageBoxRule).toContain("background: transparent");
  });

  it("single-character large overlay boxes must not render over source text", () => {
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
    expect(overlayGroup).toBeDefined();
    const overlayTexts = overlayGroup.items.map((item) => item.text);
    expect(overlayTexts).not.toContain("4");
    expect(overlayTexts).not.toContain("5");
    expect(
      ((overlayGroup.sourceDebug as { suppressedMeaninglessBoxCount?: number } | undefined)?.suppressedMeaninglessBoxCount ?? 0)
    ).toBe(2);
  });

  it("selected OCR source boxes must render their text inside the box", () => {
    const styles = readFileSync("src/styles/document.css", "utf-8");
    const activeCopyTextRule =
      styles.match(/\.ocr-image-box\.active\s+\.ocr-copy-text,\s*\n\.ocr-image-box\[aria-current="true"\]\s+\.ocr-copy-text\s*\{(?<body>[\s\S]*?)\n\}/)?.groups
        ?.body ?? "";
    expect(activeCopyTextRule).toContain("color: var(--text-strong)");
    expect(activeCopyTextRule).toContain("-webkit-text-fill-color: currentColor");
    expect(activeCopyTextRule).toContain("pointer-events: auto");
  });

  it("clicking the source image should clear the selected OCR box", () => {
    expect(isSourceOverlayBlankClickClassName("ocr-source-image")).toBe(true);
    expect(isSourceOverlayBlankClickClassName("ocr-image-layer")).toBe(true);
    expect(isSourceOverlayBlankClickClassName("ocr-image-box active")).toBe(false);
    expect(isSourceOverlayBlankClickClassName("ocr-copy-text")).toBe(false);
  });
});

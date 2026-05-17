import type { EvidenceDisplayConfig } from "../../../shared/types/api";
import {
  bboxIntersectionArea,
  compareByPageAndPosition,
  mergeBboxes,
  medianPositive,
  normalizeBbox,
  overlapLength,
  roundConfidence
} from "./evidenceGeometry.js";
import {
  basicFieldLabelCount,
  basicFieldLabelsInText,
  comparableLineSignature,
  fieldLabelsInText,
  isInternalOcrMetadataText,
  isLikelyPageMarkerText,
  isMeaninglessOverlayText,
  isStrayStandaloneSymbolText,
  mergeSameLineText,
  normalizeEvidence
} from "./evidenceText.js";
import type { BboxRect, OcrLineLike, SourceEvidenceItem, SourcePageDebug } from "./types";

export function prepareSourceItems(items: SourceEvidenceItem[], config: EvidenceDisplayConfig) {
  return prepareSourceItemsWithDebug(items, config).items;
}

export function prepareSourceItemsWithDebug(
  items: SourceEvidenceItem[],
  config: EvidenceDisplayConfig
): {
  items: SourceEvidenceItem[];
  suppressedMeaninglessBoxCount: number;
} {
  const visibleItems = items.filter(isUsableSourceItem);
  const removedBeforeOverlay = items.length - visibleItems.length;
  const cleanedOverlayBoxes = removeMeaninglessLargeOverlayBoxes(
    removeStrayStandaloneSymbols(
      removeLikelyPageMarkers(
        removeCrossLabelHeaderCandidates(stitchOverlappingTextLineFragments(visibleItems), config)
      )
    )
  );
  const cleanedItems = repairOverlappingFormFields(removeDuplicateBasicInfoFragments(cleanedOverlayBoxes.items, config));
  return {
    items: renumberSourceItemsByVisualOrder(cleanedItems),
    suppressedMeaninglessBoxCount: cleanedOverlayBoxes.removedCount + removedBeforeOverlay
  };
}

function isUsableSourceItem(item: SourceEvidenceItem) {
  const normalized = normalizeEvidence(item.text);
  if (normalized.length === 0) return false;
  if (isLikelyPageMarkerText(item.text.trim())) return false;
  if (isInternalOcrMetadataText(item.text)) return false;
  return true;
}

function removeMeaninglessLargeOverlayBoxes<T extends OcrLineLike>(items: T[]): { items: T[]; removedCount: number } {
  const pageItems = new Map<number, T[]>();
  items.forEach((item) => {
    const list = pageItems.get(item.page) ?? [];
    list.push(item);
    pageItems.set(item.page, list);
  });
  const filtered = items.filter((item) => !isMeaninglessLargeOverlayBox(item, pageItems.get(item.page) ?? items));
  return {
    items: filtered,
    removedCount: items.length - filtered.length
  };
}

function isMeaninglessLargeOverlayBox(item: OcrLineLike, pageItems: OcrLineLike[]) {
  const text = item.text.trim();
  if (!isMeaninglessOverlayText(text)) return false;
  const rect = normalizeBbox(item.bbox);
  const pageRect = normalizeBbox(mergeBboxes(pageItems.map((candidate) => candidate.bbox)));
  if (!rect || !pageRect) return false;
  const pageWidth = Math.max(1, pageRect.x2 - pageRect.x1);
  const pageHeight = Math.max(1, pageRect.y2 - pageRect.y1);
  const width = rect.x2 - rect.x1;
  const height = rect.y2 - rect.y1;
  const areaRatio = (width * height) / Math.max(1, pageWidth * pageHeight);
  const medianHeight = medianPositive(
    pageItems
      .map((candidate) => normalizeBbox(candidate.bbox))
      .filter((candidate): candidate is BboxRect => candidate !== null)
      .map((candidate) => candidate.y2 - candidate.y1)
  );
  return (
    width / pageWidth >= 0.32 ||
    height / pageHeight >= 0.08 ||
    areaRatio >= 0.02 ||
    height >= Math.max(36, medianHeight * 2.6)
  );
}

function removeLikelyPageMarkers<T extends OcrLineLike>(items: T[]): T[] {
  const pageExtents = new Map<number, { minY: number; maxY: number }>();
  items.forEach((item) => {
    const rect = normalizeBbox(item.bbox);
    if (!rect) return;
    const current = pageExtents.get(item.page);
    pageExtents.set(item.page, {
      minY: Math.min(current?.minY ?? rect.y1, rect.y1),
      maxY: Math.max(current?.maxY ?? rect.y2, rect.y2)
    });
  });
  return items.filter((item) => {
    const text = item.text.trim();
    if (!isLikelyPageMarkerText(text)) return true;
    const rect = normalizeBbox(item.bbox);
    const extent = pageExtents.get(item.page);
    if (!rect || !extent) return true;
    const pageSpan = Math.max(1, extent.maxY - extent.minY);
    const footerBand = Math.max(80, pageSpan * 0.05);
    return rect.y1 < extent.maxY - footerBand;
  });
}

function removeStrayStandaloneSymbols<T extends OcrLineLike>(items: T[]): T[] {
  return items.filter((item) => !isStrayStandaloneSymbol(item, items));
}

function isStrayStandaloneSymbol<T extends OcrLineLike>(item: T, items: T[]) {
  const text = item.text.trim();
  if (!isStrayStandaloneSymbolText(text)) return false;
  const rect = normalizeBbox(item.bbox);
  if (!rect) return false;
  return items.some((candidate) => {
    if (candidate === item || candidate.page !== item.page || isStrayStandaloneSymbolText(candidate.text.trim())) return false;
    const candidateRect = normalizeBbox(candidate.bbox);
    if (!candidateRect) return false;
    const verticalOverlap = overlapLength(rect.y1, rect.y2, candidateRect.y1, candidateRect.y2);
    const minHeight = Math.max(1, Math.min(rect.y2 - rect.y1, candidateRect.y2 - candidateRect.y1));
    const horizontalOverlap = overlapLength(rect.x1, rect.x2, candidateRect.x1, candidateRect.x2);
    const horizontalGap = Math.max(0, Math.max(candidateRect.x1 - rect.x2, rect.x1 - candidateRect.x2));
    return verticalOverlap / minHeight >= 0.45 && (horizontalOverlap > 0 || horizontalGap <= 12);
  });
}

function removeCrossLabelHeaderCandidates(items: SourceEvidenceItem[], config: EvidenceDisplayConfig) {
  if (config.basic_field_labels.length < 2) return items;
  return items.filter((item) => !isCrossLabelHeaderCandidateCoveredByAtomicFields(item, items, config));
}

function isCrossLabelHeaderCandidateCoveredByAtomicFields(
  item: SourceEvidenceItem,
  items: SourceEvidenceItem[],
  config: EvidenceDisplayConfig
) {
  const candidateLabels = basicFieldLabelsInText(item.text, config);
  if (candidateLabels.length < 2) return false;
  const candidateRect = normalizeBbox(item.bbox);
  if (!candidateRect) return false;
  const coveredLabels = new Set<string>();
  items.forEach((candidate) => {
    if (candidate === item || candidate.page !== item.page) return;
    const labels = basicFieldLabelsInText(candidate.text, config).filter((label) => candidateLabels.includes(label));
    if (labels.length !== 1) return;
    const rect = normalizeBbox(candidate.bbox);
    if (!rect || !isAtomicFieldBoxInsideCandidate(candidateRect, rect)) return;
    coveredLabels.add(labels[0]);
  });
  return coveredLabels.size >= 2;
}

function isAtomicFieldBoxInsideCandidate(candidate: BboxRect, atomic: BboxRect) {
  const verticalOverlap = overlapLength(candidate.y1, candidate.y2, atomic.y1, atomic.y2);
  const minHeight = Math.max(1, Math.min(candidate.y2 - candidate.y1, atomic.y2 - atomic.y1));
  if (verticalOverlap / minHeight < 0.55) return false;
  return atomic.x1 >= candidate.x1 - 4 && atomic.x2 <= candidate.x2 + 4;
}

function removeDuplicateBasicInfoFragments(items: SourceEvidenceItem[], config: EvidenceDisplayConfig) {
  const formFields = items.filter((item) => item.block_type === "form_field");
  if (formFields.length === 0) return items;
  return items.filter((item) => {
    if (item.block_type === "form_field" || item.block_type === "title") return true;
    if (!isBasicInfoFragment(item, config)) return true;
    if (isDuplicateBasicFieldFragment(item, formFields)) return false;
    if (basicFieldLabelCount(item.text, config) < 2) return true;
    return overlappingFormFieldCount(item, formFields) < 2;
  });
}

function isBasicInfoFragment(item: SourceEvidenceItem, config: EvidenceDisplayConfig) {
  return /基本|首页|信息/.test(item.section_name) || basicFieldLabelCount(item.text, config) >= 2;
}

function isDuplicateBasicFieldFragment(item: SourceEvidenceItem, formFields: SourceEvidenceItem[]) {
  if (normalizeEvidence(item.text).length === 0) return false;
  const itemText = normalizeEvidence(item.text);
  const itemRect = normalizeBbox(item.bbox);
  if (!itemText || !itemRect) return false;
  return formFields.some((field) => {
    const fieldRect = normalizeBbox(field.bbox);
    if (!fieldRect || bboxIntersectionArea(itemRect, fieldRect) === 0) return false;
    const fieldText = normalizeEvidence(field.text);
    return fieldText === itemText || fieldText.includes(itemText) || itemText.includes(fieldText);
  });
}

function overlappingFormFieldCount(item: SourceEvidenceItem, formFields: SourceEvidenceItem[]) {
  const itemRect = normalizeBbox(item.bbox);
  if (!itemRect) return 0;
  return formFields.filter((field) => {
    const fieldRect = normalizeBbox(field.bbox);
    if (!fieldRect) return false;
    return bboxIntersectionArea(itemRect, fieldRect) > 0;
  }).length;
}

function repairOverlappingFormFields(items: SourceEvidenceItem[]) {
  const repaired = items.map((item) => ({ ...item, bbox: [...item.bbox] }));
  const used = new Set<number>();
  for (let index = 0; index < repaired.length; index += 1) {
    if (used.has(index) || repaired[index].block_type !== "form_field") continue;
    const group = [index];
    for (let candidate = index + 1; candidate < repaired.length; candidate += 1) {
      if (used.has(candidate) || repaired[candidate].block_type !== "form_field") continue;
      if (shouldSplitSharedFormBbox(repaired[index].bbox, repaired[candidate].bbox)) {
        group.push(candidate);
      }
    }
    if (group.length < 2) continue;
    group.forEach((groupIndex) => used.add(groupIndex));
    splitFormFieldGroupBboxes(repaired, group);
  }
  return repaired;
}

function splitFormFieldGroupBboxes(items: SourceEvidenceItem[], group: number[]) {
  const rect = normalizeBbox(mergeBboxes(group.map((index) => items[index].bbox)));
  if (!rect) return;
  const sorted = [...group].sort((left, right) => items[left].reading_order - items[right].reading_order);
  const weights = sorted.map((index) => Math.max(4, normalizeEvidence(items[index].text).length));
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  const width = rect.x2 - rect.x1;
  const gap = Math.min(12, width * 0.025);
  let cursor = rect.x1;

  sorted.forEach((itemIndex, order) => {
    const share = width * (weights[order] / totalWeight);
    const left = cursor + (order === 0 ? 0 : gap / 2);
    const right = cursor + share - (order === sorted.length - 1 ? 0 : gap / 2);
    items[itemIndex].bbox = [left, rect.y1, Math.max(left + 8, right), rect.y2];
    cursor += share;
  });
}

function shouldSplitSharedFormBbox(first: number[], second: number[]) {
  const firstRect = normalizeBbox(first);
  const secondRect = normalizeBbox(second);
  if (!firstRect || !secondRect) return false;
  const verticalOverlap = overlapLength(firstRect.y1, firstRect.y2, secondRect.y1, secondRect.y2);
  const minHeight = Math.max(1, Math.min(firstRect.y2 - firstRect.y1, secondRect.y2 - secondRect.y1));
  const horizontalOverlap = overlapLength(firstRect.x1, firstRect.x2, secondRect.x1, secondRect.x2);
  const minWidth = Math.max(1, Math.min(firstRect.x2 - firstRect.x1, secondRect.x2 - secondRect.x1));
  return verticalOverlap / minHeight > 0.72 && horizontalOverlap / minWidth > 0.65;
}

function stitchOverlappingTextLineFragments<T extends OcrLineLike>(items: T[]): T[] {
  const eligible = items.filter(isStitchableTextItem);
  const passthrough = items.filter((item) => !isStitchableTextItem(item));
  if (eligible.length < 2) return renumberSourceItemsByVisualOrder(items);

  const lines: T[][] = [];
  eligible
    .slice()
    .sort(compareByPageAndPosition)
    .forEach((item) => {
      const rect = normalizeBbox(item.bbox);
      const line = rect ? lines.find((candidate) => isSameVisualLine(candidate, rect, item.page)) : null;
      if (line) {
        line.push(item);
      } else {
        lines.push([item]);
      }
    });

  const stitched = lines.flatMap(stitchLineFragments);
  return [...passthrough, ...stitched]
    .sort(compareByPageAndPosition)
    .map((item, index) => ({ ...item, reading_order: index + 1 }));
}

function renumberSourceItemsByVisualOrder<T extends OcrLineLike>(items: T[]): T[] {
  return items.slice().sort(compareByPageAndPosition).map((item, index) => ({ ...item, reading_order: index + 1 }));
}

function isStitchableTextItem(item: OcrLineLike) {
  return (
    ["line", "paragraph", "text"].includes(item.block_type) &&
    normalizeBbox(item.bbox) !== null &&
    normalizeEvidence(item.text).length >= 1
  );
}

function isSameVisualLine<T extends OcrLineLike>(line: T[], rect: BboxRect, page: number) {
  const baseRect = normalizeBbox(mergeBboxes(line.map((item) => item.bbox)));
  if (!baseRect || line[0]?.page !== page) return false;
  const verticalOverlap = overlapLength(baseRect.y1, baseRect.y2, rect.y1, rect.y2);
  const minHeight = Math.max(1, Math.min(baseRect.y2 - baseRect.y1, rect.y2 - rect.y1));
  const centerDelta = Math.abs((baseRect.y1 + baseRect.y2) / 2 - (rect.y1 + rect.y2) / 2);
  return verticalOverlap / minHeight >= 0.55 && centerDelta <= Math.max(baseRect.y2 - baseRect.y1, rect.y2 - rect.y1) * 0.7;
}

function stitchLineFragments<T extends OcrLineLike>(line: T[]): T[] {
  const output: T[] = [];
  line
    .slice()
    .sort((left, right) => {
      const leftRect = normalizeBbox(left.bbox);
      const rightRect = normalizeBbox(right.bbox);
      return (leftRect?.x1 ?? left.reading_order) - (rightRect?.x1 ?? right.reading_order);
    })
    .forEach((item) => {
      const targetIndex = output.findIndex((current) => canStitchSameLineItems(current, item));
      if (targetIndex < 0) {
        output.push(item);
        return;
      }
      output[targetIndex] = mergeSameLineTextItems(output[targetIndex], item);
    });
  return output;
}

function canStitchSameLineItems<T extends OcrLineLike>(first: T, second: T) {
  if (hasDistinctFieldLabelStarts(first.text, second.text)) return false;
  if (hasContainedMultiFieldCandidate(first.text, second.text)) return false;
  if (!hasStitchableGeometry(first, second)) return false;
  return Boolean(mergeSameLineText(first.text, second.text));
}

function hasStitchableGeometry(first: OcrLineLike, second: OcrLineLike) {
  const firstRect = normalizeBbox(first.bbox);
  const secondRect = normalizeBbox(second.bbox);
  if (!firstRect || !secondRect) return false;
  const horizontalOverlap = overlapLength(firstRect.x1, firstRect.x2, secondRect.x1, secondRect.x2);
  const minWidth = Math.max(1, Math.min(firstRect.x2 - firstRect.x1, secondRect.x2 - secondRect.x1));
  if (horizontalOverlap / minWidth >= 0.18) return true;
  const gap = Math.max(0, Math.max(firstRect.x1, secondRect.x1) - Math.min(firstRect.x2, secondRect.x2));
  const minHeight = Math.max(1, Math.min(firstRect.y2 - firstRect.y1, secondRect.y2 - secondRect.y1));
  return gap <= Math.max(10, minHeight * 0.45);
}

function hasDistinctFieldLabelStarts(first: string, second: string) {
  const firstLabel = fieldLabelsInText(first)[0] ?? null;
  const secondLabel = fieldLabelsInText(second)[0] ?? null;
  return Boolean(firstLabel && secondLabel && firstLabel !== secondLabel);
}

function hasContainedMultiFieldCandidate(first: string, second: string) {
  const firstLabels = fieldLabelsInText(first);
  const secondLabels = fieldLabelsInText(second);
  return (
    (firstLabels.length >= 2 && secondLabels.length < firstLabels.length) ||
    (secondLabels.length >= 2 && firstLabels.length < secondLabels.length)
  );
}

function mergeSameLineTextItems<T extends OcrLineLike>(first: T, second: T): T {
  const mergedText = mergeSameLineText(first.text, second.text) ?? first.text;
  const mergedBbox = mergeBboxes([first.bbox, second.bbox]);
  return {
    ...first,
    text: mergedText,
    bbox: mergedBbox.length ? mergedBbox : first.bbox,
    confidence: roundConfidence((first.confidence + second.confidence) / 2)
  };
}

// --- Source-page debug summary ---

export function sourcePageDebugSummary(
  rawItems: SourceEvidenceItem[],
  renderedItems: SourceEvidenceItem[],
  suppressedMeaninglessBoxCount = 0
): SourcePageDebug {
  const hiddenEmptyTextCount = rawItems.filter((item) => normalizeEvidence(item.text).length === 0 && normalizeBbox(item.bbox)).length;
  const lowConfidenceCount = renderedItems.filter((item) => Number(item.confidence) < 0.65).length;
  const edgeTouchingBoxCount = renderedItems.filter((item) => isEdgeTouchingSourceBox(item, renderedItems)).length;
  const longBoxCount = renderedItems.filter((item) => isSuspiciouslyLongSourceBox(item, renderedItems)).length;
  const rawTextCounts = new Map<string, number>();
  rawItems.forEach((item) => {
    const text = comparableLineSignature(item.text);
    if (text.length < 4) return;
    rawTextCounts.set(text, (rawTextCounts.get(text) ?? 0) + 1);
  });
  const duplicateTextCount = Array.from(rawTextCounts.values()).filter((count) => count > 1).length;
  const recommendedActions = sourceDebugRecommendedActions({
    hiddenEmptyTextCount,
    suppressedMeaninglessBoxCount,
    duplicateTextCount,
    edgeTouchingBoxCount,
    longBoxCount,
    lowConfidenceCount
  });
  return {
    rawBlockCount: rawItems.length,
    renderedBlockCount: renderedItems.length,
    hiddenEmptyTextCount,
    suppressedMeaninglessBoxCount,
    duplicateTextCount,
    edgeTouchingBoxCount,
    longBoxCount,
    lowConfidenceCount,
    recommendedActions
  };
}

function sourceDebugRecommendedActions(
  summary: Pick<
    SourcePageDebug,
    | "hiddenEmptyTextCount"
    | "suppressedMeaninglessBoxCount"
    | "duplicateTextCount"
    | "edgeTouchingBoxCount"
    | "longBoxCount"
    | "lowConfidenceCount"
  >
) {
  const actions: string[] = [];
  if (summary.suppressedMeaninglessBoxCount > 0) actions.push("过滤单字符/页码类大框并检查 OCR 检测阈值");
  if (summary.edgeTouchingBoxCount > 0) actions.push("检查 crop/tile padding 或增大 tile_overlap");
  if (summary.duplicateTextCount > 0) actions.push("启用 bbox IoU + 文本相似度去重");
  if (summary.longBoxCount > 0) actions.push("检查段落合并阈值和表格/多栏分区");
  if (summary.lowConfidenceCount > 0) actions.push("评测更高 DPI、去阴影、去摩尔纹、水印抑制候选");
  if (summary.hiddenEmptyTextCount > 0) actions.push("忽略空文本框并检查 OCR 检测阈值");
  return actions;
}

function isEdgeTouchingSourceBox(item: SourceEvidenceItem, pageItems: SourceEvidenceItem[]) {
  const rect = normalizeBbox(item.bbox);
  if (!rect) return false;
  const pageRect = normalizeBbox(mergeBboxes(pageItems.map((candidate) => candidate.bbox)));
  if (!pageRect) return false;
  const pageWidth = Math.max(1, pageRect.x2 - pageRect.x1);
  const tolerance = Math.max(3, pageWidth * 0.006);
  return rect.x1 <= tolerance || rect.x2 >= pageRect.x2 - tolerance;
}

function isSuspiciouslyLongSourceBox(item: SourceEvidenceItem, pageItems: SourceEvidenceItem[]) {
  const rect = normalizeBbox(item.bbox);
  const pageRect = normalizeBbox(mergeBboxes(pageItems.map((candidate) => candidate.bbox)));
  if (!rect || !pageRect) return false;
  const pageWidth = Math.max(1, pageRect.x2 - pageRect.x1);
  const textLength = normalizeEvidence(item.text).length;
  return rect.x2 - rect.x1 > pageWidth * 0.82 && textLength < 18;
}

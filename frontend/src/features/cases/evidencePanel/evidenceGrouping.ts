import type { DocumentFragment, EvidenceDisplayConfig } from "../../../shared/types/api";
import { normalizeBbox, normalizeEvidencePage } from "./evidenceGeometry.js";
import { evidenceSectionLabel } from "./evidenceText.js";
import { buildDisplayItems, displayBlockType } from "./displayItems.js";
import { prepareSourceItems, prepareSourceItemsWithDebug, sourcePageDebugSummary } from "./sourcePreparation.js";
import type { EvidenceItem, EvidencePage, SourceEvidenceItem, SourcePageDebug } from "./types";

export function groupEvidenceByPage(evidenceItems: DocumentFragment[], config: EvidenceDisplayConfig): EvidencePage[] {
  const sourcePages = new Map<number, SourceEvidenceItem[]>();
  evidenceItems
    .map((item, index) => {
      const sourcePage = normalizeEvidencePage(item.page);
      return { ...item, page: sourcePage, sourceKey: `${sourcePage}-${item.reading_order}-${index}` };
    })
    .sort((left, right) => left.page - right.page || left.reading_order - right.reading_order)
    .forEach((item) => {
      const list = sourcePages.get(item.page) ?? [];
      list.push(item);
      sourcePages.set(item.page, list);
    });
  return Array.from(sourcePages, ([page, items]) => ({ page, items }))
    .sort((left, right) => left.page - right.page)
    .map((group, index) => ({
      page: group.page,
      displayPage: index + 1,
      items: buildDisplayItems(prepareSourceItems(group.items, config), config)
    }));
}

export function groupSourceEvidenceByPage(evidenceItems: DocumentFragment[], config: EvidenceDisplayConfig): EvidencePage[] {
  const sourcePages = new Map<number, EvidenceItem[]>();
  const debugByPage = new Map<number, SourcePageDebug>();
  const sourceItems = evidenceItems
    .map((item, index) => {
      const sourcePage = normalizeEvidencePage(item.page);
      return {
        ...item,
        page: sourcePage,
        sourceKey: `source-${sourcePage}-${item.reading_order ?? index + 1}-${index}`
      };
    })
    .sort((left, right) => left.page - right.page || left.reading_order - right.reading_order);
  const itemsByPage = new Map<number, SourceEvidenceItem[]>();
  sourceItems.forEach((item) => {
    const list = itemsByPage.get(item.page) ?? [];
    list.push(item);
    itemsByPage.set(item.page, list);
  });
  Array.from(itemsByPage, ([page, items]) => {
    const prepared = prepareSourceItemsWithDebug(items, config);
    debugByPage.set(page, sourcePageDebugSummary(items, prepared.items, prepared.suppressedMeaninglessBoxCount));
    return prepared.items;
  })
    .flat()
    .forEach((item, index) => {
      const list = sourcePages.get(item.page) ?? [];
      list.push({
        ...item,
        key: `source-${item.page}-${item.reading_order ?? index + 1}-${index}`,
        section_name: evidenceSectionLabel(item.text, item.section_name, config),
        block_type: displayBlockType(item, config)
      });
      sourcePages.set(item.page, list);
    });
  return Array.from(sourcePages, ([page, items]) => ({ page, items }))
    .sort((left, right) => left.page - right.page)
    .map((group, index) => ({
      page: group.page,
      displayPage: index + 1,
      items: group.items,
      sourceDebug: debugByPage.get(group.page)
    }));
}

export function sourceEvidenceImageStateKey(groups: EvidencePage[]) {
  return groups
    .map((group) => {
      const signatures = group.items.map((item) => {
        const bbox = normalizeBbox(item.bbox);
        const bboxKey = bbox
          ? [bbox.x1, bbox.y1, bbox.x2, bbox.y2].map((value) => Math.round(value * 100) / 100).join(",")
          : "none";
        const textKey = item.text.trim().slice(0, 48);
        return [
          item.reading_order ?? "",
          item.block_type ?? "",
          item.render_dpi ?? "",
          item.preprocess_profile ?? "",
          bboxKey,
          textKey.length,
          textKey
        ].join(":");
      });
      return `${group.page}/${group.items.length}/${signatures.join("|")}`;
    })
    .join(";");
}

export function isSourceOverlayBlankClickClassName(className: string) {
  const classes = new Set(className.split(/\s+/).filter(Boolean));
  if (classes.has("ocr-image-box") || classes.has("ocr-copy-text") || classes.has("ocr-image-box-label")) return false;
  return (
    classes.has("ocr-source-image") ||
    classes.has("ocr-image-layer") ||
    classes.has("ocr-image-stage") ||
    classes.has("ocr-image-empty")
  );
}

export function hasSourceDebugSignal(debug: SourcePageDebug) {
  return (
    debug.hiddenEmptyTextCount > 0 ||
    debug.suppressedMeaninglessBoxCount > 0 ||
    debug.duplicateTextCount > 0 ||
    debug.edgeTouchingBoxCount > 0 ||
    debug.longBoxCount > 0 ||
    debug.lowConfidenceCount > 0
  );
}

export function sourceDebugBadges(debug: SourcePageDebug) {
  const badges: string[] = [];
  if (debug.hiddenEmptyTextCount > 0) badges.push(`隐藏空框 ${debug.hiddenEmptyTextCount}`);
  if (debug.suppressedMeaninglessBoxCount > 0) badges.push(`无意义框 ${debug.suppressedMeaninglessBoxCount}`);
  if (debug.duplicateTextCount > 0) badges.push(`重复候选 ${debug.duplicateTextCount}`);
  if (debug.edgeTouchingBoxCount > 0) badges.push(`贴边框 ${debug.edgeTouchingBoxCount}`);
  if (debug.longBoxCount > 0) badges.push(`长框 ${debug.longBoxCount}`);
  if (debug.lowConfidenceCount > 0) badges.push(`低置信 ${debug.lowConfidenceCount}`);
  return badges;
}

import type { DocumentFragment, EvidenceDisplayConfig } from "../../../shared/types/api";
import { mergeBboxes, roundConfidence } from "./evidenceGeometry.js";
import {
  continuesCurrentSection,
  evidenceSectionLabel,
  isDocumentTitle,
  joinParagraphText,
  normalizeSectionHeadingDelimiter,
  standaloneSectionMarker,
  startsWithBasicField,
  startsWithSectionHeading
} from "./evidenceText.js";
import { normalizeBbox } from "./evidenceGeometry.js";
import type { EvidenceItem, SourceEvidenceItem } from "./types";

export function buildDisplayItems(items: SourceEvidenceItem[], config: EvidenceDisplayConfig): EvidenceItem[] {
  const displayItems: EvidenceItem[] = [];
  let paragraph: SourceEvidenceItem[] = [];
  let pendingSectionMarker: string | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    displayItems.push(...splitEmbeddedSections(mergeEvidenceItems(paragraph, displayItems.length, config), config));
    paragraph = [];
  };

  for (const item of items) {
    const marker = standaloneSectionMarker(item.text, config);
    if (marker) {
      flushParagraph();
      pendingSectionMarker = marker;
      continue;
    }

    const current = applyPendingSectionMarker(item, pendingSectionMarker, config);
    pendingSectionMarker = null;

    if (shouldKeepAtomic(current, config)) {
      flushParagraph();
      displayItems.push(...splitEmbeddedSections(asDisplayItem(current, displayItems.length, config), config));
      continue;
    }

    const previous = paragraph[paragraph.length - 1];
    if (!previous || shouldMergeIntoParagraph(previous, current, config)) {
      paragraph.push(current);
    } else {
      flushParagraph();
      paragraph.push(current);
    }
  }
  flushParagraph();
  return displayItems;
}

export function displayBlockType(item: SourceEvidenceItem, config: EvidenceDisplayConfig): DocumentFragment["block_type"] {
  if (item.block_type === "form_field" || item.block_type === "table") return item.block_type;
  if (isDocumentTitle(item.text, config)) return "title";
  if (item.block_type === "title") return "paragraph";
  return item.block_type;
}

function asDisplayItem(item: SourceEvidenceItem, index: number, config: EvidenceDisplayConfig): EvidenceItem {
  const text = normalizeSectionHeadingDelimiter(item.text, config);
  return {
    ...item,
    key: `block-${item.sourceKey}-${index}`,
    text,
    section_name: evidenceSectionLabel(text, item.section_name, config),
    block_type: displayBlockType(item, config)
  };
}

function mergeEvidenceItems(items: SourceEvidenceItem[], index: number, config: EvidenceDisplayConfig): EvidenceItem {
  const first = items[0];
  const text = normalizeSectionHeadingDelimiter(joinParagraphText(items.map((item) => item.text)), config);
  const sectionName = evidenceSectionLabel(text, first.section_name, config);
  return {
    ...first,
    key: `paragraph-${first.page}-${items[0].reading_order}-${items[items.length - 1].reading_order}-${index}`,
    text,
    bbox: mergeBboxes(items.map((item) => item.bbox)),
    confidence: roundConfidence(items.reduce((total, item) => total + item.confidence, 0) / items.length),
    section_name: sectionName,
    block_type: items.length > 1 || startsWithSectionHeading(first.text, config) ? "paragraph" : displayBlockType(first, config)
  };
}

function splitEmbeddedSections(item: EvidenceItem, config: EvidenceDisplayConfig): EvidenceItem[] {
  if (!["line", "paragraph", "text"].includes(item.block_type)) return [item];
  const splitIndexes = embeddedSectionIndexes(item.text, config);
  if (splitIndexes.length === 0) return [item];
  const cuts = [0, ...splitIndexes, item.text.length];
  const blocks: EvidenceItem[] = [];
  for (let index = 0; index < cuts.length - 1; index += 1) {
    const text = normalizeSectionHeadingDelimiter(item.text.slice(cuts[index], cuts[index + 1]).trim(), config);
    if (!text) continue;
    blocks.push({
      ...item,
      key: `${item.key}-section-${index}`,
      text,
      section_name: evidenceSectionLabel(text, item.section_name, config),
      block_type: isDocumentTitle(text, config) ? "title" : "paragraph"
    });
  }
  return blocks.length ? blocks : [item];
}

function embeddedSectionIndexes(text: string, config: EvidenceDisplayConfig) {
  const indexes = new Set<number>();
  config.section_labels.forEach((label) => {
    let cursor = text.indexOf(label, 1);
    while (cursor > 0) {
      const previous = text[cursor - 1];
      const next = text[cursor + label.length] ?? "";
      if (/[。；;！？\n\r]/.test(previous) && /[\s：:A-ZＴPBR一-龥]/.test(next)) {
        indexes.add(cursor);
      }
      cursor = text.indexOf(label, cursor + label.length);
    }
  });
  return Array.from(indexes).sort((left, right) => left - right);
}

function shouldKeepAtomic(item: SourceEvidenceItem, config: EvidenceDisplayConfig) {
  if (["form_field", "table"].includes(item.block_type)) return true;
  if (item.block_type === "title") return isDocumentTitle(item.text, config);
  const text = item.text.trim();
  if (!text) return true;
  if (isDocumentTitle(text, config)) return true;
  if (startsWithBasicField(text, config)) return true;
  return false;
}

function shouldMergeIntoParagraph(previous: SourceEvidenceItem, current: SourceEvidenceItem, config: EvidenceDisplayConfig) {
  if (previous.page !== current.page) return false;
  if (startsWithBasicField(current.text, config) || isDocumentTitle(current.text, config)) return false;
  if (startsWithSectionHeading(current.text, config) && !continuesCurrentSection(previous.text, current.text, config))
    return false;

  const previousRect = normalizeBbox(previous.bbox);
  const currentRect = normalizeBbox(current.bbox);
  if (!previousRect || !currentRect) return true;
  const previousHeight = Math.max(1, previousRect.y2 - previousRect.y1);
  const verticalGap = currentRect.y1 - previousRect.y2;
  const leftDelta = Math.abs(currentRect.x1 - previousRect.x1);
  return verticalGap <= Math.max(54, previousHeight * 3.1) && leftDelta <= 170;
}

function applyPendingSectionMarker(item: SourceEvidenceItem, marker: string | null, config: EvidenceDisplayConfig): SourceEvidenceItem {
  if (!marker) return item;
  const text = item.text.trim();
  if (!text || text.startsWith(marker) || isDocumentTitle(text, config)) {
    return { ...item, section_name: marker };
  }
  return {
    ...item,
    text: `${marker}：${text}`,
    section_name: marker
  };
}

import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { DocumentFragment, EvidenceDisplayConfig, FieldResult } from "../../shared/types/api";

interface EvidencePanelProps {
  evidenceItems: DocumentFragment[];
  activeResult?: FieldResult;
  activeFieldLabel?: string;
  displayConfig?: EvidenceDisplayConfig;
}

export const EvidencePanel = memo(function EvidencePanel({ evidenceItems, activeResult, activeFieldLabel, displayConfig }: EvidencePanelProps) {
  const activeBlockRef = useRef<HTMLElement | null>(null);
  const documentPageRef = useRef<HTMLDivElement | null>(null);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const config = useMemo(() => mergeEvidenceDisplayConfig(displayConfig), [displayConfig]);
  const activeEvidenceText = activeResult?.evidence_span ?? activeResult?.evidence_text ?? "";
  const activePage = activeResult?.page ?? null;
  const activeBbox = activeResult?.bbox ?? [];
  const groupedEvidence = useMemo(() => groupEvidenceByPage(evidenceItems, config), [evidenceItems, config]);
  const displayBlockCount = useMemo(
    () => groupedEvidence.reduce((total, group) => total + group.items.length, 0),
    [groupedEvidence]
  );
  const fieldEvidenceKey = useMemo(
    () => findActiveEvidenceKey(groupedEvidence, activeEvidenceText, activePage, activeBbox),
    [activeBbox, activeEvidenceText, activePage, groupedEvidence]
  );
  const activeEvidenceKey = selectedEvidenceKey ?? fieldEvidenceKey;

  useEffect(() => {
    setSelectedEvidenceKey(null);
  }, [activeResult?.field_key, activeEvidenceText]);

  useEffect(() => {
    scrollEvidenceIntoPanel(activeBlockRef.current, documentPageRef.current);
  }, [activeEvidenceKey]);

  return (
    <section className="document-panel">
      <div className="panel-title">
        <span>智能文档解析</span>
        <small>{groupedEvidence.length} 页 / {displayBlockCount} 段</small>
      </div>
      <div className="document-page transcript-page-wrap" aria-label="脱敏智能文档解析证据" ref={documentPageRef}>
        {evidenceItems.length === 0 && <div className="empty-state">暂无证据片段</div>}
        {evidenceItems.length > 0 && (
          <article className="document-sheet transcript-sheet">
            {groupedEvidence.map((group) => (
              <section
                className="ocr-page transcript-page"
                key={`${group.page}-${group.displayPage}`}
                aria-label={`第 ${group.displayPage} 页智能文档解析`}
              >
                <div className="ocr-page-marker">
                  <span>第 {group.displayPage} 页</span>
                  <small>智能解析 · {group.items.length} 段</small>
                </div>
                <div className="transcript-document">
                  {renderTranscriptBlocks({
                    activeEvidenceKey,
                    activeEvidenceText,
                    activeFieldLabel,
                    bindActiveBlock: (node) => {
                      activeBlockRef.current = node;
                    },
                    fieldEvidenceKey,
                    config,
                    items: group.items,
                    onSelect: setSelectedEvidenceKey
                  })}
                </div>
              </section>
            ))}
          </article>
        )}
      </div>
    </section>
  );
});

function scrollEvidenceIntoPanel(activeBlock: HTMLElement | null, scrollContainer: HTMLElement | null) {
  if (!activeBlock || !scrollContainer) return;
  const blockRect = activeBlock.getBoundingClientRect();
  const containerRect = scrollContainer.getBoundingClientRect();
  const blockCenter = blockRect.top - containerRect.top + scrollContainer.scrollTop + blockRect.height / 2;
  const nextTop = Math.max(0, blockCenter - scrollContainer.clientHeight / 2);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  scrollContainer.scrollTo({ top: nextTop, behavior: reducedMotion ? "auto" : "smooth" });
}

function renderTranscriptBlocks({
  activeEvidenceKey,
  activeEvidenceText,
  activeFieldLabel,
  bindActiveBlock,
  config,
  fieldEvidenceKey,
  items,
  onSelect
}: {
  activeEvidenceKey: string | null;
  activeEvidenceText: string;
  activeFieldLabel?: string;
  bindActiveBlock: (node: HTMLElement | null) => void;
  config: EvidenceDisplayConfig;
  fieldEvidenceKey: string | null;
  items: EvidenceItem[];
  onSelect: (key: string) => void;
}) {
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < items.length) {
    const block = items[index];
    if (block.block_type === "title") {
      nodes.push(
        <EvidenceBlock
          activeEvidenceKey={activeEvidenceKey}
          activeEvidenceText={activeEvidenceText}
          activeFieldLabel={activeFieldLabel}
          bindActiveBlock={bindActiveBlock}
          block={block}
          config={config}
          fieldEvidenceKey={fieldEvidenceKey}
          key={block.key}
          onSelect={onSelect}
          variant="title"
        />
      );
      index += 1;
      continue;
    }

    if (block.block_type === "form_field") {
      const fields: EvidenceItem[] = [];
      while (items[index]?.block_type === "form_field") {
        fields.push(items[index]);
        index += 1;
      }
      nodes.push(
        <div className="transcript-field-grid" key={`fields-${fields[0].key}`}>
          {fields.map((field) => (
            <EvidenceBlock
              activeEvidenceKey={activeEvidenceKey}
              activeEvidenceText={activeEvidenceText}
              activeFieldLabel={activeFieldLabel}
              bindActiveBlock={bindActiveBlock}
              block={field}
              config={config}
              fieldEvidenceKey={fieldEvidenceKey}
              key={field.key}
              onSelect={onSelect}
              variant="field"
            />
          ))}
        </div>
      );
      continue;
    }

    nodes.push(
      <EvidenceBlock
        activeEvidenceKey={activeEvidenceKey}
        activeEvidenceText={activeEvidenceText}
        activeFieldLabel={activeFieldLabel}
        bindActiveBlock={bindActiveBlock}
        block={block}
        config={config}
        fieldEvidenceKey={fieldEvidenceKey}
        key={block.key}
        onSelect={onSelect}
        variant="paragraph"
      />
    );
    index += 1;
  }

  return nodes;
}

function EvidenceBlock({
  activeEvidenceKey,
  activeEvidenceText,
  activeFieldLabel,
  bindActiveBlock,
  block,
  config,
  fieldEvidenceKey,
  onSelect,
  variant
}: {
  activeEvidenceKey: string | null;
  activeEvidenceText: string;
  activeFieldLabel?: string;
  bindActiveBlock: (node: HTMLElement | null) => void;
  block: EvidenceItem;
  config: EvidenceDisplayConfig;
  fieldEvidenceKey: string | null;
  onSelect: (key: string) => void;
  variant: "field" | "paragraph" | "title";
}) {
  const active = block.key === activeEvidenceKey;
  const linkedToField = block.key === fieldEvidenceKey;
  const tone = sectionTone(`${block.section_name} ${block.text}`, config);
  const displayText = normalizeTranscriptDisplayText(block.text, block.section_name, variant, config);
  const className = [
    "transcript-block",
    `transcript-${variant}`,
    `section-${tone}`,
    active ? "active" : "",
    linkedToField ? "field-linked" : ""
  ].filter(Boolean).join(" ");
  const content =
    variant === "field"
      ? renderFieldContent(displayText, activeEvidenceText, linkedToField, config)
      : renderTranscriptText(displayText, activeEvidenceText, linkedToField, config);

  return (
    <div
      aria-current={active ? "true" : undefined}
      aria-label={`证据：${displayText}，置信度 ${Math.round(block.confidence * 100)}%`}
      className={className}
      onClick={() => onSelect(block.key)}
      onKeyDown={(event) => selectEvidenceOnKeyDown(event, () => onSelect(block.key))}
      ref={active ? bindActiveBlock : undefined}
      role="button"
      tabIndex={0}
    >
      {variant === "field" ? content : <p>{content}</p>}
      {active && (
        <span className="transcript-evidence-meta" aria-hidden="true">
          {evidenceDetailLabel(block, linkedToField, activeFieldLabel, config)} · {Math.round(block.confidence * 100)}%
        </span>
      )}
    </div>
  );
}

function renderFieldContent(text: string, evidenceText: string, active: boolean, config: EvidenceDisplayConfig) {
  const field = splitLeadingLabel(text);
  if (!field) {
    return <span className="transcript-field-value">{renderTranscriptText(text, evidenceText, active, config)}</span>;
  }
  return (
    <>
      <span className="transcript-field-name">{field.label.replace(/[：:]$/, "")}</span>
      <span className="transcript-field-value">{renderTranscriptText(field.value || "未识别", evidenceText, active, config)}</span>
    </>
  );
}

function renderTranscriptText(text: string, evidenceText: string, active: boolean, config: EvidenceDisplayConfig): ReactNode {
  const hitRange = active ? evidenceRange(text, evidenceText) : null;
  const labelRanges = clinicalLabelRanges(text, config);
  const cuts = new Set([0, text.length]);
  if (hitRange) {
    cuts.add(hitRange.start);
    cuts.add(hitRange.end);
  }
  labelRanges.forEach((range) => {
    cuts.add(range.start);
    cuts.add(range.end);
  });
  const sortedCuts = Array.from(cuts).filter((value) => value >= 0 && value <= text.length).sort((left, right) => left - right);
  const nodes: ReactNode[] = [];
  for (let index = 0; index < sortedCuts.length - 1; index += 1) {
    const start = sortedCuts[index];
    const end = sortedCuts[index + 1];
    const value = text.slice(start, end);
    if (!value) continue;
    const label = labelRanges.some((range) => start >= range.start && end <= range.end);
    const hit = Boolean(hitRange && start >= hitRange.start && end <= hitRange.end);
    const content = label ? <strong className="transcript-inline-label">{value}</strong> : value;
    nodes.push(
      hit ? (
        <mark className="evidence-hit" key={`${start}-${end}`}>
          {content}
        </mark>
      ) : (
        <span key={`${start}-${end}`}>{content}</span>
      )
    );
  }
  return nodes.length ? nodes : text;
}

function selectEvidenceOnKeyDown(event: KeyboardEvent<HTMLElement>, select: () => void) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  select();
}

type EvidenceItem = DocumentFragment & {
  key: string;
};

type SourceEvidenceItem = DocumentFragment & {
  sourceKey: string;
};

type EvidencePage = {
  page: number;
  displayPage: number;
  items: EvidenceItem[];
};

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

function normalizeEvidencePage(page: number) {
  return Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
}

function findActiveEvidenceKey(groups: EvidencePage[], evidenceText: string, page: number | null, bbox: number[]) {
  if (!evidenceText && page === null) return null;
  for (const group of groups) {
    for (const item of group.items) {
      if (isStrongEvidenceMatch(item.text, evidenceText)) return item.key;
    }
  }
  const textOverlapMatch = findTextOverlapEvidenceKey(groups, evidenceText, page);
  if (textOverlapMatch) return textOverlapMatch;
  if (evidenceText) return null;
  const bboxMatch = findBboxEvidenceKey(groups, page, bbox);
  if (bboxMatch) return bboxMatch;
  return null;
}

function isStrongEvidenceMatch(text: string, evidenceText: string) {
  const normalizedText = normalizeEvidence(text);
  const normalizedEvidence = normalizeEvidence(evidenceText);
  if (!normalizedText || !normalizedEvidence) return false;
  return normalizedText.includes(normalizedEvidence) || normalizedEvidence.includes(normalizedText);
}

function normalizeEvidence(value: string | null | undefined) {
  return (value ?? "").replace(/\s+/g, "").trim();
}

function findTextOverlapEvidenceKey(groups: EvidencePage[], evidenceText: string, page: number | null) {
  const normalizedEvidence = normalizeEvidence(evidenceText);
  if (normalizedEvidence.length < 4) return null;
  const hasRequestedPage = page !== null && groups.some((group) => group.page === page || group.displayPage === page);
  let best: { key: string; score: number } | null = null;
  for (const group of groups) {
    if (hasRequestedPage && group.page !== page && group.displayPage !== page) continue;
    for (const item of group.items) {
      const normalizedText = normalizeEvidence(item.text);
      if (normalizedText.length < 4) continue;
      const score = evidenceOverlapScore(normalizedText, normalizedEvidence, item.section_name);
      if (!best || score > best.score) best = { key: item.key, score };
    }
  }
  return best && best.score >= 0.22 ? best.key : null;
}

function evidenceOverlapScore(text: string, evidenceText: string, sectionName: string) {
  const textPairs = ngramSet(text);
  const evidencePairs = ngramSet(evidenceText);
  if (textPairs.size === 0 || evidencePairs.size === 0) return 0;
  let overlap = 0;
  textPairs.forEach((pair) => {
    if (evidencePairs.has(pair)) overlap += 1;
  });
  const denominator = Math.max(1, Math.min(textPairs.size, evidencePairs.size));
  const sectionBonus = sectionName && evidenceText.includes(sectionName) ? 0.08 : 0;
  return overlap / denominator + sectionBonus;
}

function ngramSet(value: string) {
  const set = new Set<string>();
  if (value.length <= 2) {
    if (value) set.add(value);
    return set;
  }
  for (let index = 0; index < value.length - 1; index += 1) {
    set.add(value.slice(index, index + 2));
  }
  return set;
}

function evidenceRange(text: string, evidenceText: string) {
  const normalizedEvidence = normalizeEvidence(evidenceText);
  if (!normalizedEvidence) return null;

  let normalizedText = "";
  const rawIndexByNormalizedIndex: number[] = [];
  for (let rawIndex = 0; rawIndex < text.length; rawIndex += 1) {
    const char = text[rawIndex];
    if (/\s/.test(char)) continue;
    normalizedText += char;
    rawIndexByNormalizedIndex.push(rawIndex);
  }

  const normalizedStart = normalizedText.indexOf(normalizedEvidence);
  if (normalizedStart < 0) return null;
  const normalizedEnd = normalizedStart + normalizedEvidence.length - 1;
  const start = rawIndexByNormalizedIndex[normalizedStart];
  const end = rawIndexByNormalizedIndex[normalizedEnd] + 1;
  return Number.isFinite(start) && Number.isFinite(end) ? { start, end } : null;
}

function prepareSourceItems(items: SourceEvidenceItem[], config: EvidenceDisplayConfig) {
  return repairOverlappingFormFields(removeDuplicateBasicInfoFragments(items, config));
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

function overlapLength(firstStart: number, firstEnd: number, secondStart: number, secondEnd: number) {
  return Math.max(0, Math.min(firstEnd, secondEnd) - Math.max(firstStart, secondStart));
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

function isBasicInfoFragment(item: SourceEvidenceItem, config: EvidenceDisplayConfig) {
  return /基本|首页|信息/.test(item.section_name) || basicFieldLabelCount(item.text, config) >= 2;
}

function basicFieldLabelCount(text: string, config: EvidenceDisplayConfig) {
  return config.basic_field_labels.reduce((count, label) => count + (new RegExp(`${escapeRegExp(label)}\\s*[:：]`).test(text) ? 1 : 0), 0);
}

function buildDisplayItems(items: SourceEvidenceItem[], config: EvidenceDisplayConfig): EvidenceItem[] {
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

function asDisplayItem(item: SourceEvidenceItem, index: number, config: EvidenceDisplayConfig): EvidenceItem {
  return {
    ...item,
    key: `block-${item.sourceKey}-${index}`,
    section_name: evidenceSectionLabel(item.text, item.section_name, config),
    block_type: displayBlockType(item, config)
  };
}

function mergeEvidenceItems(items: SourceEvidenceItem[], index: number, config: EvidenceDisplayConfig): EvidenceItem {
  const first = items[0];
  const sectionName = evidenceSectionLabel(first.text, first.section_name, config);
  return {
    ...first,
    key: `paragraph-${first.page}-${items[0].reading_order}-${items[items.length - 1].reading_order}-${index}`,
    text: joinParagraphText(items.map((item) => item.text)),
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
    const text = item.text.slice(cuts[index], cuts[index + 1]).trim();
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
  if (startsWithSectionHeading(current.text, config) && !continuesCurrentSection(previous.text, current.text, config)) return false;

  const previousRect = normalizeBbox(previous.bbox);
  const currentRect = normalizeBbox(current.bbox);
  if (!previousRect || !currentRect) return true;
  const previousHeight = Math.max(1, previousRect.y2 - previousRect.y1);
  const verticalGap = currentRect.y1 - previousRect.y2;
  const leftDelta = Math.abs(currentRect.x1 - previousRect.x1);
  return verticalGap <= Math.max(54, previousHeight * 3.1) && leftDelta <= 170;
}

function joinParagraphText(lines: string[]) {
  let text = "";
  lines.map((line) => line.trim()).filter(Boolean).forEach((line) => {
    if (!text) {
      text = line;
    } else if (shouldJoinWithoutSpace(text, line)) {
      text += line;
    } else {
      text += ` ${line}`;
    }
  });
  return text;
}

function shouldJoinWithoutSpace(previous: string, current: string) {
  if (/[\u4e00-\u9fff，、。；：？！）】》」』,.;:!?]$/.test(previous)) return true;
  if (/^[\u4e00-\u9fff，、。；：？！）】》」』,.;:!?]/.test(current)) return true;
  return false;
}

function displayBlockType(item: SourceEvidenceItem, config: EvidenceDisplayConfig): DocumentFragment["block_type"] {
  if (item.block_type === "form_field" || item.block_type === "table") return item.block_type;
  if (isDocumentTitle(item.text, config)) return "title";
  if (item.block_type === "title") return "paragraph";
  return item.block_type;
}

function normalizeTranscriptDisplayText(text: string, sectionName: string, variant: "field" | "paragraph" | "title", config: EvidenceDisplayConfig) {
  let normalized = repairCommonOcrText(text.trim(), config);
  if (variant === "paragraph" && evidenceSectionLabel(normalized, sectionName, config) === "体格检查") {
    normalized = normalized.replace(/^体格检查\s*[:：]?\s*(?=[TＴPBR一-龥])/u, "体格检查：");
    normalized = normalized.replace(/(体格检查：\s*)T\s*[:：]/u, "$1T：");
    normalized = normalized.replace(/\s+(P|R|BP)\s*[:：]/gu, " $1：");
  }
  return normalized;
}

function applyPendingSectionMarker(item: SourceEvidenceItem, marker: string | null, config: EvidenceDisplayConfig): SourceEvidenceItem {
  if (!marker) return item;
  const text = item.text.trim();
  if (!text || startsWithSectionHeading(text, config) || isDocumentTitle(text, config)) {
    return { ...item, section_name: marker };
  }
  return {
    ...item,
    text: `${marker}：${text}`,
    section_name: marker
  };
}

function repairCommonOcrText(text: string, config: EvidenceDisplayConfig) {
  return config.common_ocr_repairs.reduce((value, repair) => {
    try {
      return value.replace(new RegExp(repair.pattern, "giu"), repair.replacement);
    } catch {
      return value;
    }
  }, text);
}

function clinicalLabelRanges(text: string, config: EvidenceDisplayConfig) {
  const ranges: Array<{ start: number; end: number }> = [];
  config.inline_record_labels.forEach((label) => {
    const tokens = [`${label}：`, `${label}:`];
    tokens.forEach((token) => {
      let cursor = text.indexOf(token);
      while (cursor >= 0) {
        const previous = cursor === 0 ? "" : text[cursor - 1];
        if (cursor === 0 || /[。；;！？\s]/.test(previous)) {
          ranges.push({ start: cursor, end: cursor + token.length });
        }
        cursor = text.indexOf(token, cursor + token.length);
      }
    });
  });
  return mergeTextRanges(ranges);
}

function mergeTextRanges(ranges: Array<{ start: number; end: number }>) {
  return ranges
    .sort((left, right) => left.start - right.start || right.end - left.end)
    .reduce<Array<{ start: number; end: number }>>((merged, range) => {
      const previous = merged[merged.length - 1];
      if (!previous || range.start >= previous.end) {
        merged.push(range);
      } else {
        previous.end = Math.max(previous.end, range.end);
      }
      return merged;
    }, []);
}

function mergeBboxes(bboxes: number[][]) {
  const rects = bboxes.map((bbox) => normalizeBbox(bbox)).filter((rect): rect is BboxRect => rect !== null);
  if (rects.length === 0) return [];
  return [
    Math.min(...rects.map((rect) => rect.x1)),
    Math.min(...rects.map((rect) => rect.y1)),
    Math.max(...rects.map((rect) => rect.x2)),
    Math.max(...rects.map((rect) => rect.y2))
  ];
}

function roundConfidence(value: number) {
  return Math.round(value * 10000) / 10000;
}

type BboxRect = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

function normalizeBbox(bbox: number[]): BboxRect | null {
  if (bbox.length < 4 || bbox.some((value) => !Number.isFinite(value))) return null;
  const [x1, y1, x2, y2] = bbox;
  const rect = {
    x1: Math.min(x1, x2),
    y1: Math.min(y1, y2),
    x2: Math.max(x1, x2),
    y2: Math.max(y1, y2)
  };
  if (rect.x2 - rect.x1 <= 0 || rect.y2 - rect.y1 <= 0) return null;
  return rect;
}

function findBboxEvidenceKey(groups: EvidencePage[], page: number | null, bbox: number[]) {
  if (page === null) return null;
  const target = normalizeBbox(bbox);
  if (!target) return null;
  const pageItems = groups.find((group) => group.page === page || group.displayPage === page)?.items ?? [];
  let best: { key: string; score: number } | null = null;
  for (const item of pageItems) {
    const rect = normalizeBbox(item.bbox);
    if (!rect) continue;
    const score = bboxScore(target, rect);
    if (!best || score > best.score) best = { key: item.key, score };
  }
  return best && best.score > 0 ? best.key : null;
}

function bboxScore(target: BboxRect, candidate: BboxRect) {
  const overlapArea = bboxIntersectionArea(target, candidate);
  const targetArea = Math.max(1, (target.x2 - target.x1) * (target.y2 - target.y1));
  const candidateArea = Math.max(1, (candidate.x2 - candidate.x1) * (candidate.y2 - candidate.y1));
  if (overlapArea > 0) return overlapArea / Math.min(targetArea, candidateArea);

  const targetCenterX = (target.x1 + target.x2) / 2;
  const targetCenterY = (target.y1 + target.y2) / 2;
  const candidateCenterX = (candidate.x1 + candidate.x2) / 2;
  const candidateCenterY = (candidate.y1 + candidate.y2) / 2;
  const distance = Math.hypot(targetCenterX - candidateCenterX, targetCenterY - candidateCenterY);
  return distance < 24 ? 0.05 : 0;
}

function bboxIntersectionArea(first: BboxRect, second: BboxRect) {
  const overlapX = Math.max(0, Math.min(first.x2, second.x2) - Math.max(first.x1, second.x1));
  const overlapY = Math.max(0, Math.min(first.y2, second.y2) - Math.max(first.y1, second.y1));
  return overlapX * overlapY;
}

function evidenceDetailLabel(block: EvidenceItem, linkedToField: boolean, activeFieldLabel: string | undefined, config: EvidenceDisplayConfig) {
  if (linkedToField && activeFieldLabel) return activeFieldLabel;
  return evidenceSectionLabel(block.text, block.section_name, config);
}

function evidenceSectionLabel(text: string, fallback: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  const section = config.section_labels.find((label) => trimmed.startsWith(label));
  if (section) return section;
  const field = config.basic_field_labels.find((label) => new RegExp(`^${escapeRegExp(label)}\\s*[:：]`).test(trimmed));
  if (field) return field;
  if (fallback && !/OCR\s*原文/.test(fallback)) return fallback;
  return trimmed.includes("\n") ? "段落证据" : "文本证据";
}

function splitLeadingLabel(text: string) {
  const match = text.match(/^([^：:]{1,14}[：:])\s*(.*)$/);
  if (!match) return null;
  const label = match[1];
  return {
    end: label.length,
    label,
    value: match[2]
  };
}

function startsWithBasicField(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  return config.basic_field_labels.some((label) => new RegExp(`^${escapeRegExp(label)}\\s*[:：]`).test(trimmed));
}

function startsWithSectionHeading(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  return config.section_labels.some((label) => trimmed.startsWith(label));
}

function continuesCurrentSection(previousText: string, currentText: string, config: EvidenceDisplayConfig) {
  const previousSection = config.section_labels.find((label) => previousText.trim().startsWith(label));
  const currentSection = config.section_labels.find((label) => currentText.trim().startsWith(label));
  return Boolean(previousSection && currentSection && previousSection === currentSection);
}

function isStandaloneTitle(text: string) {
  const trimmed = text.trim();
  if (trimmed.length > 32) return false;
  if (/[:：。；;，,]/.test(trimmed)) return false;
  return true;
}

function isDocumentTitle(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  if (!isStandaloneTitle(trimmed)) return false;
  if (standaloneSectionMarker(trimmed, config)) return false;
  return config.document_title_patterns.some((pattern) => trimmed.includes(pattern));
}

function standaloneSectionMarker(text: string, config: EvidenceDisplayConfig) {
  const normalized = text.trim().replace(/[：:。；;\s]+$/g, "");
  return config.section_labels.includes(normalized) ? normalized : null;
}

function sectionTone(sectionName: string, config: EvidenceDisplayConfig) {
  for (const [tone, terms] of Object.entries(config.section_tones)) {
    if (terms.some((term) => sectionName.includes(term))) return tone;
  }
  return "default";
}

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

const DEFAULT_EVIDENCE_DISPLAY_CONFIG: EvidenceDisplayConfig = {
  basic_field_labels: BASIC_FIELD_LABELS,
  section_labels: SECTION_LABELS,
  inline_record_labels: INLINE_RECORD_LABELS,
  section_tones: {
    basic: ["基本", "首页", "信息", "姓名", "年龄", "性别"],
    present: ["主诉", "现病", "入院"],
    history: ["既往", "个人", "家族", "婚育", "月经", "病史"],
    diagnosis: ["诊断", "出院", "医嘱"],
    exam: ["检验", "检查", "影像", "化验", "体格", "专科", "辅助"]
  },
  document_title_patterns: ["病历", "病案", "入院记录", "出院记录", "病程记录", "手术记录", "首页"],
  common_ocr_repairs: [
    { pattern: "(BP\\s*[：:]?\\s*\\d+\\s*\\/\\s*\\d+\\s*mmHg)\\s*般状况", replacement: "$1 一般状况" },
    { pattern: "(^|[。；;！？\\s])般状况(?=\\s*[：:])", replacement: "$1一般状况" }
  ]
};

function mergeEvidenceDisplayConfig(config?: EvidenceDisplayConfig): EvidenceDisplayConfig {
  return {
    basic_field_labels: config?.basic_field_labels?.length ? config.basic_field_labels : DEFAULT_EVIDENCE_DISPLAY_CONFIG.basic_field_labels,
    section_labels: config?.section_labels?.length ? config.section_labels : DEFAULT_EVIDENCE_DISPLAY_CONFIG.section_labels,
    inline_record_labels: config?.inline_record_labels?.length ? config.inline_record_labels : DEFAULT_EVIDENCE_DISPLAY_CONFIG.inline_record_labels,
    section_tones: Object.keys(config?.section_tones ?? {}).length ? config!.section_tones : DEFAULT_EVIDENCE_DISPLAY_CONFIG.section_tones,
    document_title_patterns: config?.document_title_patterns?.length ? config.document_title_patterns : DEFAULT_EVIDENCE_DISPLAY_CONFIG.document_title_patterns,
    common_ocr_repairs: config?.common_ocr_repairs?.length ? config.common_ocr_repairs : DEFAULT_EVIDENCE_DISPLAY_CONFIG.common_ocr_repairs
  };
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

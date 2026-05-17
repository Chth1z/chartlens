import type { KeyboardEvent, ReactNode } from "react";
import type { EvidenceDisplayConfig } from "../../../shared/types/api";
import {
  clinicalLabelRanges,
  evidenceRange,
  evidenceSectionLabel,
  normalizeTranscriptDisplayText,
  sectionTone,
  splitLeadingLabel
} from "./evidenceText.js";
import type { EvidenceItem, EvidencePage } from "./types";

interface TranscriptViewProps {
  groupedEvidence: EvidencePage[];
  activeEvidenceKey: string | null;
  fieldEvidenceKey: string | null;
  activeEvidenceText: string;
  activeFieldLabel?: string;
  config: EvidenceDisplayConfig;
  bindActiveBlock: (node: HTMLElement | null) => void;
  onSelect: (key: string) => void;
}

export function TranscriptView({
  groupedEvidence,
  activeEvidenceKey,
  fieldEvidenceKey,
  activeEvidenceText,
  activeFieldLabel,
  config,
  bindActiveBlock,
  onSelect
}: TranscriptViewProps) {
  return (
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
              bindActiveBlock,
              fieldEvidenceKey,
              config,
              items: group.items,
              onSelect
            })}
          </div>
        </section>
      ))}
    </article>
  );
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
  ]
    .filter(Boolean)
    .join(" ");
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
      <span className="transcript-field-value">
        {renderTranscriptText(field.value || "未识别", evidenceText, active, config)}
      </span>
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
  const sortedCuts = Array.from(cuts)
    .filter((value) => value >= 0 && value <= text.length)
    .sort((left, right) => left - right);
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

function evidenceDetailLabel(block: EvidenceItem, linkedToField: boolean, activeFieldLabel: string | undefined, config: EvidenceDisplayConfig) {
  if (linkedToField && activeFieldLabel) return activeFieldLabel;
  return evidenceSectionLabel(block.text, block.section_name, config);
}

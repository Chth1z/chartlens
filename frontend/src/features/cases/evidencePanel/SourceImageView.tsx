import { useEffect, useRef } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { sourcePageImageUrl } from "../../../shared/api/client.js";
import type { EvidenceDisplayConfig } from "../../../shared/types/api";
import {
  bboxToImageRect,
  hasTextSelection,
  imageMetricsFromElement,
  imageRectStyle,
  imageRectToViewportPercent,
  imageStageStyle,
  inferBboxSpace,
  normalizeBbox,
  sourceImageStyle
} from "./evidenceGeometry.js";
import { evidenceSectionLabel, sectionTone } from "./evidenceText.js";
import { hasSourceDebugSignal, isSourceOverlayBlankClickClassName, sourceDebugBadges } from "./evidenceGrouping.js";
import type { BboxRect, EvidenceItem, EvidencePage, ImageMetrics, ImageRect } from "./types";

interface SourceImageViewProps {
  groupedEvidence: EvidencePage[];
  caseId?: string;
  activeEvidenceKey: string | null;
  fieldEvidenceKey: string | null;
  activeEvidenceText: string;
  activeFieldLabel?: string;
  config: EvidenceDisplayConfig;
  imageMetrics: Record<number, ImageMetrics>;
  sourceFailures: Record<number, boolean>;
  sourceRetryTokens: Record<number, number>;
  bindActiveBlock: (node: HTMLElement | null) => void;
  onSelect: (key: string) => void;
  onClearSelection: () => void;
  onImageError: (page: number) => void;
  onImageLoad: (page: number, metrics: ImageMetrics) => void;
  onImageRetry: (page: number) => void;
}

export function SourceImageView({
  groupedEvidence,
  caseId,
  activeEvidenceKey,
  fieldEvidenceKey,
  activeEvidenceText,
  activeFieldLabel,
  config,
  imageMetrics,
  sourceFailures,
  sourceRetryTokens,
  bindActiveBlock,
  onSelect,
  onClearSelection,
  onImageError,
  onImageLoad,
  onImageRetry
}: SourceImageViewProps) {
  return (
    <article className="document-sheet ocr-image-sheet">
      {groupedEvidence.map((group) => (
        <OcrImagePage
          activeEvidenceKey={activeEvidenceKey}
          activeEvidenceText={activeEvidenceText}
          activeFieldLabel={activeFieldLabel}
          bindActiveBlock={bindActiveBlock}
          caseId={caseId}
          config={config}
          fieldEvidenceKey={fieldEvidenceKey}
          group={group}
          imageMetrics={imageMetrics[group.page]}
          key={`${group.page}-${group.displayPage}`}
          onImageError={() => onImageError(group.page)}
          onImageLoad={(page, metrics) => onImageLoad(page, metrics)}
          onImageRetry={() => onImageRetry(group.page)}
          onClearSelection={onClearSelection}
          onSelect={onSelect}
          retryToken={sourceRetryTokens[group.page] ?? 0}
          sourceFailed={sourceFailures[group.page] ?? false}
        />
      ))}
    </article>
  );
}

function OcrImagePage({
  activeEvidenceKey,
  activeEvidenceText,
  activeFieldLabel,
  bindActiveBlock,
  caseId,
  config,
  fieldEvidenceKey,
  group,
  imageMetrics,
  onImageError,
  onImageLoad,
  onImageRetry,
  onClearSelection,
  onSelect,
  retryToken,
  sourceFailed
}: {
  activeEvidenceKey: string | null;
  activeEvidenceText: string;
  activeFieldLabel?: string;
  bindActiveBlock: (node: HTMLElement | null) => void;
  caseId?: string;
  config: EvidenceDisplayConfig;
  fieldEvidenceKey: string | null;
  group: EvidencePage;
  imageMetrics?: ImageMetrics;
  onImageError: () => void;
  onImageLoad: (page: number, metrics: ImageMetrics) => void;
  onImageRetry: () => void;
  onClearSelection: () => void;
  onSelect: (key: string) => void;
  retryToken: number;
  sourceFailed: boolean;
}) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const bboxSpace = inferBboxSpace(group.items, imageMetrics);
  const hasAnyBbox = group.items.some((item) => normalizeBbox(item.bbox) !== null);
  const boxes = group.items
    .map((item) => {
      const imageRect = bboxToImageRect(item.bbox, bboxSpace, imageMetrics);
      return {
        item,
        imageRect,
        rect: imageRectToViewportPercent(imageRect, imageMetrics?.viewport)
      };
    })
    .filter((entry): entry is { item: EvidenceItem; imageRect: BboxRect; rect: ImageRect } => entry.rect !== null && entry.imageRect !== null);
  const missingBoxCount = group.items.length - boxes.length;
  const hasSource = Boolean(caseId) && !sourceFailed;
  const sourceTextLines = group.items.map((item) => item.text.trim()).filter(Boolean);
  const handleSourceStageClick = (event: MouseEvent<HTMLDivElement>) => {
    if (hasTextSelection()) return;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.closest(".ocr-image-box") || target.closest("button")) return;
    if (isSourceOverlayBlankClickClassName(String(target.className))) onClearSelection();
  };

  useEffect(() => {
    const image = imageRef.current;
    if (!hasSource || imageMetrics || !image?.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) return;
    onImageLoad(group.page, imageMetricsFromElement(image));
  }, [group.page, hasSource, imageMetrics, onImageLoad, retryToken]);

  return (
    <section className="ocr-page ocr-image-page" aria-label={`第 ${group.displayPage} 页原图 OCR`}>
      <div className="ocr-page-marker">
        <span>第 {group.displayPage} 页</span>
        <small>{boxes.length} 个坐标框{missingBoxCount > 0 ? ` · ${missingBoxCount} 段无坐标` : ""}</small>
      </div>
      {group.sourceDebug && hasSourceDebugSignal(group.sourceDebug) && (
        <div className="ocr-source-debug-strip" aria-label={`第 ${group.displayPage} 页 OCR 调试摘要`}>
          {sourceDebugBadges(group.sourceDebug).map((badge) => (
            <span key={badge}>{badge}</span>
          ))}
          {group.sourceDebug.recommendedActions.length > 0 && (
            <strong>{group.sourceDebug.recommendedActions.slice(0, 2).join("；")}</strong>
          )}
        </div>
      )}
      <div className="ocr-image-stage" onClick={handleSourceStageClick} style={imageStageStyle(imageMetrics)}>
        {hasSource ? (
          <>
            <img
              alt={`第 ${group.displayPage} 页原图`}
              className="ocr-source-image"
              draggable={false}
              loading="lazy"
              onError={onImageError}
              onLoad={(event) => {
                const image = event.currentTarget;
                onImageLoad(group.page, imageMetricsFromElement(image));
              }}
              ref={imageRef}
              style={sourceImageStyle(imageMetrics)}
              src={sourcePageImageUrl(caseId!, group.page, retryToken)}
            />
            <div className="ocr-image-layer" aria-label={`第 ${group.displayPage} 页 OCR 坐标框`}>
              {boxes.map(({ imageRect, item, rect }) => {
                const active = item.key === activeEvidenceKey;
                const linkedToField = item.key === fieldEvidenceKey;
                const tone = sectionTone(`${item.section_name} ${item.text}`, config);
                const className = ["ocr-image-box", `section-${tone}`, active ? "active" : "", linkedToField ? "field-linked" : ""]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <span
                    aria-current={active ? "true" : undefined}
                    aria-label={`证据：${item.text}，置信度 ${Math.round(item.confidence * 100)}%`}
                    className={className}
                    key={item.key}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!hasTextSelection()) onSelect(item.key);
                    }}
                    onKeyDown={(event) => selectEvidenceOnKeyDown(event, () => onSelect(item.key))}
                    ref={active ? bindActiveBlock : undefined}
                    role="button"
                    style={imageRectStyle(rect, imageRect, imageMetrics)}
                    tabIndex={0}
                    title={item.text}
                  >
                    <span className="ocr-copy-text">{item.text}</span>
                    <span aria-hidden="true" className="ocr-image-box-label">
                      {evidenceDetailLabel(item, linkedToField, activeFieldLabel, config)} · {Math.round(item.confidence * 100)}%
                    </span>
                  </span>
                );
              })}
            </div>
          </>
        ) : (
          <div className="ocr-image-empty">
            <strong>原图预览不可用</strong>
            <span>当前文件页无法作为图片载入，仍可使用类 Word 视图完成同一套证据复核。</span>
            {caseId && (
              <button className="icon-button subtle" onClick={onImageRetry} type="button">
                重新加载原图
              </button>
            )}
          </div>
        )}
        {hasSource && boxes.length === 0 && hasAnyBbox && !imageMetrics && (
          <div className="ocr-image-empty floating compact">
            <span>正在读取原图尺寸以对齐 OCR 坐标。</span>
          </div>
        )}
        {hasSource && boxes.length === 0 && (!hasAnyBbox || imageMetrics) && (
          <div className="ocr-image-empty floating">
            <strong>当前页没有可用坐标框</strong>
            <span>OCR 结果未返回文字坐标，因此不会在原图上伪造高亮。</span>
          </div>
        )}
        {hasSource && boxes.length > 0 && activeEvidenceText && !fieldEvidenceKey && (
          <div className="ocr-image-empty floating compact">
            <span>当前字段未匹配到原图坐标，已保留手动框选能力。</span>
          </div>
        )}
      </div>
      {sourceTextLines.length > 0 && (
        <div className="ocr-source-text-panel" aria-label={`第 ${group.displayPage} 页 OCR 识别文字`}>
          <div className="ocr-source-text-title">识别文字</div>
          <div className="ocr-source-text-body">
            {sourceTextLines.map((line, index) => (
              <p key={`${group.page}-source-text-${index}`}>{line}</p>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function selectEvidenceOnKeyDown(event: KeyboardEvent<HTMLElement>, select: () => void) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  select();
}

function evidenceDetailLabel(
  block: EvidenceItem,
  linkedToField: boolean,
  activeFieldLabel: string | undefined,
  config: EvidenceDisplayConfig
) {
  if (linkedToField && activeFieldLabel) return activeFieldLabel;
  return evidenceSectionLabel(block.text, block.section_name, config);
}

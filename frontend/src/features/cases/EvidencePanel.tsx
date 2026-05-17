import { memo, useEffect, useMemo, useRef, useState } from "react";
import { FileImage, FileText } from "lucide-react";
import type { DocumentFragment, EvidenceDisplayConfig, FieldResult } from "../../shared/types/api";
import { mergeEvidenceDisplayConfig } from "./evidencePanel/defaultDisplayConfig.js";
import { findBboxEvidenceKey } from "./evidencePanel/evidenceGeometry.js";
import {
  groupEvidenceByPage,
  groupSourceEvidenceByPage,
  sourceEvidenceImageStateKey
} from "./evidencePanel/evidenceGrouping.js";
import { findActiveEvidenceKey } from "./evidencePanel/evidenceText.js";
import { SourceImageView } from "./evidencePanel/SourceImageView.js";
import { TranscriptView } from "./evidencePanel/TranscriptView.js";
import type { EvidenceViewMode, ImageMetrics } from "./evidencePanel/types";

// Re-exports kept for tests and any external consumer that imported helpers from this path.
export {
  groupEvidenceByPage,
  groupSourceEvidenceByPage,
  sourceEvidenceImageStateKey,
  isSourceOverlayBlankClickClassName
} from "./evidencePanel/evidenceGrouping.js";

interface EvidencePanelProps {
  caseId?: string;
  evidenceItems: DocumentFragment[];
  sourceEvidenceItems?: DocumentFragment[];
  activeResult?: FieldResult;
  activeFieldLabel?: string;
  displayConfig?: EvidenceDisplayConfig;
}

const SOURCE_IMAGE_AUTO_RETRIES = 2;

export const EvidencePanel = memo(function EvidencePanel({
  caseId,
  evidenceItems,
  sourceEvidenceItems,
  activeResult,
  activeFieldLabel,
  displayConfig
}: EvidencePanelProps) {
  const activeBlockRef = useRef<HTMLElement | null>(null);
  const documentPageRef = useRef<HTMLDivElement | null>(null);
  const [selectedTranscriptEvidenceKey, setSelectedTranscriptEvidenceKey] = useState<string | null>(null);
  const [selectedSourceEvidenceKey, setSelectedSourceEvidenceKey] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<EvidenceViewMode>("transcript");
  const [imageMetrics, setImageMetrics] = useState<Record<number, ImageMetrics>>({});
  const [sourceFailures, setSourceFailures] = useState<Record<number, boolean>>({});
  const [sourceRetryTokens, setSourceRetryTokens] = useState<Record<number, number>>({});

  const config = useMemo(() => mergeEvidenceDisplayConfig(displayConfig), [displayConfig]);
  const activeEvidenceText = activeResult?.evidence_span ?? activeResult?.evidence_text ?? "";
  const activePage = activeResult?.page ?? null;
  const activeBbox = activeResult?.bbox ?? [];

  const groupedEvidence = useMemo(() => groupEvidenceByPage(evidenceItems, config), [evidenceItems, config]);
  const sourceGroupedEvidence = useMemo(
    () => groupSourceEvidenceByPage(sourceEvidenceItems?.length ? sourceEvidenceItems : evidenceItems, config),
    [config, evidenceItems, sourceEvidenceItems]
  );
  const sourceImageStateKey = useMemo(() => sourceEvidenceImageStateKey(sourceGroupedEvidence), [sourceGroupedEvidence]);
  const displayBlockCount = useMemo(
    () => groupedEvidence.reduce((total, group) => total + group.items.length, 0),
    [groupedEvidence]
  );
  const sourceBlockCount = useMemo(
    () => sourceGroupedEvidence.reduce((total, group) => total + group.items.length, 0),
    [sourceGroupedEvidence]
  );
  const fieldEvidenceKey = useMemo(
    () => findActiveEvidenceKey(groupedEvidence, activeEvidenceText, activePage, activeBbox, findBboxEvidenceKey),
    [activeBbox, activeEvidenceText, activePage, groupedEvidence]
  );
  const fieldSourceEvidenceKey = useMemo(
    () => findActiveEvidenceKey(sourceGroupedEvidence, activeEvidenceText, activePage, activeBbox, findBboxEvidenceKey),
    [activeBbox, activeEvidenceText, activePage, sourceGroupedEvidence]
  );
  const activeTranscriptEvidenceKey = selectedTranscriptEvidenceKey ?? fieldEvidenceKey;
  const activeSourceEvidenceKey = selectedSourceEvidenceKey === null ? fieldSourceEvidenceKey : selectedSourceEvidenceKey;
  const visiblePageCount = viewMode === "source" ? sourceGroupedEvidence.length : groupedEvidence.length;
  const visibleBlockCount = viewMode === "source" ? sourceBlockCount : displayBlockCount;

  useEffect(() => {
    setSelectedTranscriptEvidenceKey(null);
    setSelectedSourceEvidenceKey(null);
  }, [activeResult?.field_key, activeEvidenceText]);

  useEffect(() => {
    scrollEvidenceIntoPanel(activeBlockRef.current, documentPageRef.current);
  }, [activeSourceEvidenceKey, activeTranscriptEvidenceKey, viewMode]);

  useEffect(() => {
    setImageMetrics({});
    setSourceFailures({});
    setSourceRetryTokens({});
  }, [caseId, sourceImageStateKey]);

  const retrySourcePageImage = (page: number) => {
    setImageMetrics((current) => {
      if (!(page in current)) return current;
      const next = { ...current };
      delete next[page];
      return next;
    });
    setSourceFailures((current) => ({ ...current, [page]: false }));
    setSourceRetryTokens((current) => ({ ...current, [page]: (current[page] ?? 0) + 1 }));
  };

  const handleSourceImageError = (page: number) => {
    const currentRetryToken = sourceRetryTokens[page] ?? 0;
    if (currentRetryToken < SOURCE_IMAGE_AUTO_RETRIES) {
      retrySourcePageImage(page);
      return;
    }
    setSourceFailures((current) => ({ ...current, [page]: true }));
  };

  const bindActiveBlock = (node: HTMLElement | null) => {
    activeBlockRef.current = node;
  };

  return (
    <section className="document-panel">
      <div className="panel-title">
        <div className="document-title-copy">
          <span>智能文档解析</span>
          <small>{visiblePageCount} 页 / {visibleBlockCount} 段</small>
        </div>
        <div className="document-view-toggle" role="tablist" aria-label="智能文档解析显示方式">
          <button
            aria-selected={viewMode === "transcript"}
            className={viewMode === "transcript" ? "active" : ""}
            onClick={() => setViewMode("transcript")}
            role="tab"
            title="按类 Word 文档查看脱敏 OCR 证据"
            type="button"
          >
            <FileText size={15} /> 类 Word
          </button>
          <button
            aria-selected={viewMode === "source"}
            className={viewMode === "source" ? "active" : ""}
            onClick={() => setViewMode("source")}
            role="tab"
            title="在原图或页图上查看 OCR 坐标框"
            type="button"
          >
            <FileImage size={15} /> 原图 OCR
          </button>
        </div>
      </div>
      <div
        className={`document-page ${viewMode === "source" ? "ocr-image-page-wrap" : "transcript-page-wrap"}`}
        aria-label={viewMode === "source" ? "原图 OCR 坐标证据" : "脱敏智能文档解析证据"}
        ref={documentPageRef}
      >
        {evidenceItems.length === 0 && <div className="empty-state">暂无证据片段</div>}
        {evidenceItems.length > 0 && viewMode === "transcript" && (
          <TranscriptView
            activeEvidenceKey={activeTranscriptEvidenceKey}
            activeEvidenceText={activeEvidenceText}
            activeFieldLabel={activeFieldLabel}
            bindActiveBlock={bindActiveBlock}
            config={config}
            fieldEvidenceKey={fieldEvidenceKey}
            groupedEvidence={groupedEvidence}
            onSelect={setSelectedTranscriptEvidenceKey}
          />
        )}
        {evidenceItems.length > 0 && viewMode === "source" && (
          <SourceImageView
            activeEvidenceKey={activeSourceEvidenceKey}
            activeEvidenceText={activeEvidenceText}
            activeFieldLabel={activeFieldLabel}
            bindActiveBlock={bindActiveBlock}
            caseId={caseId}
            config={config}
            fieldEvidenceKey={fieldSourceEvidenceKey}
            groupedEvidence={sourceGroupedEvidence}
            imageMetrics={imageMetrics}
            onClearSelection={() => setSelectedSourceEvidenceKey("")}
            onImageError={handleSourceImageError}
            onImageLoad={(page, metrics) => {
              setSourceFailures((current) => ({ ...current, [page]: false }));
              setImageMetrics((current) => ({ ...current, [page]: metrics }));
            }}
            onImageRetry={retrySourcePageImage}
            onSelect={setSelectedSourceEvidenceKey}
            sourceFailures={sourceFailures}
            sourceRetryTokens={sourceRetryTokens}
          />
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

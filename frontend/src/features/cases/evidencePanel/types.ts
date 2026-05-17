import type { DocumentFragment } from "../../../shared/types/api";

export type EvidenceViewMode = "transcript" | "source";

export type EvidenceItem = DocumentFragment & {
  key: string;
};

export type SourceEvidenceItem = DocumentFragment & {
  sourceKey: string;
};

export type EvidencePage = {
  page: number;
  displayPage: number;
  items: EvidenceItem[];
  sourceDebug?: SourcePageDebug;
};

export type SourcePageDebug = {
  rawBlockCount: number;
  renderedBlockCount: number;
  hiddenEmptyTextCount: number;
  suppressedMeaninglessBoxCount: number;
  duplicateTextCount: number;
  edgeTouchingBoxCount: number;
  longBoxCount: number;
  lowConfidenceCount: number;
  recommendedActions: string[];
};

export type ImageSize = {
  width: number;
  height: number;
};

export type ImageMetrics = ImageSize & {
  viewport: BboxRect;
};

export type BboxSpace = {
  width: number;
  height: number;
};

export type ImageRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export type BboxRect = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export type OcrLineLike = {
  page: number;
  reading_order: number;
  text: string;
  bbox: number[];
  confidence: number;
  block_type: DocumentFragment["block_type"];
};

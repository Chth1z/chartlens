import type { CSSProperties } from "react";
import type {
  BboxRect,
  BboxSpace,
  EvidenceItem,
  EvidencePage,
  ImageMetrics,
  ImageRect,
  OcrLineLike
} from "./types";

export function normalizeBbox(bbox: number[]): BboxRect | null {
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

export function mergeBboxes(bboxes: number[][]) {
  const rects = bboxes.map((bbox) => normalizeBbox(bbox)).filter((rect): rect is BboxRect => rect !== null);
  if (rects.length === 0) return [];
  return [
    Math.min(...rects.map((rect) => rect.x1)),
    Math.min(...rects.map((rect) => rect.y1)),
    Math.max(...rects.map((rect) => rect.x2)),
    Math.max(...rects.map((rect) => rect.y2))
  ];
}

export function bboxIntersectionArea(first: BboxRect, second: BboxRect) {
  const overlapX = Math.max(0, Math.min(first.x2, second.x2) - Math.max(first.x1, second.x1));
  const overlapY = Math.max(0, Math.min(first.y2, second.y2) - Math.max(first.y1, second.y1));
  return overlapX * overlapY;
}

export function overlapLength(firstStart: number, firstEnd: number, secondStart: number, secondEnd: number) {
  return Math.max(0, Math.min(firstEnd, secondEnd) - Math.max(firstStart, secondStart));
}

export function clampPercent(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

export function inferBboxSpace(items: EvidenceItem[], imageMetrics?: ImageMetrics): BboxSpace | null {
  const rects = items.map((item) => normalizeBbox(item.bbox)).filter((rect): rect is BboxRect => rect !== null);
  if (rects.length === 0) return null;
  const maxX = Math.max(...rects.map((rect) => rect.x2));
  const maxY = Math.max(...rects.map((rect) => rect.y2));
  if (maxX <= 1.5 && maxY <= 1.5) return { width: 1, height: 1 };
  if (maxX <= 100 && maxY <= 100 && (maxX > 50 || maxY > 50)) return { width: 100, height: 100 };
  if (imageMetrics && maxX <= imageMetrics.width * 1.04 && maxY <= imageMetrics.height * 1.04) {
    return imageMetrics;
  }
  if (maxX <= 1000 && maxY <= 1000) return { width: 1000, height: 1000 };
  return imageMetrics ?? null;
}

export function bboxToImageRect(bbox: number[], space: BboxSpace | null, imageMetrics?: ImageMetrics): BboxRect | null {
  const rect = normalizeBbox(bbox);
  if (!rect || !space || !imageMetrics || space.width <= 0 || space.height <= 0) return null;
  const scaleX = imageMetrics.width / space.width;
  const scaleY = imageMetrics.height / space.height;
  return {
    x1: rect.x1 * scaleX,
    y1: rect.y1 * scaleY,
    x2: rect.x2 * scaleX,
    y2: rect.y2 * scaleY
  };
}

export function imageRectToViewportPercent(rect: BboxRect | null, viewport?: BboxRect): ImageRect | null {
  if (!rect || !viewport) return null;
  const viewportWidth = viewport.x2 - viewport.x1;
  const viewportHeight = viewport.y2 - viewport.y1;
  if (viewportWidth <= 0 || viewportHeight <= 0) return null;
  const left = clampPercent(((rect.x1 - viewport.x1) / viewportWidth) * 100);
  const top = clampPercent(((rect.y1 - viewport.y1) / viewportHeight) * 100);
  const right = clampPercent(((rect.x2 - viewport.x1) / viewportWidth) * 100);
  const bottom = clampPercent(((rect.y2 - viewport.y1) / viewportHeight) * 100);
  const width = Math.max(0.25, right - left);
  const height = Math.max(0.25, bottom - top);
  if (width <= 0 || height <= 0) return null;
  return { left, top, width, height };
}

export function imageRectStyle(rect: ImageRect, imageRect: BboxRect, imageMetrics?: ImageMetrics): CSSProperties {
  const fontSize = imageMetrics ? Math.max(7, Math.min(22, (imageRect.y2 - imageRect.y1) * 0.72)) : 12;
  return {
    left: `${rect.left}%`,
    top: `${rect.top}%`,
    width: `${rect.width}%`,
    height: `${rect.height}%`,
    fontSize: `${fontSize}px`
  };
}

export function imageStageStyle(imageMetrics?: ImageMetrics): CSSProperties {
  if (!imageMetrics) return {};
  const viewport = imageMetrics.viewport;
  return {
    aspectRatio: `${viewport.x2 - viewport.x1} / ${viewport.y2 - viewport.y1}`
  };
}

export function sourceImageStyle(imageMetrics?: ImageMetrics): CSSProperties {
  if (!imageMetrics) return {};
  const viewport = imageMetrics.viewport;
  const viewportWidth = viewport.x2 - viewport.x1;
  const viewportHeight = viewport.y2 - viewport.y1;
  if (viewportWidth <= 0 || viewportHeight <= 0) return {};
  return {
    left: `${(-viewport.x1 / viewportWidth) * 100}%`,
    top: `${(-viewport.y1 / viewportHeight) * 100}%`,
    width: `${(imageMetrics.width / viewportWidth) * 100}%`,
    height: `${(imageMetrics.height / viewportHeight) * 100}%`
  };
}

export function imageMetricsFromElement(image: HTMLImageElement): ImageMetrics {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  return {
    width,
    height,
    viewport: detectContentViewport(image) ?? { x1: 0, y1: 0, x2: width, y2: height }
  };
}

function detectContentViewport(image: HTMLImageElement): BboxRect | null {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (width <= 0 || height <= 0) return null;
  const maxCanvasSide = 900;
  const scale = Math.min(1, maxCanvasSide / Math.max(width, height));
  const canvasWidth = Math.max(1, Math.round(width * scale));
  const canvasHeight = Math.max(1, Math.round(height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = canvasWidth;
  canvas.height = canvasHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvasWidth, canvasHeight);
  context.drawImage(image, 0, 0, canvasWidth, canvasHeight);
  const data = context.getImageData(0, 0, canvasWidth, canvasHeight).data;
  let minX = canvasWidth;
  let minY = canvasHeight;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < canvasHeight; y += 1) {
    for (let x = 0; x < canvasWidth; x += 1) {
      const offset = (y * canvasWidth + x) * 4;
      if (!isContentPixel(data[offset], data[offset + 1], data[offset + 2], data[offset + 3])) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (maxX < minX || maxY < minY) return null;
  const margin = Math.max(24, Math.min(width, height) * 0.035);
  const rect = {
    x1: Math.max(0, minX / scale - margin),
    y1: Math.max(0, minY / scale - margin),
    x2: Math.min(width, (maxX + 1) / scale + margin),
    y2: Math.min(height, (maxY + 1) / scale + margin)
  };
  const cropArea = (rect.x2 - rect.x1) * (rect.y2 - rect.y1);
  const imageArea = width * height;
  if (cropArea / imageArea > 0.94) return null;
  return rect;
}

function isContentPixel(red: number, green: number, blue: number, alpha: number) {
  if (alpha < 12) return false;
  const darkest = Math.min(red, green, blue);
  const lightest = Math.max(red, green, blue);
  return darkest < 242 || lightest - darkest > 18;
}

export function findBboxEvidenceKey(groups: EvidencePage[], page: number | null, bbox: number[]) {
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

export function compareByPageAndPosition<T extends OcrLineLike>(left: T, right: T) {
  const leftRect = normalizeBbox(left.bbox);
  const rightRect = normalizeBbox(right.bbox);
  if (left.page !== right.page) return left.page - right.page;
  if (leftRect && rightRect) {
    const yDelta = leftRect.y1 - rightRect.y1;
    if (Math.abs(yDelta) > Math.max(10, Math.min(leftRect.y2 - leftRect.y1, rightRect.y2 - rightRect.y1) * 0.5)) {
      return yDelta;
    }
    return leftRect.x1 - rightRect.x1;
  }
  return left.reading_order - right.reading_order;
}

export function normalizeEvidencePage(page: number) {
  return Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
}

export function roundConfidence(value: number) {
  return Math.round(value * 10000) / 10000;
}

export function medianPositive(values: number[]) {
  const positive = values.filter((value) => Number.isFinite(value) && value > 0).sort((left, right) => left - right);
  if (positive.length === 0) return 1;
  return positive[Math.floor(positive.length / 2)];
}

export function hasTextSelection() {
  return (window.getSelection()?.toString().trim().length ?? 0) > 0;
}

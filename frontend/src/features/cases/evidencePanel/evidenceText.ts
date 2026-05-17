import type { EvidenceDisplayConfig } from "../../../shared/types/api";
import type { EvidencePage } from "./types";

export function normalizeEvidence(value: string | null | undefined) {
  return (value ?? "").replace(/\s+/g, "").trim();
}

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function comparableLineSignature(text: string) {
  return text
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[^\p{Letter}\p{Number}]/gu, "");
}

export function comparableOverlapText(text: string) {
  return text.normalize("NFKC").toLocaleLowerCase();
}

export function ngramSet(value: string) {
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

export function boundedEditDistance(left: string, right: string, maxDistance: number) {
  if (Math.abs(left.length - right.length) > maxDistance) return maxDistance + 1;
  let previous = new Array<number>(right.length + 1).fill(0).map((_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = new Array<number>(right.length + 1).fill(0);
    current[0] = leftIndex;
    let rowBest = current[0];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const substitutionCost = left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
      current[rightIndex] = Math.min(
        previous[rightIndex] + 1,
        current[rightIndex - 1] + 1,
        previous[rightIndex - 1] + substitutionCost
      );
      rowBest = Math.min(rowBest, current[rightIndex]);
    }
    if (rowBest > maxDistance) return maxDistance + 1;
    previous = current;
  }
  return previous[right.length] ?? maxDistance + 1;
}

export function alignedTextSimilarity(left: string, right: string) {
  if (left.length !== right.length || left.length === 0) return 0;
  let matching = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] === right[index]) matching += 1;
  }
  return matching / left.length;
}

export function longestCommonTextFragment(left: string, right: string, minSize: number) {
  let best: { leftIndex: number; rightIndex: number; size: number } | null = null;
  let previous = new Array<number>(right.length + 1).fill(0);
  for (let leftIndex = 0; leftIndex < left.length; leftIndex += 1) {
    const current = new Array<number>(right.length + 1).fill(0);
    for (let rightIndex = 0; rightIndex < right.length; rightIndex += 1) {
      if (left[leftIndex] !== right[rightIndex]) continue;
      const size = previous[rightIndex] + 1;
      current[rightIndex + 1] = size;
      if (size >= minSize && (!best || size > best.size)) {
        best = { leftIndex: leftIndex - size + 1, rightIndex: rightIndex - size + 1, size };
      }
    }
    previous = current;
  }
  return best;
}

export function isStrongEvidenceMatch(text: string, evidenceText: string) {
  const normalizedText = normalizeEvidence(text);
  const normalizedEvidence = normalizeEvidence(evidenceText);
  if (!normalizedText || !normalizedEvidence) return false;
  return normalizedText.includes(normalizedEvidence) || normalizedEvidence.includes(normalizedText);
}

export function evidenceRange(text: string, evidenceText: string) {
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

export function evidenceOverlapScore(text: string, evidenceText: string, sectionName: string) {
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

export function findActiveEvidenceKey(
  groups: EvidencePage[],
  evidenceText: string,
  page: number | null,
  bbox: number[],
  findBboxKey: (groups: EvidencePage[], page: number | null, bbox: number[]) => string | null
) {
  if (!evidenceText && page === null) return null;
  for (const group of groups) {
    for (const item of group.items) {
      if (isStrongEvidenceMatch(item.text, evidenceText)) return item.key;
    }
  }
  const textOverlapMatch = findTextOverlapEvidenceKey(groups, evidenceText, page);
  if (textOverlapMatch) return textOverlapMatch;
  if (evidenceText) return null;
  const bboxMatch = findBboxKey(groups, page, bbox);
  if (bboxMatch) return bboxMatch;
  return null;
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

// --- Same-line stitching helpers ---

export function mergeSameLineText(first: string, second: string): string | null {
  const left = first.trim();
  const right = second.trim();
  if (!left || !right) return null;
  if (left === right) return left;
  if (left.includes(right)) return left;
  if (right.includes(left)) return right;

  const fuzzyContained = mergeByFuzzySubstringContainment(left, right);
  if (fuzzyContained) return fuzzyContained;
  const nearDuplicate = mergeByNearDuplicateLineText(left, right);
  if (nearDuplicate) return nearDuplicate;
  const shortFuzzyContained = mergeByShortFuzzyContainment(left, right);
  if (shortFuzzyContained) return shortFuzzyContained;
  const direct = mergeByTextOverlap(left, right);
  if (direct) return direct;
  const fuzzyOverlap = mergeByFuzzyTextOverlap(left, right);
  if (fuzzyOverlap) return fuzzyOverlap;
  const anchored = mergeByCommonSubstring(left, right);
  if (anchored) return anchored;
  return null;
}

export function fieldLabelStart(text: string) {
  return fieldLabelsInText(text)[0] ?? null;
}

export function fieldLabelsInText(text: string) {
  const compact = text.normalize("NFKC").replace(/\s+/g, "").trim();
  return Array.from(compact.matchAll(/([\p{Letter}\p{Number}（）()·-]{1,12})[:：]/gu), (match) => match[1]);
}

function mergeByFuzzyTextOverlap(left: string, right: string): string | null {
  const maxOverlap = Math.min(left.length, right.length);
  for (let size = maxOverlap; size >= 8; size -= 1) {
    const leftSuffix = left.slice(-size);
    const rightPrefix = right.slice(0, size);
    const comparableLeft = comparableOverlapText(leftSuffix);
    const comparableRight = comparableOverlapText(rightPrefix);
    if (
      !comparableLeft ||
      !comparableRight ||
      comparableLeft[0] !== comparableRight[0] ||
      comparableLeft.at(-1) !== comparableRight.at(-1)
    ) {
      continue;
    }
    const maxEdits = Math.max(1, Math.ceil(size * 0.12));
    if (boundedEditDistance(comparableLeft, comparableRight, maxEdits) <= maxEdits) {
      return `${left}${right.slice(size)}`;
    }
  }
  return null;
}

function mergeByFuzzySubstringContainment(left: string, right: string): string | null {
  const leftSignature = comparableLineSignature(left);
  const rightSignature = comparableLineSignature(right);
  const minLength = Math.min(leftSignature.length, rightSignature.length);
  const maxLength = Math.max(leftSignature.length, rightSignature.length);
  if (minLength < 8 || maxLength <= minLength) return null;
  const [shortSignature, longSignature, longText] =
    leftSignature.length <= rightSignature.length
      ? [leftSignature, rightSignature, right]
      : [rightSignature, leftSignature, left];
  return isFuzzySignatureContained(shortSignature, longSignature) ? longText : null;
}

function isFuzzySignatureContained(shortSignature: string, longSignature: string) {
  const maxEdits = Math.max(2, Math.ceil(shortSignature.length * 0.12));
  const minWindow = Math.max(1, shortSignature.length - maxEdits);
  const maxWindow = Math.min(longSignature.length, shortSignature.length + maxEdits);
  for (let start = 0; start <= longSignature.length - minWindow; start += 1) {
    for (let size = minWindow; size <= maxWindow && start + size <= longSignature.length; size += 1) {
      if (boundedEditDistance(shortSignature, longSignature.slice(start, start + size), maxEdits) <= maxEdits) {
        return true;
      }
    }
  }
  return false;
}

function mergeByNearDuplicateLineText(left: string, right: string): string | null {
  const leftSignature = comparableLineSignature(left);
  const rightSignature = comparableLineSignature(right);
  const minLength = Math.min(leftSignature.length, rightSignature.length);
  const maxLength = Math.max(leftSignature.length, rightSignature.length);
  if (minLength < 8 || maxLength === 0 || minLength / maxLength < 0.82) return null;
  if (leftSignature === rightSignature) return preferredOcrLineVariant(left, right);
  const maxEdits = Math.max(2, Math.ceil(maxLength * 0.08));
  if (boundedEditDistance(leftSignature, rightSignature, maxEdits) <= maxEdits) return preferredOcrLineVariant(left, right);
  if (alignedTextSimilarity(leftSignature, rightSignature) >= 0.92) return preferredOcrLineVariant(left, right);
  const match = longestCommonTextFragment(leftSignature, rightSignature, Math.max(6, Math.floor(minLength * 0.84)));
  if (!match || match.size / minLength < 0.9) return null;
  return preferredOcrLineVariant(left, right);
}

function preferredOcrLineVariant(left: string, right: string) {
  const leftScore = ocrTextVariantScore(left);
  const rightScore = ocrTextVariantScore(right);
  if (Math.abs(leftScore - rightScore) > 0.1) return leftScore > rightScore ? left : right;
  if (left.length !== right.length) return left.length > right.length ? left : right;
  return left;
}

function ocrTextVariantScore(text: string) {
  let score = text.length / 200;
  const cjkPunctuation = text.match(/[，、。；：？！]/gu)?.length ?? 0;
  const asciiComma = text.match(/,/g)?.length ?? 0;
  const replacement = text.match(/\uFFFD/g)?.length ?? 0;
  const digitOneUnit = text.match(/[A-Za-zμΜ][\/／]1/gu)?.length ?? 0;
  score += cjkPunctuation * 2;
  score -= asciiComma * 1.8;
  score -= replacement * 5;
  score -= digitOneUnit * 4;
  return score;
}

function mergeByTextOverlap(left: string, right: string): string | null {
  const maxOverlap = Math.min(left.length, right.length);
  for (let size = maxOverlap; size >= 6; size -= 1) {
    if (left.slice(-size) === right.slice(0, size)) {
      return `${left}${right.slice(size)}`;
    }
  }
  return null;
}

function mergeByShortFuzzyContainment(left: string, right: string): string | null {
  const [short, long] = left.length <= right.length ? [left, right] : [right, left];
  if (short.length < 3 || short.length > 8 || long.length < short.length + 4) return null;
  const match = longestCommonTextFragment(long, short, Math.max(2, short.length - 1));
  if (!match) return null;
  const longTail = long.length - (match.leftIndex + match.size);
  const shortTail = short.length - (match.rightIndex + match.size);
  return longTail <= 1 && shortTail <= 1 ? long : null;
}

function mergeByCommonSubstring(left: string, right: string): string | null {
  const match = longestCommonTextFragment(left, right, 8);
  if (!match) return null;
  const leftTail = left.length - (match.leftIndex + match.size);
  const rightPrefixLimit = Math.max(2, Math.min(8, Math.floor(right.length / 6)));
  const leftTailLimit = Math.max(2, Math.min(12, Math.floor(left.length / 5)));
  if (match.rightIndex > rightPrefixLimit || leftTail > leftTailLimit) return null;

  const common = left.slice(match.leftIndex, match.leftIndex + match.size);
  const leftSuffix = left.slice(match.leftIndex + match.size);
  const rightSuffix = right.slice(match.rightIndex + match.size);
  let suffix = leftSuffix;
  if (!leftSuffix) {
    suffix = rightSuffix;
  } else if (!rightSuffix) {
    suffix = leftSuffix;
  } else if (rightSuffix.length >= leftSuffix.length + 2) {
    suffix = rightSuffix;
  } else if (leftSuffix.length >= rightSuffix.length + 2) {
    suffix = leftSuffix;
  }
  return `${left.slice(0, match.leftIndex)}${common}${suffix}`;
}

// --- Text classification helpers (page markers, stray symbols, metadata) ---

export function isLikelyPageMarkerText(text: string) {
  return /^[-–—]?\d{1,4}[-–—]?$/.test(text) || /^第\s*\d{1,4}\s*页$/.test(text);
}

export function isStrayStandaloneSymbolText(text: string) {
  return /^[□■☐☑][。．.，,、；;：:]?$/.test(text);
}

export function isInternalOcrMetadataText(text: string) {
  const normalized = text.normalize("NFKC").trim();
  if (!normalized) return false;
  return (
    /^canonical_selected$/i.test(normalized) ||
    /^canonical:\s*/i.test(normalized) ||
    /^candidate(_group)?_id[:=]/i.test(normalized) ||
    /^merge_flags?[:=]/i.test(normalized) ||
    /^conflict_flags?[:=]/i.test(normalized) ||
    /^layout_region_id[:=]/i.test(normalized) ||
    /^line_group_id[:=]/i.test(normalized) ||
    /^(pp_structure_v3|pp_ocr_v5|paddleocr_vl|paddleocr_hybrid|docling|document_ai_http):\d{3,}/i.test(normalized)
  );
}

export function isMeaninglessOverlayText(text: string) {
  const normalized = text.normalize("NFKC").trim();
  const comparable = normalizeEvidence(normalized);
  if (!comparable) return true;
  return (
    isInternalOcrMetadataText(normalized) ||
    isLikelyPageMarkerText(normalized) ||
    /^\d{1,4}[.．、]?$/.test(normalized) ||
    isStrayStandaloneSymbolText(normalized) ||
    /^[\p{P}\p{S}]{1,3}$/u.test(comparable) ||
    /^[A-Za-z]$/.test(comparable)
  );
}

// --- Section / display helpers used by both transcript and source views ---

export function isStandaloneTitle(text: string) {
  const trimmed = text.trim();
  if (trimmed.length > 32) return false;
  if (/[:：。；;，,]/.test(trimmed)) return false;
  return true;
}

export function isDocumentTitle(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  if (!isStandaloneTitle(trimmed)) return false;
  if (standaloneSectionMarker(trimmed, config)) return false;
  return config.document_title_patterns.some((pattern) => trimmed.includes(pattern));
}

export function standaloneSectionMarker(text: string, config: EvidenceDisplayConfig) {
  const normalized = text.trim().replace(/[：:。；;\s]+$/g, "");
  return config.section_labels.includes(normalized) ? normalized : null;
}

export function startsWithBasicField(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  return config.basic_field_labels.some((label) => new RegExp(`^${escapeRegExp(label)}\\s*[:：]`).test(trimmed));
}

export function startsWithSectionHeading(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  return config.section_labels.some((label) => trimmed.startsWith(label));
}

export function continuesCurrentSection(previousText: string, currentText: string, config: EvidenceDisplayConfig) {
  const previousSection = config.section_labels.find((label) => previousText.trim().startsWith(label));
  const currentSection = config.section_labels.find((label) => currentText.trim().startsWith(label));
  return Boolean(previousSection && currentSection && previousSection === currentSection);
}

export function evidenceSectionLabel(text: string, fallback: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  const section = config.section_labels.find((label) => trimmed.startsWith(label));
  if (section) return section;
  const field = config.basic_field_labels.find((label) => new RegExp(`^${escapeRegExp(label)}\\s*[:：]`).test(trimmed));
  if (field) return field;
  if (fallback && !/OCR\s*原文/.test(fallback)) return fallback;
  return trimmed.includes("\n") ? "段落证据" : "文本证据";
}

export function splitLeadingLabel(text: string) {
  const match = text.match(/^([^：:]{1,14}[：:])\s*(.*)$/);
  if (!match) return null;
  const label = match[1];
  return {
    end: label.length,
    label,
    value: match[2]
  };
}

export function sectionTone(sectionName: string, config: EvidenceDisplayConfig) {
  const trimmed = sectionName.trim();
  for (const [tone, terms] of Object.entries(config.section_tones)) {
    if (terms.some((term) => trimmed.startsWith(term))) return tone;
  }
  for (const [tone, terms] of Object.entries(config.section_tones)) {
    if (terms.some((term) => trimmed.includes(term))) return tone;
  }
  return "default";
}

export function basicFieldLabelsInText(text: string, config: EvidenceDisplayConfig) {
  return config.basic_field_labels.filter((label) => new RegExp(`${escapeRegExp(label)}\\s*[:：]`).test(text));
}

export function basicFieldLabelCount(text: string, config: EvidenceDisplayConfig) {
  return basicFieldLabelsInText(text, config).length;
}

export function repairCommonOcrText(text: string, config: EvidenceDisplayConfig) {
  return config.common_ocr_repairs.reduce((value, repair) => {
    try {
      return value.replace(new RegExp(repair.pattern, "giu"), repair.replacement);
    } catch {
      return value;
    }
  }, text);
}

export function clinicalLabelRanges(text: string, config: EvidenceDisplayConfig) {
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

export function normalizeSectionHeadingDelimiter(text: string, config: EvidenceDisplayConfig) {
  const trimmed = text.trim();
  const section = config.section_labels
    .slice()
    .sort((left, right) => right.length - left.length)
    .find((label) => trimmed.startsWith(label));
  if (!section || trimmed.length <= section.length) return text;
  const next = trimmed[section.length] ?? "";
  if (/[:：]/.test(next)) return text;
  if (!/[\s\u4e00-\u9fffA-Za-z0-9（(“"《]/.test(next)) return text;
  return `${section}：${trimmed.slice(section.length).trimStart()}`;
}

export function normalizeTranscriptDisplayText(
  text: string,
  sectionName: string,
  variant: "field" | "paragraph" | "title",
  config: EvidenceDisplayConfig
) {
  let normalized = repairCommonOcrText(text.trim(), config);
  if (variant === "paragraph" && evidenceSectionLabel(normalized, sectionName, config) === "体格检查") {
    normalized = normalized.replace(/^体格检查\s*[:：]?\s*(?=[TＴPBR一-龥])/u, "体格检查：");
    normalized = normalized.replace(/(体格检查：\s*)T\s*[:：]/u, "$1T：");
    normalized = normalized.replace(/\s+(P|R|BP)\s*[:：]/gu, " $1：");
  }
  return normalized;
}

export function joinParagraphText(lines: string[]) {
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

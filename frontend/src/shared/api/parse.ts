import type { z } from "zod";
import { ApiError } from "./apiError.js";

const CONTRACT_ERROR_STATUS = 502;

// Translate a zod parse failure into the project's standard contract error.
// The first issue's path and expectation is reported as
//   "<root>.<a>.<b> must be a <type>"
// to keep parity with the previous hand-written validators (and the existing
// tests asserting on those exact messages).
export function parse<T>(schema: z.ZodType<T>, payload: unknown, label: string): T {
  const result = schema.safeParse(payload);
  if (!result.success) {
    const issue = result.error.issues[0];
    const message = issueMessage(label, issue);
    throw new ApiError(CONTRACT_ERROR_STATUS, message, payload);
  }
  return result.data;
}

function issueMessage(label: string, issue: z.core.$ZodIssue | undefined): string {
  if (!issue) {
    return `${label} response is invalid`;
  }
  const path = [label, ...issue.path.map((segment) => formatPathSegment(segment))]
    .filter((part) => part !== "")
    .join("");
  if (issue.code === "invalid_type") {
    return `${normalizeJoinedPath(path)} must be ${describeExpected(issue)}`;
  }
  if (issue.code === "unrecognized_keys") {
    return `${normalizeJoinedPath(path)} contains unrecognized keys`;
  }
  if (issue.code === "invalid_value") {
    return `${normalizeJoinedPath(path)} has an unsupported value`;
  }
  if (issue.code === "invalid_union") {
    return `${normalizeJoinedPath(path)} did not match any expected shape`;
  }
  return `${normalizeJoinedPath(path)} ${issue.message ?? "is invalid"}`;
}

function formatPathSegment(segment: PropertyKey): string {
  if (typeof segment === "number") return `[${segment}]`;
  return `.${String(segment)}`;
}

function normalizeJoinedPath(path: string): string {
  // The first segment is the label; subsequent segments already carry a leading
  // "." or "[". Collapse a stray trailing dot for the bare-root case.
  return path.replace(/\.$/, "");
}

function describeExpected(issue: z.core.$ZodIssueInvalidType): string {
  const expected = issue.expected;
  if (expected === "array") return "an array";
  if (expected === "object") return "an object";
  if (expected === "string") return "a string";
  if (expected === "number") return "a number";
  if (expected === "boolean") return "a boolean";
  if (expected === "null") return "null";
  if (expected === "undefined") return "undefined";
  return `a ${expected}`;
}

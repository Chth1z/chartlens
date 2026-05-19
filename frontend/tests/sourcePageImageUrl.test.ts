import { describe, it, expect } from "vitest";
import { sourcePageImageUrl } from "../src/shared/api/client";

describe("sourcePageImageUrl", () => {
  it("source page image URL must encode the case id", () => {
    expect(sourcePageImageUrl("CASE 1", 6)).toBe("/api/cases/CASE%201/source-pages/6");
  });

  it("source page image URL must support cache-busting retry tokens", () => {
    expect(sourcePageImageUrl("CASE 1", 6, 2)).toBe("/api/cases/CASE%201/source-pages/6?retry=2");
  });
});

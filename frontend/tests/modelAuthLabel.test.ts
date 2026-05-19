import { describe, it, expect } from "vitest";
import { confidenceBand, modelAuthLabel } from "../src/features/cases/status";

describe("modelAuthLabel", () => {
  it("dynamic DeepSeek provider ids should be labeled as DeepSeek", () => {
    expect(modelAuthLabel(null, "provider_deepseek_deepseek_v4_flash-chat")).toBe("DeepSeek");
  });

  it("runtime DeepSeek provider names should be labeled as DeepSeek", () => {
    expect(modelAuthLabel(null, "deepseek_v4_flash-chat")).toBe("DeepSeek");
  });

  it("local fallback route should still be labeled as fallback", () => {
    expect(modelAuthLabel(null, "local_after_model_fallback")).toBe("本地规则 fallback");
  });

  it("manual reviewed fields should have a distinct status band", () => {
    expect(
      confidenceBand({ validation_state: "reviewed", acceptance_reason: "manual_review", review_required: false, normalized_code: "2" } as any)
    ).toBe("manual_review");
  });
});

import { confidenceBand, modelAuthLabel } from "../src/features/cases/status.js";

function assertEqual(actual: string, expected: string, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

assertEqual(modelAuthLabel(null, "provider_deepseek_deepseek_v4_flash-chat"), "DeepSeek", "dynamic DeepSeek provider ids should be labeled as DeepSeek");
assertEqual(modelAuthLabel(null, "deepseek_v4_flash-chat"), "DeepSeek", "runtime DeepSeek provider names should be labeled as DeepSeek");
assertEqual(modelAuthLabel(null, "local_after_model_fallback"), "本地规则 fallback", "local fallback route should still be labeled as fallback");
assertEqual(
  confidenceBand({ validation_state: "reviewed", acceptance_reason: "manual_review", review_required: false, normalized_code: "2" } as any),
  "manual_review",
  "manual reviewed fields should have a distinct status band"
);

import { modelAuthLabel } from "../src/features/cases/status.js";

function assertEqual(actual: string, expected: string, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

assertEqual(modelAuthLabel(null, "provider_deepseek_deepseek_v4_flash-chat"), "DeepSeek", "dynamic DeepSeek provider ids should be labeled as DeepSeek");
assertEqual(modelAuthLabel(null, "deepseek_v4_flash-chat"), "DeepSeek", "runtime DeepSeek provider names should be labeled as DeepSeek");
assertEqual(modelAuthLabel(null, "local_after_model_fallback"), "本地规则 fallback", "local fallback route should still be labeled as fallback");

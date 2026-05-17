import { sourcePageImageUrl } from "../src/shared/api/client.js";

function assertEqual(actual: string, expected: string, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, received ${actual}`);
  }
}

assertEqual(
  sourcePageImageUrl("CASE 1", 6),
  "/api/cases/CASE%201/source-pages/6",
  "source page image URL must encode the case id"
);

assertEqual(
  sourcePageImageUrl("CASE 1", 6, 2),
  "/api/cases/CASE%201/source-pages/6?retry=2",
  "source page image URL must support cache-busting retry tokens"
);

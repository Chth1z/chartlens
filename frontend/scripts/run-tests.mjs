import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const testsDir = resolve(".tmp-frontend-tests/tests");
const testFiles = readdirSync(testsDir)
  .filter((name) => name.endsWith(".test.js"))
  .sort();

for (const file of testFiles) {
  await import(pathToFileURL(resolve(testsDir, file)).href);
  console.log(`ok ${file}`);
}

console.log(`${testFiles.length} frontend tests passed`);

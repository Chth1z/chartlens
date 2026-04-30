import { rmSync } from "node:fs";
import { resolve } from "node:path";

rmSync(resolve(".tmp-frontend-tests"), { recursive: true, force: true });

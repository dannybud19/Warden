import { copyFileSync, existsSync, mkdirSync } from "node:fs";
const src = "../fixtures/reports/full_case.json";
const dst = "src/mocks/full_case.json";
mkdirSync("src/mocks", { recursive: true });
if (existsSync(src)) copyFileSync(src, dst);
else console.warn(`[copy-fixture] ${src} not found; mock mode will be empty`);

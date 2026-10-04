// Writes src/version.ts from package.json so the UI can detect a stale cached bundle.
import { readFileSync, writeFileSync } from "node:fs";
const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
writeFileSync(new URL("../src/version.ts", import.meta.url), `export const FRONTEND_VERSION = "${version}";\n`);

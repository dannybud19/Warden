import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

// Load production modules using the compiler already installed by the app, without a test framework.
export const load = createRequire(import.meta.url);
const compile = (module, filename) => {
  const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  });
  // Match the app's @/ alias and JSON default imports when testing its real API client.
  const require = module.require.bind(module);
  module.require = (name) => require(name.startsWith("@/")
    ? fileURLToPath(new URL(`../src/${name.slice(2)}`, import.meta.url)) : name);
  module._compile(outputText, filename);
};
load.extensions[".ts"] = compile;
load.extensions[".tsx"] = compile;

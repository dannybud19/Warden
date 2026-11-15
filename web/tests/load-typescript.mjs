import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";

// Load production modules using the compiler already installed by the app, without a test framework.
export const load = createRequire(import.meta.url);
const compile = (module, filename) => {
  const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX,
    },
  });
  module._compile(outputText, filename);
};
load.extensions[".ts"] = compile;
load.extensions[".tsx"] = compile;

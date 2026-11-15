import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { load } from "./load-typescript.mjs";

const { mood, riskDisplay, verificationProgress } = load("../src/lib/present.ts");
const { RiskGauge } = load("../src/components/warden/RiskGauge.tsx");
const makeCase = (extra = {}) => ({ checks: [], actions: [], reports: {}, score_history: [{ score: 100 }], ...extra });
const render = (c) => renderToStaticMarkup(createElement(RiskGauge, {
  risk: riskDisplay(c, mood(c, false)), progress: verificationProgress(c),
}));

test("the production dial shows unknown risk without a needle or a misleading numerical risk score", () => {
  const html = render(makeCase());
  assert.match(html, /Risk level: Unknown risk/);
  assert.match(html, />Unknown risk</);
  assert.doesNotMatch(html, /out of 100|\/100|fill="#17393e"/);
  assert.match(html, /role="progressbar"/);
  assert.match(html, /aria-label="Verification progress"/);
  assert.match(html, /aria-valuenow="0"/);
});

test("the independent progress bar displays 16 percent beneath a case whose remaining score is 84", () => {
  const html = render(makeCase({ score_history: [{ score: 84 }] }));
  assert.match(html, /Unknown risk/);
  assert.match(html, /aria-valuenow="16"/);
  assert.match(html, /16%/);
  assert.match(html, /width:16%/);
});

test("the production dial keeps a scam warning and high-risk needle even at 100 percent verification", () => {
  const html = render(makeCase({ decision: { verdict: "likely_scam" }, score_history: [{ score: 0 }] }));
  assert.match(html, /Risk level: High risk/);
  assert.match(html, /fill="#17393e"/);
  assert.match(html, /aria-valuenow="100"/);
  assert.match(html, /stroke="#e06a52" stroke-opacity="1"/);
});

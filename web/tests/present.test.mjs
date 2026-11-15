import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import ts from "typescript";

// Load the real presentation modules with the installed compiler; no browser or API is needed.
const load = createRequire(import.meta.url);
load.extensions[".ts"] = (module, filename) => {
  const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
  });
  module._compile(outputText, filename);
};
const { mood, riskDisplay, actionCardStatus } = load("../src/lib/present.ts");

const CHECKS = [
  "landlord_identity", "payment_safety", "right_to_let", "in_person_viewing",
  "contract_consistency", "deposit_protection", "no_pressure", "fair_price",
];
const makeCase = (overrides = {}) => ({
  checks: CHECKS.map((id) => ({ id, state: "unverified" })),
  actions: [], reports: {}, score_history: [], ...overrides,
});
const concern = { id: "payment", check_id: "payment_safety", supports: "suspicious", severity: "high", hard_flag: true };
const reports = (finding) => ({ message_checker: { findings: [finding] } });
const payment = { id: "act_confirm_payment_123", check_id: "payment_safety", status: "open" };

test("a fresh score of 100 is neutral, not a scam verdict", () => {
  const c = makeCase();
  assert.equal(mood(c, false).state, "default");
  assert.equal(riskDisplay(c, mood(c, false)).value, 100);
});

test("one cleared check does not make an incomplete case green", () => {
  const c = makeCase();
  c.checks[0].state = "cleared";
  assert.equal(mood(c, false).state, "default");
});

test("all eight cleared checks are required for green", () => {
  const c = makeCase({ checks: CHECKS.map((id) => ({ id, state: "cleared" })) });
  assert.equal(mood(c, false).state, "green");
  assert.notEqual(mood({ ...c, checks: c.checks.slice(0, 7) }, false).state, "green");
  assert.notEqual(mood({ ...c, checks: [] }, false).state, "green");
  assert.notEqual(mood({ ...c, checks: Array(8).fill(c.checks[0]) }, false).state, "green");
});

test("a positive verdict alone cannot paint missing checks green", () => {
  assert.equal(mood(makeCase({ decision: { verdict: "no_red_flags_remaining" } }), false).state, "default");
});

test("unverified is neutral; proceed with care is amber", () => {
  assert.equal(mood(makeCase({ decision: { verdict: "not_verified" } }), false).state, "default");
  assert.equal(mood(makeCase({ decision: { verdict: "proceed_with_care" } }), false).state, "amber");
});

test("ordinary payment questions do not imply a suspicious demand", () => {
  const c = makeCase({ actions: [{ ...payment, id: "act_payment_method" }] });
  assert.equal(mood(c, false).state, "default");
});

test("a targeted payment confirmation is amber even with a hard finding", () => {
  const c = makeCase({ actions: [payment], reports: reports(concern) });
  const status = mood(c, false);
  assert.equal(status.state, "stop");
  assert.equal(status.accent, "#d99a2b");
  assert.equal(status.title, "Don’t pay yet—confirm the payment request");
});

test("an unconfirmed hard finding alone cannot declare a likely scam", () => {
  assert.equal(mood(makeCase({ reports: reports(concern) }), false).state, "amber");
});

test("suspicious check states and flagged answers count without a report finding", () => {
  const c = makeCase();
  c.checks[1].state = "suspicious";
  assert.equal(mood(c, false).state, "amber");
  const answered = makeCase({ actions: [{ ...payment, status: "done", outcome: "flags" }] });
  assert.equal(mood(answered, false).state, "amber");
  assert.doesNotMatch(mood(answered, false).sub, /0 red flags/);
});

test("informational service errors do not imply fraud", () => {
  const c = makeCase({ reports: reports({ ...concern, hard_flag: false, severity: "info" }) });
  assert.equal(mood(c, false).state, "default");
});

test("a likely-scam verdict stays red during work or payment questions", () => {
  const c = makeCase({ decision: { verdict: "likely_scam" }, actions: [payment] });
  assert.equal(mood(c, false).state, "red");
  assert.equal(mood(c, true).state, "red");
});

test("checking does not hide an existing warning", () => {
  assert.equal(mood(makeCase(), true).state, "thinking");
  assert.equal(mood(makeCase({ actions: [payment] }), true).state, "stop");
  assert.equal(mood(makeCase({ reports: reports(concern) }), true).state, "amber");
});

test("the displayed score is exact in every colour and follows the latest snapshot", () => {
  const cases = [
    { decision: { verdict: "likely_scam" }, score: 12.34 },
    { reports: reports(concern), score: 95.45 },
    { checks: CHECKS.map((id) => ({ id, state: "cleared" })), score: 42.86 },
    { score: 87.65 },
  ];
  for (const { score, ...data } of cases) {
    const c = makeCase({ ...data, score_history: [{ score: 100 }, { score }] });
    const status = mood(c, false);
    const display = riskDisplay(c, status);
    assert.equal(display.value, score);
    assert.equal(display.headline, status.title);
    assert.equal(display.color, status.accent);
  }
});

test("a neutral or unparsed answer is answered, not cleared", () => {
  for (const outcome of ["neutral", null, undefined]) {
    assert.equal(actionCardStatus({ ...payment, status: "done", outcome }), "answered");
  }
});

test("action badges distinguish clear, flag, skip and open outcomes", () => {
  assert.equal(actionCardStatus({ ...payment, status: "done", outcome: "clears" }), "done");
  assert.equal(actionCardStatus({ ...payment, status: "done", outcome: "flags" }), "flagged");
  assert.equal(actionCardStatus({ ...payment, status: "skipped" }), "skipped");
  assert.equal(actionCardStatus({ ...payment, status: "impossible" }), "skipped");
  assert.equal(actionCardStatus(payment), "todo");
});

import assert from "node:assert/strict";
import test from "node:test";
import { load } from "./load-typescript.mjs";
const { mood, riskDisplay, verificationProgress, actionCardStatus } = load("../src/lib/present.ts");

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

test("a fresh case has unknown risk and zero verification progress", () => {
  const c = makeCase();
  assert.equal(mood(c, false).state, "default");
  const risk = riskDisplay(c, mood(c, false));
  assert.equal(risk.category, "unknown");
  assert.equal(risk.label, "Unknown risk");
  assert.equal(risk.needlePosition, null);
  assert.equal(verificationProgress(c), 0);
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

test("risk comes from findings and verdicts while progress follows the latest weighted score", () => {
  const cases = [
    { decision: { verdict: "likely_scam" }, score: 12.34, expectedRisk: "high", expectedProgress: 87.66 },
    { reports: reports(concern), score: 95.45, expectedRisk: "concerns", expectedProgress: 4.55 },
    { checks: CHECKS.map((id) => ({ id, state: "cleared" })), score: 42.86, expectedRisk: "no_red_flags", expectedProgress: 57.14 },
    { score: 87.65, expectedRisk: "unknown", expectedProgress: 12.35 },
  ];
  for (const { score, expectedRisk, expectedProgress, ...data } of cases) {
    const c = makeCase({ ...data, score_history: [{ score: 100 }, { score }] });
    const status = mood(c, false);
    const display = riskDisplay(c, status);
    assert.equal(display.category, expectedRisk);
    assert.equal(verificationProgress(c), expectedProgress);
    assert.equal(display.headline, status.title);
    assert.equal("value" in display, false); // no invented numerical risk probability
  }
});

test("a final scam verdict can have zero progress and a low remaining score never clears high risk", () => {
  for (const score of [100, 84, 0]) {
    const c = makeCase({ status: "decided", decision: { verdict: "likely_scam" }, score_history: [{ score }] });
    const display = riskDisplay(c, mood(c, false));
    assert.equal(display.category, "high");
    assert.equal(display.label, "High risk");
    assert.equal(verificationProgress(c), 100 - score);
  }
});

test("unknown stays neutral even after some verification, and a numeric score alone cannot clear risk", () => {
  const c = makeCase({ score_history: [{ score: 84 }] });
  c.checks[0].state = "cleared";
  assert.equal(verificationProgress(c), 16);
  assert.equal(riskDisplay(c, mood(c, false)).category, "unknown");
  c.score_history[0].score = 0;
  assert.equal(riskDisplay(c, mood(c, false)).category, "unknown");
});

test("payment confirmation and incomplete checks cannot become a green risk category", () => {
  const c = makeCase({ actions: [payment], reports: reports(concern) });
  assert.equal(riskDisplay(c, mood(c, false)).category, "concerns");
  const partial = makeCase({ checks: CHECKS.slice(0, 7).map((id) => ({ id, state: "cleared" })) });
  assert.equal(riskDisplay(partial, mood(partial, false)).category, "unknown");
  const cleared = makeCase({ checks: CHECKS.map((id) => ({ id, state: "cleared" })) });
  assert.equal(riskDisplay(cleared, mood(cleared, false)).label, "No red flags remaining");
});

test("a progress change cannot move the risk needle while the evidence and verdict stay the same", () => {
  for (const data of [{}, { reports: reports(concern) }, { decision: { verdict: "likely_scam" } }]) {
    const before = makeCase({ ...data, score_history: [{ score: 100 }] });
    const after = makeCase({ ...data, score_history: [{ score: 20 }] });
    const original = riskDisplay(before, mood(before, false));
    const changed = riskDisplay(after, mood(after, true));
    assert.equal(changed.category, original.category);
    assert.equal(changed.needlePosition, original.needlePosition);
  }
});

test("progress handles absent and invalid score snapshots without a broken bar", () => {
  assert.equal(verificationProgress(makeCase()), 0);
  for (const score of [NaN, Infinity]) assert.equal(verificationProgress(makeCase({ score_history: [{ score }] })), 0);
  assert.equal(verificationProgress(makeCase({ score_history: [{ score: -10 }] })), 100);
  assert.equal(verificationProgress(makeCase({ score_history: [{ score: 110 }] })), 0);
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

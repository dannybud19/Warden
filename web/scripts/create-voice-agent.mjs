// Creates (or updates) the "Warden home call" voice agent in your ElevenLabs account and writes its id
// to web/.env.local as ELEVENLABS_AGENT_ID.
//
//   1. Put ELEVENLABS_API_KEY=... in web/.env.local
//   2. cd web && node scripts/create-voice-agent.mjs
//
// Re-run any time you change the prompt or tools below: it updates the existing agent instead of
// making a new one, and replaces whatever was pasted in the ElevenLabs dashboard.
// Warden speaks with the "Sheldon" voice. Set ELEVENLABS_VOICE_ID to use a different one.
//
// The call (WS V): the agent asks the right questions with two client tools that run in the browser
// (CaseCall.tsx), never the backend. get_next_questions lists the case's open steps; record_answer
// keeps an answer in the browser. When the call ends the browser sends the transcript and answers
// to POST /cases/{id}/debrief once. The {{...}} variables are filled by the app at call start; the
// placeholders below are only for test calls in the dashboard.
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const ENV_FILE = new URL("../.env.local", import.meta.url);
const API = "https://api.elevenlabs.io";

function readEnv() {
  if (!existsSync(ENV_FILE)) return {};
  return Object.fromEntries(
    readFileSync(ENV_FILE, "utf8")
      .split("\n")
      .map((l) => l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/))
      .filter(Boolean)
      .map((m) => [m[1], m[2].replace(/^["']|["']$/g, "")]),
  );
}

function writeEnv(key, value) {
  const text = existsSync(ENV_FILE) ? readFileSync(ENV_FILE, "utf8") : "";
  const line = `${key}=${value}`;
  const next = new RegExp(`^${key}=.*$`, "m").test(text)
    ? text.replace(new RegExp(`^${key}=.*$`, "m"), line)
    : `${text.replace(/\n?$/, "\n")}${line}\n`;
  writeFileSync(ENV_FILE, next);
}

const env = { ...readEnv(), ...process.env };
const KEY = env.ELEVENLABS_API_KEY;
if (!KEY) {
  console.error("Missing ELEVENLABS_API_KEY. Add it to web/.env.local, then run this again.");
  process.exit(1);
}

async function api(path, init = {}) {
  const res = await fetch(API + path, {
    ...init,
    headers: { "xi-api-key": KEY, "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  const body = await res.text();
  if (!res.ok) throw new Error(`${init.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
  return body ? JSON.parse(body) : {};
}

// Warden's voice: "Sheldon".
const SHELDON = "uWNz6TbvrJHW6G4bBMPw";

function pickVoice() {
  if (env.ELEVENLABS_VOICE_ID) return { voice_id: env.ELEVENLABS_VOICE_ID, name: "(from ELEVENLABS_VOICE_ID)" };
  return { voice_id: SHELDON, name: "Sheldon" };
}

// ---- Warden's personality and job on a call about one home ----
// {{...}} values are filled in by the app at the start of every call.
const PROMPT = `You are Warden, a calm, friendly assistant helping a student in London check whether a rental is genuine before they pay anything. You are on a voice call with {{student_name}} about {{home}}.

What Warden knows so far:
- Current status: {{verdict}}
- Red flags so far: {{red_flags}}
- Checks: {{checks}}
- Most important open question: {{open_question}}
- Other open questions: {{open_questions}}

Your job on this call:
1. Let them tell their story first. Listen. Ask short follow-ups about anything no document would show: how they found the place, who they spoke to, whether they've seen it in person, whether anyone asked for money and how, any pressure to decide quickly, names, phone numbers, company names.
2. Then ask the open questions, one at a time. Call get_next_questions whenever you need the next one. Each line starts with an id (like act_viewing) or says "no id, just ask". Never read ids aloud, and ask each question only once.
3. When they answer a question that has an id, call record_answer with that exact action_id, their answer in their own words, and status "done" (or "skipped" if they can't or won't answer). Never call record_answer for a "no id" question or with an id you weren't given: just listen, because everything they say is checked after the call.
4. Don't decide anything during the call and never say a place is safe or definitely a scam. Say you'll check everything they said straight after the call.
5. Keep each turn under 25 words. Plain British English. No legal advice. Never ask for bank details, passwords or ID numbers, and don't repeat them back.
6. End by summarising in one sentence what you'll check, then say goodbye.`;

const FIRST_MESSAGE = "Hi {{student_name}}, it's Warden. Tell me what's happened with {{home}} so far, in your own words.";

// Both tools are answered in the browser from the case the page holds (no backend call during a call).
const GET_NEXT_QUESTIONS = {
  type: "client",
  name: "get_next_questions",
  description:
    "Get the next open questions to ask about this home. Returns one per line: '<n>. <action_id>: <question> (why: <reason>)' or '<n>. (no id, just ask) <question> (why: <reason>)'.",
  expects_response: true,
  response_timeout_secs: 10,
};

const RECORD_ANSWER = {
  type: "client",
  name: "record_answer",
  description:
    "Record the student's answer to one open question that has an id. It is kept in the browser and checked after the call.",
  expects_response: true,
  response_timeout_secs: 10,
  parameters: {
    type: "object",
    required: ["action_id", "answer"],
    properties: {
      action_id: { type: "string", description: "The id from get_next_questions, e.g. act_viewing." },
      answer: { type: "string", description: "The answer in the student's own words." },
      status: {
        type: "string",
        enum: ["done", "skipped"],
        description: "done when they answered, skipped when they can't or won't answer. Defaults to done.",
      },
    },
  },
};

// Test values for dashboard test calls only; real calls get the app's values.
const PLACEHOLDERS = {
  student_name: "Sam",
  home: "1 Test Street",
  verdict: "Unverified. Don't send any money until this is cleared.",
  red_flags: "none found so far",
  checks: "2 of 8 checks done",
  open_question: "Ask to view the property in person before paying anything. Did the agent agree?",
  open_questions:
    "1. act_viewing: Ask to view the property in person before paying anything. Did the agent agree? (why: In-person viewing)\n2. act_company_number: Ask the agent for their Companies House number. Did they give you one? (why: Landlord identity)",
};

const conversation_config = {
  agent: {
    first_message: FIRST_MESSAGE,
    language: "en",
    prompt: { prompt: PROMPT, tools: [GET_NEXT_QUESTIONS, RECORD_ANSWER] },
    dynamic_variables: { dynamic_variable_placeholders: PLACEHOLDERS },
  },
  // Spend credits carefully: no call can run longer than 5 minutes.
  conversation: { max_duration_seconds: 300 },
};

const voice = await pickVoice();
conversation_config.tts = { voice_id: voice.voice_id };
console.log(`Voice: ${voice.name} (${voice.voice_id})`);

let agentId = env.ELEVENLABS_AGENT_ID;
if (agentId) {
  await api(`/v1/convai/agents/${agentId}`, { method: "PATCH", body: JSON.stringify({ name: "Warden home call", conversation_config }) });
  console.log(`Updated agent ${agentId}`);
} else {
  const created = await api("/v1/convai/agents/create", { method: "POST", body: JSON.stringify({ name: "Warden home call", conversation_config }) });
  agentId = created.agent_id;
  writeEnv("ELEVENLABS_AGENT_ID", agentId);
  console.log(`Created agent ${agentId} and saved it to web/.env.local`);
}
console.log("Restart the web dev server so it picks up the new env values.");

// Creates (or updates) the "Warden home call" voice agent in your ElevenLabs account and writes its id
// to web/.env.local as ELEVENLABS_AGENT_ID.
//
//   1. Put ELEVENLABS_API_KEY=... in web/.env.local
//   2. cd web && node scripts/create-voice-agent.mjs
//
// Re-run any time you change the prompt below: it updates the existing agent instead of making a new one.
// Warden speaks with the "Sheldon" voice. Set ELEVENLABS_VOICE_ID to use a different one.
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
const PROMPT = `You are Warden, a warm, calm guide on a voice call with {{student_name}}, a renter (usually a student) checking one specific home before they pay anything. You lead a team of autonomous agents that have been checking this home.

What your agents know so far:
- Home: {{home}}
- Your current read: {{verdict}}
- Red flags found: {{red_flags}}
- Progress: {{checks}}
- The question you want them to ask the letting agent: {{open_question}}

Help them understand what the red flags mean in plain words, what to say to the letting agent, and what to do next. Keep every turn short: one or two sentences, at most one question. Reassure them, but never call a place safe and never tell them to pay; the best you ever say is "no red flags remaining". Only talk about what your agents found; if they ask about something not checked yet, say so and suggest adding the evidence on the page. British English, no lists read aloud.

If they tell you how the letting agent answered the open question, call record_answer with their answer in their own words, then tell them you've passed it to your team. Don't ask for bank, passport or ID details, and don't repeat sensitive details back. Keep the call under four minutes and finish warmly.`;

const FIRST_MESSAGE = "Hi {{student_name}}, it's Warden. I've been looking into {{home}} with my team. What's on your mind?";

const RECORD_ANSWER = {
  type: "client",
  name: "record_answer",
  description: "Record how the letting agent answered the open question, in the student's own words. Only when there is an open question and they've told you the reply.",
  expects_response: true,
  response_timeout_secs: 10,
  parameters: {
    type: "object",
    required: ["answer"],
    properties: { answer: { type: "string", description: "The letting agent's reply, as the student reported it." } },
  },
};

const conversation_config = {
  agent: {
    first_message: FIRST_MESSAGE,
    language: "en",
    prompt: { prompt: PROMPT, tools: [RECORD_ANSWER] },
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

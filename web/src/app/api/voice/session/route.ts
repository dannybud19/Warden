// Hands the browser a short-lived ElevenLabs conversation token for one call with Warden.
// The API key never leaves the server. POST so it is never cached.

export async function POST() {
  const key = process.env.ELEVENLABS_API_KEY;
  const agentId = process.env.ELEVENLABS_AGENT_ID;
  if (!key || !agentId) {
    return Response.json(
      { error: "Calling Warden isn't set up yet. Add ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID to web/.env.local." },
      { status: 503 },
    );
  }
  const res = await fetch(
    `https://api.elevenlabs.io/v1/convai/conversation/token?agent_id=${encodeURIComponent(agentId)}`,
    { headers: { "xi-api-key": key }, cache: "no-store" },
  );
  if (!res.ok) {
    return Response.json({ error: `ElevenLabs refused the call (${res.status}).` }, { status: 502 });
  }
  const { token } = (await res.json()) as { token?: string };
  if (!token) return Response.json({ error: "ElevenLabs returned no token." }, { status: 502 });
  return Response.json({ token });
}

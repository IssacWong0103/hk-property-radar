/* HK Property Radar — email-brief toggle API (Cloudflare Worker, free tier).
   The dashboard's Settings panel calls /subscribe, /unsubscribe, /status.
   Subscribers live in KV (binding SUBS); the scheduled send_email.py reads them. */
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};
const validEmail = (e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e || "");

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
    const json = (o, s = 200) =>
      new Response(JSON.stringify(o), { status: s, headers: { ...CORS, "Content-Type": "application/json" } });

    try {
      if (url.pathname === "/subscribe" && req.method === "POST") {
        const { email } = await req.json();
        if (!validEmail(email)) return json({ ok: false, error: "invalid email" }, 400);
        await env.SUBS.put("sub:" + email.toLowerCase(), JSON.stringify({ email, enabled: true, ts: Date.now() }));
        return json({ ok: true, enabled: true });
      }
      if (url.pathname === "/unsubscribe" && req.method === "POST") {
        const { email } = await req.json();
        if (!validEmail(email)) return json({ ok: false, error: "invalid email" }, 400);
        await env.SUBS.put("sub:" + email.toLowerCase(), JSON.stringify({ email, enabled: false, ts: Date.now() }));
        return json({ ok: true, enabled: false });
      }
      if (url.pathname === "/status" && req.method === "GET") {
        const email = (url.searchParams.get("email") || "").toLowerCase();
        const v = await env.SUBS.get("sub:" + email);
        return json({ ok: true, enabled: v ? JSON.parse(v).enabled : false });
      }
      return json({ ok: false, error: "not found" }, 404);
    } catch (e) {
      return json({ ok: false, error: String(e) }, 500);
    }
  },
};

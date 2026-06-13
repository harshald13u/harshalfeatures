// TEMPORARY: take the whole site offline. Public gets a 503 "back soon" page.
// To bring the site back: delete this file and push (or ask Claude to revert).
// Owner preview: append ?owner=hd-e1c1f15b4c67 to any URL (sets a 24h cookie to see the real site).
const OWNER_KEY = "hd-e1c1f15b4c67";
const OFFLINE_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Harshal Dasani — back soon</title>
<style>
:root{--bg:#0E0C0A;--ink:#ECE4D3;--mut:#8a8273;--gold:#d4a64a}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;text-align:center}
.wrap{max-width:560px}
.kick{letter-spacing:3px;text-transform:uppercase;font-size:12px;color:var(--gold);font-weight:700;margin-bottom:18px}
h1{font-family:Georgia,'Times New Roman',serif;font-weight:600;font-size:clamp(30px,6vw,52px);margin:0 0 14px;line-height:1.05}
p{color:var(--mut);font-size:16px;line-height:1.6;margin:0 auto;max-width:42ch}
.rule{width:54px;height:3px;background:var(--gold);border-radius:2px;margin:26px auto 0}
</style></head>
<body><div class="wrap">
<div class="kick">Harshal Dasani</div>
<h1>We'll be back soon.</h1>
<p>The site is temporarily offline for updates. Please check back shortly — thank you for your patience.</p>
<div class="rule"></div>
</div></body></html>`;

export async function onRequest(context){
  const url = new URL(context.request.url);
  const cookie = context.request.headers.get("cookie") || "";
  // Owner preview bypass
  if (url.searchParams.get("owner") === OWNER_KEY) {
    const res = await context.next();
    const out = new Response(res.body, res);
    out.headers.append("set-cookie", `hd_owner=${OWNER_KEY}; Path=/; Max-Age=86400; SameSite=Lax`);
    return out;
  }
  if (cookie.includes("hd_owner=" + OWNER_KEY)) {
    return context.next();
  }
  // Everyone else: offline
  return new Response(OFFLINE_HTML, { status: 503, headers: {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "no-store",
    "retry-after": "86400"
  }});
}

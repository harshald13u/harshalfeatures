// TEMPORARY: site hidden — public sees a plain "site does not exist" 404.
// Bring back: delete this file and push (or ask Claude to revert).
// Owner preview: append ?owner=hd-e1c1f15b4c67 to any URL (sets a 24h cookie to see the real site).
const OWNER_KEY = "hd-e1c1f15b4c67";
const NOT_FOUND_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Site not found</title>
<style>
html,body{height:100%;margin:0}
body{background:#fff;color:#3a3a3a;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;text-align:center}
.w{max-width:440px}
h1{font-size:46px;font-weight:700;margin:0 0 10px;letter-spacing:-1px;color:#222}
p{font-size:15px;line-height:1.6;color:#777;margin:0}
.s{font-size:13px;color:#aaa;margin-top:18px}
</style></head>
<body><div class="w">
<h1>404</h1>
<p>This site does not exist.</p>
<div class="s">The page you are looking for could not be found.</div>
</div></body></html>`;

export async function onRequest(context){
  const url = new URL(context.request.url);
  const cookie = context.request.headers.get("cookie") || "";
  if (url.searchParams.get("owner") === OWNER_KEY) {
    const res = await context.next();
    const out = new Response(res.body, res);
    out.headers.append("set-cookie", `hd_owner=${OWNER_KEY}; Path=/; Max-Age=86400; SameSite=Lax`);
    return out;
  }
  if (cookie.includes("hd_owner=" + OWNER_KEY)) {
    return context.next();
  }
  return new Response(NOT_FOUND_HTML, { status: 404, headers: {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "no-store"
  }});
}

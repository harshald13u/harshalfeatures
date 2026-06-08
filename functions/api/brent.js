// Cloudflare Pages Function — GET /api/brent
// Returns today's Brent crude price as JSON, fetched server-side (no CORS,
// no API key exposed). Used by the Oil-to-India tool.
//   default   -> edge-cached ~15 min (fast page loads)
//   ?fresh=1  -> bypass cache, fetch the very latest (used by Refresh)
// Source (pinned): Yahoo Finance front-month Brent (BZ=F). Fallback: Stooq (cb.f).
export async function onRequest(context) {
  const url = new URL(context.request.url);
  const fresh = url.searchParams.has('fresh');
  const H = {
    'content-type': 'application/json; charset=utf-8',
    'access-control-allow-origin': '*',
    'cache-control': fresh ? 'no-store' : 'public, max-age=900'
  };
  const cfOpt = fresh ? { cacheTtl: 0, cacheEverything: false }
                      : { cacheTtl: 900, cacheEverything: true };
  const bust = fresh ? ('&_=' + Date.now()) : '';

  // 1) Yahoo Finance — Brent front-month future (BZ=F)
  for (const host of ['query1', 'query2']) {
    try {
      const r = await fetch(
        'https://' + host + '.finance.yahoo.com/v8/finance/chart/BZ=F?interval=1d&range=1d' + bust,
        { headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' }, cf: cfOpt }
      );
      if (r.ok) {
        const j = await r.json();
        const m = j && j.chart && j.chart.result && j.chart.result[0] && j.chart.result[0].meta;
        if (m && typeof m.regularMarketPrice === 'number') {
          return new Response(JSON.stringify({
            price: m.regularMarketPrice,
            asOf: (m.regularMarketTime || 0) * 1000,
            currency: m.currency || 'USD',
            source: 'Yahoo Finance · Brent (BZ=F)',
            fresh: fresh
          }), { headers: H });
        }
      }
    } catch (e) { /* try next */ }
  }

  // 2) Stooq fallback — Brent continuous (cb.f), CSV: Symbol,Date,Time,Close
  try {
    const r = await fetch('https://stooq.com/q/l/?s=cb.f&f=sd2t2c&h&e=csv' + bust, { cf: cfOpt });
    if (r.ok) {
      const rows = (await r.text()).trim().split('\n');
      if (rows.length >= 2) {
        const c = rows[1].split(',');
        const close = parseFloat(c[c.length - 1]);
        if (isFinite(close) && close > 0) {
          const asOf = Date.parse((c[1] || '') + 'T' + (c[2] || '00:00:00') + 'Z');
          return new Response(JSON.stringify({
            price: close, asOf: isFinite(asOf) ? asOf : Date.now(),
            currency: 'USD', source: 'Stooq · Brent (cb.f)', fresh: fresh
          }), { headers: H });
        }
      }
    }
  } catch (e) { /* fall through */ }

  return new Response(JSON.stringify({ error: 'unavailable' }), { status: 502, headers: H });
}

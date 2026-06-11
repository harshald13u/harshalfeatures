// Cloudflare Pages Function — GET /api/fii-monthly
// Edge-fetches NSDL FPI net-investment (monthly, Rs cr: Equity + Total) so the
// /tools/fii-flows/ monthly auto-updater can pull it reliably (GitHub datacenter
// IPs are blocked by NSDL; the edge is not). ?debug=1 dumps structure for dev.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const SOURCES = [
  'https://www.fpi.nsdl.co.in/web/Reports/Yearwise.aspx?RptType=6',
  'https://www.fpi.nsdl.co.in/Reports/Yearwise.aspx?RptType=6',
  'https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx',
];
async function grab(u, fresh){
  const r = await fetch(u, { headers:{ 'User-Agent':UA, 'Accept':'text/html,application/xhtml+xml,*/*',
    'Accept-Language':'en-US,en;q=0.9', 'Referer':'https://www.fpi.nsdl.co.in/' },
    signal: AbortSignal.timeout(12000),
    cf: fresh?{cacheTtl:0}:{ cacheTtl:43200, cacheEverything:true } });
  return { ok:r.ok, status:r.status, url:u, html: await r.text() };
}
export async function onRequest(context){
  const url = new URL(context.request.url);
  const fresh = url.searchParams.has('fresh');
  const debug = url.searchParams.has('debug');
  const H = { 'content-type':'application/json; charset=utf-8','access-control-allow-origin':'*',
    'cache-control': fresh?'no-store':'public, max-age=43200, s-maxage=43200' };
  const tried=[];
  async function scan(useFresh){
    for(const u of SOURCES){
      try{
        const g = await grab(u, useFresh);
        tried.push({url:u, status:g.status, len:g.html.length, fresh:useFresh});
        if(!g.ok || g.html.length<500) continue;
        const year = detectYear(g.html);
        const months = parseNSDL(g.html, year);
        if(debug) return {debug:true, picked:u, status:g.status, len:g.html.length, detectedYear:year, count:months.length, months, freshPass:useFresh};
        if(months.length) return {source:u, fetchedAt:new Date().toISOString(), detectedYear:year, months, stale: !useFresh && fresh};
      }catch(e){ tried.push({url:u, error:String(e), fresh:useFresh}); }
    }
    return null;
  }
  // try the requested freshness first; if a fresh request fails (NSDL slow), fall back to the
  // edge-cached copy rather than erroring — the monthly updater calls ?fresh=1 and must not break.
  let res = await scan(fresh);
  if(!res && fresh) res = await scan(false);
  if(res) return new Response(JSON.stringify(res, debug?null:undefined, debug?2:undefined), {headers:H});
  return new Response(JSON.stringify({error:'NSDL unreachable/unparsed from edge', tried}), {status:502, headers:H});
}
const MON={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
function ymOf(t){
  const s=String(t).trim();
  let m=s.match(/^(\d{4})-(\d{1,2})$/); if(m) return `${m[1]}-${String(+m[2]).padStart(2,'0')}`;
  m=s.match(/([A-Za-z]{3,9})[\s\-\/]+(\d{2,4})/);
  if(m && MON[m[1].slice(0,3).toLowerCase()]){ let y=+m[2]; if(y<100)y+=2000; return `${y}-${String(MON[m[1].slice(0,3).toLowerCase()]).padStart(2,'0')}`; }
  return null;
}
function n(x){ if(x==null) return null; let t=String(x).replace(/[,₹\s]/g,'').replace(/−/g,'-'); let neg=false; if(/^\(.*\)$/.test(t)){neg=true;t=t.slice(1,-1);} if(t===''||t==='-') return null; const v=parseFloat(t); return isFinite(v)?(neg?-v:v):null; }
function stripTags(s){ return s.replace(/<[^>]+>/g,' ').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').trim(); }
function detectYear(html){
  let m=html.match(/value=['"]?(\d{4})['"]?\s+selected/i); if(m) return +m[1];
  m=html.match(/selected[^>]*>\s*(\d{4})\s*<\/option/i); if(m) return +m[1];
  m=html.match(/Calendar Year[^0-9]{0,40}(\d{4})/i); if(m) return +m[1];
  return new Date().getUTCFullYear();
}
const MONTHNAME={january:1,february:2,march:3,april:4,may:5,june:6,july:7,august:8,september:9,october:10,november:11,december:12};
function cellNum(x){ if(x==null) return null; let t=String(x).replace(/[,₹\s]/g,'').replace(/−/g,'-'); let neg=false; if(/^\(.*\)$/.test(t)){neg=true;t=t.slice(1,-1);} if(t===''||t==='-'||t==='NA') return null; const v=parseFloat(t); return isFinite(v)?(neg?-v:v):null; }
function rowCells(rowHtml){
  // split on <td/<th opening tags (NSDL omits closing tags)
  return rowHtml.split(/<t[dh][^>]*>/i).slice(1).map(c=>stripTags(c.split(/<\/?t[dh]/i)[0]));
}
function parseNSDL(html, year){
  // NSDL CY report: each data row = <month name> + 12 numeric cells (Equity..Total).
  // HTML omits </tr>/</td>, so split on the opening tags rather than match closed tags.
  const out={};
  const rows = html.split(/<tr[^>]*>/i).slice(1);    // each chunk = one row's content
  for(const r of rows){
    const cells = rowCells(r);
    if(cells.length<3) continue;
    const mo = MONTHNAME[String(cells[0]).trim().toLowerCase()];
    if(!mo) continue;
    const nums = cells.slice(1).map(cellNum).filter(v=>v!=null);
    if(nums.length<2) continue;
    const ym = `${year}-${String(mo).padStart(2,'0')}`;
    out[ym] = { ym, eq: Math.round(nums[0]), tot: Math.round(nums[nums.length-1]) };
  }
  return Object.values(out).sort((a,b)=>a.ym<b.ym?-1:1);
}

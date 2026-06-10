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
  for(const u of SOURCES){
    try{
      const g = await grab(u, fresh);
      tried.push({url:u, status:g.status, len:g.html.length});
      if(!g.ok || g.html.length<500) continue;
      if(debug){
        const html=g.html;
        const tables=(html.match(/<table/gi)||[]).length;
        const eqIdx=html.search(/equity/i);
        const snip = eqIdx>=0 ? html.slice(Math.max(0,eqIdx-400), eqIdx+1600) : html.slice(0,1600);
        return new Response(JSON.stringify({debug:true, picked:u, status:g.status, len:html.length,
          tables, eqIdx, snippet: snip.replace(/\s+/g,' ')}, null, 2), {headers:H});
      }
      const months = parseNSDL(g.html);
      if(months.length) return new Response(JSON.stringify({source:u, fetchedAt:new Date().toISOString(), months}), {headers:H});
    }catch(e){ tried.push({url:u, error:String(e)}); }
  }
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
function parseNSDL(html){
  // crude table parse: split rows, map header to find Rs-crore Equity + Total columns
  const out={};
  const tables=html.match(/<table[\s\S]*?<\/table>/gi)||[];
  for(const tbl of tables){
    const rows=tbl.match(/<tr[\s\S]*?<\/tr>/gi)||[];
    if(rows.length<3) continue;
    let eqCol=null, totCol=null, hdrRow=-1;
    for(let ri=0; ri<Math.min(4,rows.length); ri++){
      const cells=(rows[ri].match(/<t[hd][\s\S]*?<\/t[hd]>/gi)||[]).map(c=>stripTags(c).toLowerCase());
      if(!cells.length) continue;
      let ec=null, tc=null;
      cells.forEach((h,ci)=>{ if(/usd|us\$|\$/.test(h))return; if(ec==null && /equity/.test(h))ec=ci; if(/total|grand total/.test(h)||h==='net')tc=ci; });
      if(ec!=null && tc!=null){ eqCol=ec; totCol=tc; hdrRow=ri; break; }
    }
    if(hdrRow<0) continue;
    for(let ri=hdrRow+1; ri<rows.length; ri++){
      const cells=(rows[ri].match(/<t[hd][\s\S]*?<\/t[hd]>/gi)||[]).map(stripTags);
      if(cells.length<=Math.max(eqCol,totCol)) continue;
      const ym=ymOf(cells[0]); if(!ym) continue;
      const eq=n(cells[eqCol]), tot=n(cells[totCol]);
      if(eq==null||tot==null) continue;
      out[ym]={ym, eq:Math.round(eq), tot:Math.round(tot)};
    }
  }
  return Object.values(out).sort((a,b)=>a.ym<b.ym?-1:1);
}

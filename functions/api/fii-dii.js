// Cloudflare Pages Function — GET /api/fii-dii
// Robust multi-source FII/DII daily cash feed. Defense-in-depth so no single source can
// stall it:
//   • Groww   __NEXT_DATA__  -> ~21-day history (datacenter-friendly, ~1-day lag)
//   • Upstox  server table   -> independent history fallback (datacenter-friendly)
//   • NSE     fiidiiTradeReact -> SAME-DAY latest (authoritative); extends the series
// Merge by date (union), NSE leads same-day, cross-checked. Strict validation; never emits
// implausible numbers. Edge-cached ~30 min. ?fresh bypasses cache, ?debug shows per-source.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const CEIL = 100000; // |net| ceiling (Rs cr) — rejects F&O/parse bleed

const num = x => { if(x==null||x==='') return null; const n=parseFloat(String(x).replace(/[^0-9.\-]/g,'')); return isFinite(n)?n:null; };
const firstNum = (o,keys) => { for(const k of keys){ const v=num(o&&o[k]); if(v!=null) return v; } return null; };
function toISO(d){
  if(d==null) return null;
  if(typeof d==='number'){ const dt=new Date(d>1e12?d:d*1000); return isNaN(dt)?null:dt.toISOString().slice(0,10); }
  const s=String(d).trim();
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})/); if(m) return m[1]+'-'+m[2]+'-'+m[3];
  const MON={jan:'01',feb:'02',mar:'03',apr:'04',may:'05',jun:'06',jul:'07',aug:'08',sep:'09',oct:'10',nov:'11',dec:'12'};
  m=s.match(/(\d{1,2})[\s\-]([A-Za-z]{3})[A-Za-z]*[\s\-](\d{4})/); if(m){ const mo=MON[m[2].toLowerCase()]; if(mo) return m[3]+'-'+mo+'-'+String(m[1]).padStart(2,'0'); }
  m=s.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/); if(m) return m[3]+'-'+String(m[2]).padStart(2,'0')+'-'+String(m[1]).padStart(2,'0');
  const dt=new Date(s); return isNaN(dt)?null:dt.toISOString().slice(0,10);
}
function findSeries(node, depth){
  if(depth>10||node==null||typeof node!=='object') return null;
  if(Array.isArray(node)){
    if(node.length>=2 && node.every(it=>it&&typeof it==='object' && it.fii && (firstNum(it.fii,['netBuySell','net','netValue'])!=null))) return node;
    for(const it of node){ const r=findSeries(it,depth+1); if(r) return r; }
    return null;
  }
  for(const k in node){ const r=findSeries(node[k],depth+1); if(r) return r; }
  return null;
}
const side = o => ({ buy:firstNum(o,['grossBuy','buyValue','buy']), sell:firstNum(o,['grossSell','sellValue','sell']), net:firstNum(o,['netBuySell','net','netValue']) });

function clean(date, f, d, today){
  date=toISO(date); if(!date||date>today) return null;
  if(f.net==null && f.buy!=null && f.sell!=null) f.net=f.buy-f.sell;
  if(d.net==null && d.buy!=null && d.sell!=null) d.net=d.buy-d.sell;
  if(f.net==null||d.net==null) return null;
  if(Math.abs(f.net)>CEIL||Math.abs(d.net)>CEIL) return null;
  if(f.buy!=null&&f.sell!=null&&Math.abs((f.buy-f.sell)-f.net)>10){ f.buy=f.sell=null; }
  if(d.buy!=null&&d.sell!=null&&Math.abs((d.buy-d.sell)-d.net)>10){ d.buy=d.sell=null; }
  return {date, f, d};
}
const detail = r => (r.f.buy!=null?1:0)+(r.f.sell!=null?1:0)+(r.d.buy!=null?1:0)+(r.d.sell!=null?1:0);
async function getText(u, opt){ const r=await fetch(u, opt); if(!r.ok) throw new Error(u.split('?')[0]+' '+r.status); return r.text(); }

async function growwRows(fresh, today){
  const html=await getText('https://groww.in/fii-dii-data',
    { headers:{'User-Agent':UA,'Accept':'text/html,*/*','Accept-Language':'en-US,en;q=0.9'},
      signal:AbortSignal.timeout(8000), cf: fresh?{cacheTtl:0}:{cacheTtl:1800,cacheEverything:true} });
  const m=html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/); if(!m) throw new Error('groww no __NEXT_DATA__');
  const series=findSeries(JSON.parse(m[1]),0); if(!series) throw new Error('groww no series');
  const out=[]; for(const it of series){ const c=clean(it.date||it.tradeDate||it.day, side(it.fii), side(it.dii), today); if(c) out.push(c); }
  if(!out.length) throw new Error('groww empty'); return out;
}
function stripTags(s){ return s.replace(/<[^>]+>/g,' ').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').replace(/\s+/g,' ').trim(); }
async function upstoxRows(fresh, today){
  const html=await getText('https://upstox.com/fii-dii-data/',
    { headers:{'User-Agent':UA,'Accept':'text/html,*/*','Accept-Language':'en-US,en;q=0.9'},
      signal:AbortSignal.timeout(8000), cf: fresh?{cacheTtl:0}:{cacheTtl:1800,cacheEverything:true} });
  const tables=html.match(/<table[\s\S]*?<\/table>/gi)||[];
  for(const tbl of tables){
    const rows=tbl.match(/<tr[\s\S]*?<\/tr>/gi)||[]; if(rows.length<2) continue;
    const hdr=stripTags(rows[0]).toLowerCase();
    if(/%|long value|\bfut\b|\bopt\b/.test(hdr)) continue;
    if(!(hdr.includes('fii')&&hdr.includes('dii')&&hdr.includes('net purchase'))) continue;
    const out=[];
    for(let i=1;i<rows.length;i++){
      const cells=(rows[i].match(/<t[dh][\s\S]*?<\/t[dh]>/gi)||[]).map(stripTags);
      if(cells.length<7) continue;
      const c=clean(cells[0], {buy:num(cells[1]),sell:num(cells[2]),net:num(cells[3])},
                              {buy:num(cells[4]),sell:num(cells[5]),net:num(cells[6])}, today);
      if(c) out.push(c);
    }
    if(out.length) return out;
  }
  throw new Error('upstox no cash table');
}
async function nseRow(fresh, today){
  let lastErr=null;
  for(let attempt=0; attempt<2; attempt++){
    try{
      const boot=await fetch('https://www.nseindia.com/',{headers:{'User-Agent':UA,'Accept':'text/html,*/*','Accept-Language':'en-US,en;q=0.9'},signal:AbortSignal.timeout(4000),cf:{cacheTtl:0}});
      const sc=(boot.headers.getSetCookie?boot.headers.getSetCookie():[boot.headers.get('set-cookie')]).filter(Boolean);
      const cookie=sc.map(s=>String(s).split(';')[0]).join('; ');
      const nr=await fetch('https://www.nseindia.com/api/fiidiiTradeReact',{headers:{'User-Agent':UA,'Accept':'application/json','Referer':'https://www.nseindia.com/','Cookie':cookie},signal:AbortSignal.timeout(4000),cf:fresh?{cacheTtl:0}:{cacheTtl:1800}});
      if(!nr.ok){ lastErr=new Error('nse '+nr.status); continue; }
      const arr=await nr.json(); const A=Array.isArray(arr)?arr:[];
      const pick=re=>A.find(x=>re.test(x.category||''));
      const nf=pick(/FII|FPI/i), nd=pick(/DII/i);
      if(!nf||!nd){ lastErr=new Error('nse missing rows'); continue; }
      const c=clean(nf.date||nd.date, {buy:num(nf.buyValue),sell:num(nf.sellValue),net:num(nf.netValue)},
                                      {buy:num(nd.buyValue),sell:num(nd.sellValue),net:num(nd.netValue)}, today);
      if(c) return c; lastErr=new Error('nse unclean');
    }catch(e){ lastErr=e; }
  }
  throw lastErr||new Error('nse failed');
}

export async function onRequest(context){
  const url=new URL(context.request.url); const fresh=url.searchParams.has('fresh'); const debug=url.searchParams.has('debug');
  const H={ 'content-type':'application/json; charset=utf-8','access-control-allow-origin':'*',
    'cache-control': fresh?'no-store':'public, max-age=1800, s-maxage=1800' };
  const today=new Date().toISOString().slice(0,10);
  const dbg={};

  const [g,u,n]=await Promise.allSettled([ growwRows(fresh,today), upstoxRows(fresh,today), nseRow(fresh,today) ]);
  const groww = g.status==='fulfilled'? g.value : []; dbg.groww = g.status==='fulfilled'? `${groww.length} rows`:String(g.reason&&g.reason.message||g.reason);
  const upstox= u.status==='fulfilled'? u.value : []; dbg.upstox= u.status==='fulfilled'? `${upstox.length} rows`:String(u.reason&&u.reason.message||u.reason);
  const nse   = n.status==='fulfilled'? n.value : null; dbg.nse  = n.status==='fulfilled'? nse.date:String(n.reason&&n.reason.message||n.reason);

  const byDate=new Map();
  for(const r of groww) byDate.set(r.date, r);
  for(const r of upstox){ const e=byDate.get(r.date); if(!e || detail(r)>detail(e)) byDate.set(r.date, r); }
  const sourcesUsed=[]; if(groww.length)sourcesUsed.push('Groww'); if(upstox.length)sourcesUsed.push('Upstox');

  let confidence='single-source';
  if(nse){
    const e=byDate.get(nse.date);
    byDate.set(nse.date, e? {date:nse.date, f:{buy:nse.f.buy??e.f.buy, sell:nse.f.sell??e.f.sell, net:nse.f.net}, d:{buy:nse.d.buy??e.d.buy, sell:nse.d.sell??e.d.sell, net:nse.d.net}} : nse);
    if(!sourcesUsed.includes('NSE')) sourcesUsed.unshift('NSE');
    if(e) confidence = Math.abs(e.f.net-nse.f.net)<=Math.max(50,Math.abs(nse.f.net)*0.02)?'confirmed':'nse-leads';
    else confidence='confirmed';
  }

  const dates=[...byDate.keys()].sort();
  const history=dates.map((dt,i)=>{ const r=byDate.get(dt); return {date:dt, fii:{net:r.f.net}, dii:{net:r.d.net}, status: i===dates.length-1?'provisional':'final'}; });

  if(debug) return new Response(JSON.stringify({today, sources:dbg, used:sourcesUsed, latest:dates[dates.length-1]||null, count:history.length},null,2),{headers:H});
  if(!history.length){
    try{ const r=await fetch('https://harshaldasani.pages.dev/fii-dii/history.json',{cf:{cacheTtl:300}}); if(r.ok){ const j=await r.json(); if(j&&Array.isArray(j.history)&&j.history.length){ j.stale=true; return new Response(JSON.stringify(j),{headers:H}); } } }catch(e){}
    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), latest:null, history:[], error:'all sources failed', sources:dbg }),{status:200,headers:H});
  }

  const last=byDate.get(dates[dates.length-1]);
  const body={ lastUpdated:new Date().toISOString(),
    latest:{ date:last.date, status:'provisional', confidence, sources:sourcesUsed,
      fii:{buy:last.f.buy,sell:last.f.sell,net:last.f.net}, dii:{buy:last.d.buy,sell:last.d.sell,net:last.d.net} },
    history, fpi:null };
  return new Response(JSON.stringify(body),{headers:H});
}

// Cloudflare Pages Function — GET /api/fii-dii
// Daily FII/DII cash-market flows for /fii-dii/. Primary: Groww (groww.in/fii-dii-data,
// parse __NEXT_DATA__ -> ~20-day history with gross buy/sell + net). Opportunistic confirm:
// NSE fiidiiTradeReact (often 403s datacenter IPs -> stay single-source, never block).
// Strict validation; edge-cached ~30 min; educational data only, descriptive not prescriptive.
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const num = x => { if(x==null||x==='') return null; const n=parseFloat(String(x).replace(/[^0-9.\-]/g,'')); return isFinite(n)?n:null; };
const firstNum = (o,keys) => { for(const k of keys){ const v=num(o&&o[k]); if(v!=null) return v; } return null; };

function toISO(d){
  if(d==null) return null;
  if(typeof d==='number'){ const dt=new Date(d>1e12?d:d*1000); return isNaN(dt)?null:dt.toISOString().slice(0,10); }
  const s=String(d).trim();
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})/); if(m) return m[1]+'-'+m[2]+'-'+m[3];
  const MON={jan:'01',feb:'02',mar:'03',apr:'04',may:'05',jun:'06',jul:'07',aug:'08',sep:'09',oct:'10',nov:'11',dec:'12'};
  m=s.match(/(\d{1,2})[\s-]([A-Za-z]{3})[A-Za-z]*[\s-](\d{4})/); if(m){ const mo=MON[m[2].toLowerCase()]; if(mo) return m[3]+'-'+mo+'-'+String(m[1]).padStart(2,'0'); }
  const dt=new Date(s); return isNaN(dt)?null:dt.toISOString().slice(0,10);
}
// recursively find the daily series: an array whose items have an `fii` object with a net-ish number
function findSeries(node, depth){
  if(depth>8||node==null||typeof node!=='object') return null;
  if(Array.isArray(node)){
    if(node.length>=2 && node.every(it=>it&&typeof it==='object' && it.fii && (firstNum(it.fii,['netBuySell','net','netValue'])!=null))) return node;
    for(const it of node){ const r=findSeries(it,depth+1); if(r) return r; }
    return null;
  }
  for(const k in node){ const r=findSeries(node[k],depth+1); if(r) return r; }
  return null;
}
const side = o => ({ buy:firstNum(o,['grossBuy','buyValue','buy']), sell:firstNum(o,['grossSell','sellValue','sell']), net:firstNum(o,['netBuySell','net','netValue']) });

export async function onRequest(context){
  const url=new URL(context.request.url); const fresh=url.searchParams.has('fresh');
  const H={ 'content-type':'application/json; charset=utf-8','access-control-allow-origin':'*',
    'cache-control': fresh?'no-store':'public, max-age=1800, s-maxage=1800' };
  try{
    const gr=await fetch('https://groww.in/fii-dii-data',
      { headers:{ 'User-Agent':UA,'Accept':'text/html,*/*','Accept-Language':'en-US,en;q=0.9' },
        signal: AbortSignal.timeout(8000),
        cf: fresh?{cacheTtl:0}:{ cacheTtl:1800, cacheEverything:true } });
    if(!gr.ok) throw new Error('groww '+gr.status);
    const html=await gr.text();
    const m=html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
    if(!m) throw new Error('no __NEXT_DATA__');
    const series=findSeries(JSON.parse(m[1]),0);
    if(!series) throw new Error('no series');

    // normalise + STRICT validation
    const today=new Date().toISOString().slice(0,10); const seen=new Set(); const rows=[];
    for(const it of series){
      const date=toISO(it.date||it.tradeDate||it.day);
      if(!date || date>today || seen.has(date)) continue;
      const f=side(it.fii), d=side(it.dii);
      if(f.net==null||d.net==null) continue;
      if(Math.abs(f.net)>300000||Math.abs(d.net)>300000) continue;        // sanity ceiling
      if(f.buy!=null&&f.sell!=null&&Math.abs((f.buy-f.sell)-f.net)>2) continue;  // arithmetic gate
      if(d.buy!=null&&d.sell!=null&&Math.abs((d.buy-d.sell)-d.net)>2) continue;
      seen.add(date); rows.push({date,f,d});
    }
    if(!rows.length) throw new Error('no valid rows');
    rows.sort((a,b)=>a.date<b.date?-1:1);
    const history=rows.map((r,i)=>({date:r.date, fii:{net:r.f.net}, dii:{net:r.d.net}, status: i===rows.length-1?'provisional':'final'}));
    const last=rows[rows.length-1];
    let confidence='single-source', sources=['Groww · NSE-compiled data'];

    // NSE: confirm the latest day, OR extend the series when NSE leads Groww by a day
    // (NSE publishes provisional cash data the same evening; Groww often lags one day).
    try{
      let cookie='';
      const boot=await fetch('https://www.nseindia.com/',{headers:{'User-Agent':UA,'Accept':'text/html,*/*','Accept-Language':'en-US,en;q=0.9'},signal:AbortSignal.timeout(3500),cf:{cacheTtl:0}});
      const sc=(boot.headers.getSetCookie?boot.headers.getSetCookie():[boot.headers.get('set-cookie')]).filter(Boolean);
      cookie=sc.map(s=>String(s).split(';')[0]).join('; ');
      const nr=await fetch('https://www.nseindia.com/api/fiidiiTradeReact',{headers:{'User-Agent':UA,'Accept':'application/json','Referer':'https://www.nseindia.com/','Cookie':cookie},signal:AbortSignal.timeout(3500),cf:fresh?{cacheTtl:0}:{cacheTtl:1800}});
      if(nr.ok){
        const arr=await nr.json(); const A=Array.isArray(arr)?arr:[];
        if(url.searchParams.has('nsedbg')){ return new Response(JSON.stringify({grewLast:last.date, nseRaw:A.slice(0,6)},null,2),{headers:H}); }
        const pick=re=>A.find(x=>re.test(x.category||''));
        const nf=pick(/FII|FPI/i), nd=pick(/DII/i);
        if(nf){
          const ndate=toISO(nf.date)||(nd&&toISO(nd.date));
          const nfn=num(nf.netValue), nfb=num(nf.buyValue), nfs=num(nf.sellValue);
          const ddn=nd?num(nd.netValue):null, ddb=nd?num(nd.buyValue):null, dds=nd?num(nd.sellValue):null;
          if(ndate && nfn!=null){
            if(ndate>last.date && ddn!=null && ndate<=today && Math.abs(nfn)<=300000 && Math.abs(ddn)<=300000){
              // NSE has a newer day than Groww -> append it (NSE authoritative)
              if(history.length) history[history.length-1].status='final';
              history.push({date:ndate, fii:{net:nfn}, dii:{net:ddn}, status:'provisional'});
              last={date:ndate, f:{buy:nfb,sell:nfs,net:nfn}, d:{buy:ddb,sell:dds,net:ddn}};
              confidence='confirmed'; sources=['NSE','Groww'];
            } else if(ndate===last.date){
              if(Math.abs(nfn-last.f.net)<=Math.max(50,Math.abs(last.f.net)*0.01)){ confidence='confirmed'; sources=['Groww','NSE']; }
              else { confidence='divergent'; sources=['Groww','NSE']; }
            }
          }
        }
      }
    }catch(e){}

    const body={ lastUpdated:new Date().toISOString(),
      latest:{ date:last.date, status:'provisional', confidence, sources,
        fii:{buy:last.f.buy,sell:last.f.sell,net:last.f.net}, dii:{buy:last.d.buy,sell:last.d.sell,net:last.d.net} },
      history, fpi:null };
    return new Response(JSON.stringify(body),{headers:H});
  }catch(e){
    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), latest:null, history:[], error:String(e&&e.message||e) }),{status:200,headers:H});
  }
}

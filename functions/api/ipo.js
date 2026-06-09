// Cloudflare Pages Function — GET /api/ipo
// Live Indian IPO feed for /ipo/, assembled server-side from NSE public JSON
// (no key, no cost). Edge-cached ~15 min. Normalises to the dashboard schema:
//   { lastUpdated, source, ipos:[ {name,seg,status,ex,band,lot,min,size,type,dates,sub,listing} ] }
// Official data only — no GMP, no recommendations.

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const BASE = 'https://www.nseindia.com';
const MON = {JAN:0,FEB:1,MAR:2,APR:3,MAY:4,JUN:5,JUL:6,AUG:7,SEP:8,OCT:9,NOV:10,DEC:11};
const MONS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function istNow(){ return new Date(Date.now() + (330 - new Date().getTimezoneOffset()) * 60000); }
function parseDate(s){
  if(!s || s === '-') return null;
  const m = String(s).toUpperCase().match(/(\d{1,2})[-\s]([A-Z]{3})[-\s](\d{4})/);
  if(!m) return null; const mo = MON[m[2]]; if(mo == null) return null;
  return new Date(Date.UTC(+m[3], mo, +m[1]));
}
function pretty(d){ return d ? `${d.getUTCDate()} ${MONS[d.getUTCMonth()]}` : 'TBA'; }
function num(x){ if(x==null) return null; const n=parseFloat(String(x).replace(/[^0-9.eE+-]/g,'')); return isFinite(n)?n:null; }
function band(s){ if(!s) return null; const n=(String(s).match(/\d+(?:\.\d+)?/g)||[]).map(Number); if(!n.length) return null; return n.length===1?[n[0],n[0]]:[Math.min(n[0],n[1]),Math.max(n[0],n[1])]; }
function pick(o,keys){ for(const k of keys){ if(o&&o[k]!=null&&o[k]!==''&&o[k]!=='-') return o[k]; } return null; }
function isSME(s){ return /sme/i.test(String(s||'')); }
function exFor(sme){ return sme?['NSE SME']:['NSE','BSE']; }

async function jget(path, cookie){
  const r = await fetch(BASE+path, { headers:{ 'User-Agent':UA, 'Accept':'application/json, text/plain, */*',
    'Accept-Language':'en-US,en;q=0.9', 'Referer':BASE+'/market-data/all-upcoming-issues-ipo', 'Cookie':cookie||'' },
    cf:{ cacheTtl:0, cacheEverything:false } });
  if(!r.ok) throw new Error(path+' -> '+r.status);
  return r.json();
}
// subscription multiples from /api/ipo-active-category (srNo: 1=QIB, 2=NII, 3=RII, category 'Total'=overall)
function parseSub(j){
  const rows=(j&&j.dataList)||[]; const r2=x=>x==null?null:Math.round(x*100)/100;
  let mult={overall:null,qib:null,nii:null,ret:null}, bid={overall:null,qib:null,nii:null,ret:null}, offered=null;
  for(const r of rows){
    const sr=String(r.srNo||'').trim(), cat=String(r.category||'').toLowerCase();
    const m=num(r.noOfTotalMeant), b=num(r.noOfSharesBid), o=num(r.noOfShareOffered);
    if(cat==='total'){ mult.overall=m; bid.overall=b; offered=o; }
    else if(sr==='1'){ mult.qib=m; bid.qib=b; }
    else if(sr==='2'){ mult.nii=m; bid.nii=b; }
    else if(sr==='3'){ mult.ret=m; bid.ret=b; }
  }
  const maxMult=Math.max(mult.overall||0,mult.qib||0,mult.nii||0,mult.ret||0);
  if(maxMult>0) return { sub:{overall:r2(mult.overall),qib:r2(mult.qib),nii:r2(mult.nii),ret:r2(mult.ret)}, offered };
  const anyBid=(bid.overall||bid.qib||bid.nii||bid.ret);
  if(anyBid) return { sub:{pending:true, bidShares:bid.overall||null}, offered };  // NSE published bids but no offered-base (common for SME)
  return { sub:null, offered };
}

export async function onRequest(context){
  const url = new URL(context.request.url);
  const fresh = url.searchParams.has('fresh');
  const H = { 'content-type':'application/json; charset=utf-8', 'access-control-allow-origin':'*',
    'cache-control': fresh ? 'no-store' : 'public, max-age=900, s-maxage=900' };
  try {
    // bootstrap NSE cookie
    let cookie='';
    try {
      const boot = await fetch(BASE+'/market-data/all-upcoming-issues-ipo',
        { headers:{ 'User-Agent':UA, 'Accept':'text/html,*/*', 'Accept-Language':'en-US,en;q=0.9' }, cf:{cacheTtl:0} });
      const sc = (boot.headers.getSetCookie ? boot.headers.getSetCookie() : [boot.headers.get('set-cookie')]).filter(Boolean);
      cookie = sc.map(s=>String(s).split(';')[0]).join('; ');
    } catch(e){}

    const safe = p => jget(p,cookie).catch(()=>[]);
    const [upcoming, current, past] = await Promise.all([
      safe('/api/all-upcoming-issues?category=ipo'), safe('/api/ipo-current-issue'), safe('/api/public-past-issues') ]);

    const today = istNow(); today.setUTCHours(0,0,0,0);
    const map = new Map(); // symbol(or name) -> entry ; priority open/closing > upcoming > listed
    const PRI = { closing:0, open:1, upcoming:2, listed:3 };
    const add = e => { const k=(e.symbol||e.name||'').toUpperCase(); const ex=map.get(k);
      if(!ex || PRI[e.status] < PRI[ex.status]) map.set(k,e); };

    const mk = (r, status) => {
      const sme = isSME(pick(r,['series','securityType','marketType']));
      const open = parseDate(pick(r,['issueStartDate','ipoStartDate','startDate']));
      const close = parseDate(pick(r,['issueEndDate','ipoEndDate','endDate']));
      const list = parseDate(pick(r,['listingDate']));
      const bd = band(pick(r,['priceRange','priceBand','issuePrice']));
      const shares = num(pick(r,['issueSize','totalIssueSize','noOfSharesOffered']));
      let st = status;
      if(status==='open' && close && close.getTime()===today.getTime()) st='closing';
      return { name: pick(r,['companyName','company','name','symbol'])||'IPO', symbol: pick(r,['symbol'])||null,
        seg: sme?'sme':'mainboard', status: st, ex: exFor(sme), band: bd, lot: num(pick(r,['lotSize','minBidQuantity','marketLot','minOrderQuantity'])),
        size: (shares && bd) ? Math.round(shares*bd[1]/1e7*100)/100 : null, _shares: shares||null,
        type: pick(r,['issueType','type'])||'',
        dates: { open: pretty(open), close: pretty(close), listing: status==='listed'?pretty(list):undefined },
        sub: null, listing: (status==='listed') ? ((num(pick(r,['issuePrice']))!=null)?{issue:num(pick(r,['issuePrice']))}:null) : undefined };
    };

    for(const r of (Array.isArray(current)?current:[])) add(mk(r,'open'));
    for(const r of (Array.isArray(upcoming)?upcoming:[])) add(mk(r,'upcoming'));
    for(const r of (Array.isArray(past)?past:[]).slice(0,9)) add(mk(r,'listed'));

    let ipos = [...map.values()];
    // live subscription + true issue size for open/closing
    const openish = ipos.filter(i => (i.status==='open'||i.status==='closing') && i.symbol);
    await Promise.all(openish.map(async i => {
      try { const j = await jget('/api/ipo-active-category?symbol='+encodeURIComponent(i.symbol), cookie);
        const { sub, offered } = parseSub(j);
        if(sub) i.sub = sub;
        if((!i.size) && offered && i.band) i.size = Math.round(offered*i.band[1]/1e7*100)/100;
      } catch(e){}
    }));
    for(const i of ipos){ if(i.band && i.lot) i.min = Math.round(i.band[1]*i.lot); delete i._shares; }
    ipos.sort((a,b)=> (PRI[a.status]-PRI[b.status]));

    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), source:'NSE (public data)', ipos }), { headers:H });
  } catch(e){
    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), ipos:[], error:String(e&&e.message||e) }), { status:200, headers:H });
  }
}

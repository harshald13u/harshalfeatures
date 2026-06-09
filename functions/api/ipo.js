// Cloudflare Pages Function — GET /api/ipo
// Live Indian IPO feed for /ipo/ (mainboard + SME), compiled server-side from
// Chittorgarh's public report JSON (which itself aggregates BSE/NSE/SEBI bid data).
// Gives price band, issue size, dates, status and full category-wise subscription
// for BOTH mainboard and SME issues — the SME data the exchange APIs don't expose.
// No GMP, no recommendations. Edge-cached ~15 min. Graceful empty fallback.

const HOST = 'https://webnodejs.chittorgarh.com';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const MONS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function istNow(){ return new Date(Date.now() + (330 - new Date().getTimezoneOffset()) * 60000); }
function fyOf(d){ const y=d.getUTCFullYear(), m=d.getUTCMonth()+1; return m>=4 ? (y+'-'+String((y+1)%100).padStart(2,'0')) : ((y-1)+'-'+String(y%100).padStart(2,'0')); }
function stripHTML(s){ return String(s||'').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').trim(); }
function slugFrom(html){ const m=String(html||'').match(/\/ipo\/([a-z0-9-]+)\/\d+\//i); return m?m[1]:null; }
function idFrom(html){ const m=String(html||'').match(/\/ipo\/[a-z0-9-]+\/(\d+)\//i); return m?m[1]:null; }
function num(x){ if(x==null||x==='') return null; const n=parseFloat(String(x).replace(/[^0-9.\-]/g,'')); return isFinite(n)?n:null; }
function band(s){ if(!s) return null; const n=(String(s).match(/\d+(?:\.\d+)?/g)||[]).map(Number); if(!n.length) return null; return n.length===1?[n[0],n[0]]:[Math.min(n[0],n[1]),Math.max(n[0],n[1])]; }
function isoDate(s){ if(!s) return null; const d=new Date(s); return isNaN(d)?null:new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())); }
function pretty(d){ return d?(d.getUTCDate()+' '+MONS[d.getUTCMonth()]):'TBA'; }
function exFromListing(s, sme){ const t=String(s||'').toUpperCase();
  const out=[]; if(/NSE/.test(t)) out.push(sme?'NSE SME':'NSE'); if(/BSE/.test(t)) out.push(sme?'BSE SME':'BSE');
  return out.length?out:(sme?['SME']:['NSE','BSE']); }

async function cg(report, month, year, fy, cat, fresh, ttl){
  const url = HOST+'/cloud/report/data-read/'+report+'/1/'+month+'/'+year+'/'+fy+'/0/'+cat+'/0';
  const r = await fetch(url, { headers:{ 'User-Agent':UA, 'Accept':'application/json, text/plain, */*',
    'Accept-Language':'en-US,en;q=0.9', 'Referer':'https://www.chittorgarh.com/' }, cf: fresh?{cacheTtl:0,cacheEverything:false}:{ cacheTtl:(ttl||900), cacheEverything:true } });
  if(!r.ok) throw new Error(report+'/'+cat+' -> '+r.status);
  const j = await r.json();
  return (j && j.reportTableData) || [];
}

export async function onRequest(context){
  const url = new URL(context.request.url);
  const fresh = url.searchParams.has('fresh');
  const H = { 'content-type':'application/json; charset=utf-8', 'access-control-allow-origin':'*',
    'cache-control': fresh ? 'no-store' : 'public, max-age=1800, s-maxage=1800' };
  try {
    const now = istNow(); const today = new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),now.getUTCDate()));
    const year = now.getUTCFullYear(), month = now.getUTCMonth()+1, fy = fyOf(now);
    const safe = (rep,cat,ttl) => cg(rep,month,year,fy,cat,fresh,ttl).catch(()=>[]);
    // sequential — Chittorgarh throttles burst-parallel requests from one IP
    const listMain = await safe(82,'mainboard', 21600);  // band/dates/size: ~static -> 6h
    const listSme  = await safe(82,'sme', 21600);
    const subMain  = await safe(21,'mainboard', 1800);   // subscription: changes when open -> 30m
    const subSme   = await safe(21,'sme', 1800);

    // subscription map by ~id
    const subMap = new Map();
    for(const r of [...subMain, ...subSme]){
      const o = num(r['Total (x)']), q = num(r['QIB (x)']), ni = num(r['NII (x)']), rt = num(r['Retail (x)']);
      const key = r['~URLRewrite_Folder_Name'] || null;
      if(key && (o!=null||q!=null||ni!=null||rt!=null)) subMap.set(key, { overall:o, qib:q, nii:ni, ret:rt });
    }

    function build(rows, sme){
      const out=[];
      for(const r of rows){
        const bd = band(r['Issue Price (Rs.)']);
        const open = isoDate(r['~Issue_Open_Date']);
        const close = isoDate(r['~IssueCloseDate'] || r['~Issue_Close_Date']);
        const list = isoDate(r['~ListingDate'] || r['~IPO_Listing_date']);
        let status;
        if(open && today < open) status='upcoming';
        else if(open && close && today >= open && today <= close) status=(today.getTime()===close.getTime()?'closing':'open');
        else if(list && today >= list) status='listed';
        else if(close && today > close) status='listed';   // closed/awaiting -> show under listed
        else status='upcoming';
        const size = num(r['Total Issue Amount (Incl.Firm reservations) (Rs.cr.)']);
        const am = String(r['Company']||'').match(/<a[^>]*>([\s\S]*?)<\/a>/i);
        const cleanName = am ? stripHTML(am[1]) : (stripHTML(r['Company']).replace(/\s+(CT|P|U|NEW)$/,''));
        const e = { name: cleanName || (r['~compare_name']||'IPO').replace(/ IPO$/,''),
          slug: r['~URLRewrite_Folder_Name'] || slugFrom(r['Company']) || null,
          cgid: idFrom(r['Company']),
          symbol: (r['~nse_symbol']||'')||null, isin:(r['~isin']||'')||null,
          seg: sme?'sme':'mainboard', status, ex: exFromListing(r['Listing at'], sme),
          band: bd, lot:null, size: size,
          type: (r['Pricing Method']||'')||'',
          dates: { open: pretty(open), close: pretty(close), listing: list?pretty(list):undefined },
          sub: subMap.get(r['~URLRewrite_Folder_Name'] || slugFrom(r['Company'])) || null,
          listing: status==='listed' ? (bd?{issue:bd[1]}:null) : undefined,
          _ts: (list||close||open) ? (list||close||open).getTime() : 0 };
        out.push(e);
      }
      return out;
    }

    let ipos = [...build(listMain,false), ...build(listSme,true)];
    // cap recently-listed to the 12 most recent per segment to keep it tidy
    const live = ipos.filter(i=>i.status!=='listed');
    const listed = ipos.filter(i=>i.status==='listed').sort((a,b)=>b._ts-a._ts).slice(0, 18);
    ipos = [...live, ...listed];
    const PRI = { closing:0, open:1, upcoming:2, listed:3 };
    ipos.sort((a,b)=> (PRI[a.status]-PRI[b.status]));

    // lot size + min investment live only on each IPO's per-page. Fetch them for
    // open/upcoming AND recently-listed, parse the lot + stated min amount.
    async function lotFor(i){
      try{
        const r = await fetch('https://www.chittorgarh.com/ipo/'+i.slug+'/'+i.cgid+'/',
          { headers:{ 'User-Agent':UA, 'Accept':'text/html,*/*', 'Accept-Language':'en-US,en;q=0.9', 'Referer':'https://www.chittorgarh.com/' },
            cf: fresh?{cacheTtl:0}:{ cacheTtl:604800, cacheEverything:true } });  // lot is static -> 7d
        if(!r.ok) return; const raw = await r.text();
        const t = raw.replace(/<[^>]+>/g,' ').replace(/&#8377;|&#x20B9;/gi,'₹').replace(/\s+/g,' ');
        const lm = t.match(/(?:minimum order quantity is|lot size is|lot size for an application is)\s*([\d,]+)/i);
        const lot = lm ? num(lm[1]) : null;
        const mm = t.match(/minimum amount (?:required for application|of investment)[^₹]{0,40}₹\s*([\d,]+)/i);
        const minv = mm ? num(mm[1]) : (lot && i.band ? Math.round(lot * i.band[1]) : null);
        if(lot) i.lot = lot;
        if(minv && i.status!=='listed') i.min = minv;
      }catch(e){}
    }
    const want = ipos.filter(i => i.slug && i.cgid).slice(0, 30);
    const q = want.slice();
    await Promise.all(Array.from({length:3}, async () => { while(q.length){ const it=q.shift(); await lotFor(it); } }));
    for(const i of ipos){ delete i.cgid; delete i._ts; }
    const body = { lastUpdated:new Date().toISOString(), source:'Compiled from BSE & NSE public data', ipos };
    if(fresh) body._debug = { listMain:listMain.length, listSme:listSme.length, subMain:subMain.length, subSme:subSme.length };
    return new Response(JSON.stringify(body), { headers:H });
  } catch(e){
    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), ipos:[], error:String(e&&e.message||e) }), { status:200, headers:H });
  }
}

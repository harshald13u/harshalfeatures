// Cloudflare Pages Function — GET /api/ipo
// Live Indian IPO feed for /ipo/, assembled server-side from NSE's public JSON
// (no key, no cost). Edge-cached ~15 min. Normalises to the dashboard schema:
//   { lastUpdated, ipos:[ {name,seg,status,ex,band,lot,min,size,type,dates,sub,listing} ] }
// Official data only — no GMP, no recommendations. NSE needs a session cookie,
// so we bootstrap one from the public IPO page, then call the JSON endpoints.

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const BASE = 'https://www.nseindia.com';
const MON = {JAN:0,FEB:1,MAR:2,APR:3,MAY:4,JUN:5,JUL:6,AUG:7,SEP:8,OCT:9,NOV:10,DEC:11};
const MONS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function istNow(){ return new Date(Date.now() + (330 - new Date().getTimezoneOffset()) * 60000); }
function parseDate(s){ // "25-MAR-2026" or "25-Mar-2026" -> Date (IST midnight) | null
  if(!s || s === '-' ) return null;
  const m = String(s).toUpperCase().match(/(\d{1,2})[-\s]([A-Z]{3})[-\s](\d{4})/);
  if(!m) return null;
  const mo = MON[m[2]]; if(mo == null) return null;
  return new Date(Date.UTC(+m[3], mo, +m[1]));
}
function pretty(d){ return d ? `${d.getUTCDate()} ${MONS[d.getUTCMonth()]}` : 'TBA'; }
function num(x){ if(x==null) return null; const n=parseFloat(String(x).replace(/[^0-9.]/g,'')); return isFinite(n)?n:null; }
function band(s){ // "Rs.528 to Rs.555" | "528 - 555" -> [528,555] | null
  if(!s) return null;
  const nums=(String(s).match(/\d+(?:\.\d+)?/g)||[]).map(Number);
  if(!nums.length) return null;
  if(nums.length===1) return [nums[0],nums[0]];
  return [Math.min(nums[0],nums[1]), Math.max(nums[0],nums[1])];
}
function pick(o, keys){ for(const k of keys){ if(o && o[k]!=null && o[k]!=='' && o[k]!=='-') return o[k]; } return null; }
function isSME(s){ return /sme/i.test(String(s||'')); }
function exFor(seg, sme){ return sme ? [seg==='nse'?'NSE SME':'BSE SME'] : ['NSE','BSE']; }

async function jget(path, cookie){
  const r = await fetch(BASE + path, {
    headers: { 'User-Agent': UA, 'Accept': 'application/json, text/plain, */*',
      'Accept-Language': 'en-US,en;q=0.9', 'Referer': BASE + '/market-data/all-upcoming-issues-ipo',
      'Cookie': cookie || '' },
    cf: { cacheTtl: 0, cacheEverything: false }
  });
  if(!r.ok) throw new Error(path + ' -> ' + r.status);
  return r.json();
}

export async function onRequest(context){
  const url = new URL(context.request.url);
  const fresh = url.searchParams.has('fresh');
  const H = { 'content-type':'application/json; charset=utf-8', 'access-control-allow-origin':'*',
    'cache-control': fresh ? 'no-store' : 'public, max-age=900, s-maxage=900' };

  try {
    // 1) bootstrap NSE cookies from a public HTML page
    let cookie = '';
    try {
      const boot = await fetch(BASE + '/market-data/all-upcoming-issues-ipo',
        { headers: { 'User-Agent': UA, 'Accept': 'text/html,*/*', 'Accept-Language':'en-US,en;q=0.9' }, cf:{cacheTtl:0} });
      const sc = (boot.headers.getSetCookie ? boot.headers.getSetCookie() : [boot.headers.get('set-cookie')]).filter(Boolean);
      cookie = sc.map(s => String(s).split(';')[0]).join('; ');
    } catch(e){}

    // 2) pull the three public endpoints (best-effort each)
    const safe = p => jget(p, cookie).catch(() => []);
    const [upcoming, current, past] = await Promise.all([
      safe('/api/all-upcoming-issues?category=ipo'),
      safe('/api/ipo-current-issue'),
      safe('/api/public-past-issues'),
    ]);

    const ipos = [];
    const today = istNow(); today.setUTCHours(0,0,0,0);

    // OPEN (current)
    for(const r of (Array.isArray(current)?current:[])){
      const sme = isSME(pick(r,['series','securityType','marketType']));
      const open = parseDate(pick(r,['issueStartDate','ipoStartDate','startDate']));
      const close = parseDate(pick(r,['issueEndDate','ipoEndDate','endDate']));
      const status = (close && close.getTime()===today.getTime()) ? 'closing' : 'open';
      ipos.push({
        name: pick(r,['companyName','company','name','symbol']) || 'IPO',
        symbol: pick(r,['symbol']) || null,
        seg: sme?'sme':'mainboard', status, ex: exFor('nse', sme),
        band: band(pick(r,['priceRange','priceBand','issuePrice'])),
        lot: num(pick(r,['lotSize','minBidQuantity','marketLot'])),
        size: num(pick(r,['issueSize','totalIssueSize'])),
        type: pick(r,['issueType','type']) || '',
        dates: { open: pretty(open), close: pretty(close) }, sub: null,
      });
    }
    // UPCOMING
    for(const r of (Array.isArray(upcoming)?upcoming:[])){
      const sme = isSME(pick(r,['series','securityType','marketType']));
      const open = parseDate(pick(r,['issueStartDate','ipoStartDate','startDate']));
      const close = parseDate(pick(r,['issueEndDate','ipoEndDate','endDate']));
      ipos.push({
        name: pick(r,['companyName','company','name','symbol']) || 'IPO',
        symbol: pick(r,['symbol']) || null,
        seg: sme?'sme':'mainboard', status:'upcoming', ex: exFor('nse', sme),
        band: band(pick(r,['priceRange','priceBand','issuePrice'])),
        lot: num(pick(r,['lotSize','minBidQuantity','marketLot'])),
        size: num(pick(r,['issueSize','totalIssueSize'])),
        type: pick(r,['issueType','type']) || '',
        dates: { open: pretty(open), close: pretty(close) },
      });
    }
    // RECENTLY LISTED (past) — most recent 9
    const pastArr = (Array.isArray(past)?past:[]).slice(0, 9);
    for(const r of pastArr){
      const sme = isSME(pick(r,['securityType','series']));
      const issue = num(pick(r,['issuePrice']));
      const list = parseDate(pick(r,['listingDate']));
      ipos.push({
        name: pick(r,['companyName','company','symbol']) || 'IPO',
        symbol: pick(r,['symbol']) || null,
        seg: sme?'sme':'mainboard', status:'listed', ex: exFor('nse', sme),
        band: band(pick(r,['priceRange'])),
        size: num(pick(r,['issueSize'])),
        type: pick(r,['issueType','type']) || '',
        dates: { open: pretty(parseDate(pick(r,['ipoStartDate']))), close: pretty(parseDate(pick(r,['ipoEndDate']))), listing: pretty(list) },
        listing: issue ? { issue } : null,   // issue price known; list/cur filled by quote step if available
      });
    }

    // compute min invest where possible
    for(const i of ipos){ if(i.band && i.lot) i.min = Math.round(i.band[1]*i.lot); }

    // finalize min for items with band+lot already handled; add min:null otherwise
    const body = { lastUpdated: new Date().toISOString(), source:'NSE (public data)', ipos };
    return new Response(JSON.stringify(body), { headers: H });
  } catch(e){
    return new Response(JSON.stringify({ lastUpdated:new Date().toISOString(), ipos:[], error:String(e&&e.message||e) }), { status:200, headers:H });
  }
}

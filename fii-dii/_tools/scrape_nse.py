#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-source FII/DII scraper (GitHub Actions / local).
Tries SEVERAL websites and merges whatever responds, so no single site (or NSE's
cloud-IP block) can stop the daily update. Upserts fii-dii/fii_dii_history.csv by
date and rebuilds fii-dii/history.json. Never writes guessed numbers.

Providers (each returns a list of day-rows; all are tried, results merged):
  1. Moneycontrol  — server-rendered HTML table (works from cloud; gives recent weeks)
  2. NSE API       — authoritative (often blocks cloud/foreign IPs)
  3. NSE via proxy — allorigins / corsproxy (helps from cloud)
  4. Groww API     — best-effort JSON
Add/remove providers freely in PROVIDERS at the bottom.
Deps: requests, beautifulsoup4
"""
import os, csv, json, datetime, time, re, urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CSV_PATH = os.path.join(ROOT, "fii-dii", "fii_dii_history.csv")
JSON_PATH = os.path.join(ROOT, "fii-dii", "history.json")
HDR = ["Date","FII Buy","FII Sell","FII Net","DII Buy","DII Sell","DII Net","Source","Status"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NSE_API = "https://www.nseindia.com/api/fiidiiTradeReact"

def _f(v):
    if v in (None,""): return None
    s=re.sub(r"[^0-9.\-]","",str(v))
    if s in ("","-","."): return None
    try: return float(s)
    except: return None

def _nd(s):
    s=str(s).strip()
    for fmt in ("%d-%b-%Y","%Y-%m-%d","%d %b %Y","%d-%m-%Y","%d/%m/%Y","%B %d, %Y","%b %d, %Y","%d %B %Y"):
        try: return datetime.datetime.strptime(s,fmt).strftime("%Y-%m-%d")
        except: pass
    m=re.search(r"(\d{1,2})[-/ ]([A-Za-z]{3,})[-/ ](\d{4})",s)
    if m:
        for fmt in ("%d %b %Y","%d %B %Y"):
            try: return datetime.datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}","%d %b %Y").strftime("%Y-%m-%d")
            except: pass
    return None

def row(date,fb,fs,fn,db,ds,dn,src):
    if not date: return None
    if fn is None and fb is not None and fs is not None: fn=fb-fs
    if dn is None and db is not None and ds is not None: dn=db-ds
    if fn is None or dn is None: return None
    # sanity ceiling: daily cash net never approaches +/-1 lakh cr -> rejects F&O/parse bleed
    if abs(fn)>100000 or abs(dn)>100000: return None
    # arithmetic guard: if gross present it must reconcile with net, else the columns are
    # mis-parsed -> drop the suspect gross but keep the (validated) net.
    if fb is not None and fs is not None and abs((fb-fs)-fn)>10: fb=fs=None
    if db is not None and ds is not None and abs((db-ds)-dn)>10: db=ds=None
    return {"Date":date,"FII Buy":fb,"FII Sell":fs,"FII Net":fn,"DII Buy":db,"DII Sell":ds,"DII Net":dn,"Source":src,"Status":"provisional"}

# ---------------- providers ----------------
def _get(url, tries=3, timeout=15, headers=None, **kw):
    """GET with retries + backoff and sane default headers."""
    import requests
    h={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"}
    if headers: h.update(headers)
    last=None
    for k in range(tries):
        try:
            r=requests.get(url,headers=h,timeout=timeout,**kw); r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(1.0*(k+1))
    raise last

def _find_series(node,depth=0):
    """Recursively locate Groww's day-series array inside __NEXT_DATA__."""
    if depth>10 or node is None: return None
    if isinstance(node,list):
        if len(node)>=2 and all(isinstance(x,dict) and isinstance(x.get("fii"),dict) for x in node): return node
        for x in node:
            r=_find_series(x,depth+1)
            if r: return r
        return None
    if isinstance(node,dict):
        for kk in node:
            r=_find_series(node[kk],depth+1)
            if r: return r
    return None

def _parse_nse(data):
    fii=dii=None
    for rr in (data or []):
        c=str(rr.get("category","")).upper()
        rec=(_nd(rr.get("date")),_f(rr.get("buyValue")),_f(rr.get("sellValue")),_f(rr.get("netValue")))
        if "FII" in c or "FPI" in c: fii=rec
        elif "DII" in c: dii=rec
    if not fii or not dii: raise ValueError("nse missing")
    # NSE returns FII & DII for the SAME latest day; pair them on FII's date
    return [row(fii[0],fii[1],fii[2],fii[3],dii[1],dii[2],dii[3],"NSE")]

# 1) Our Cloudflare edge (reaches NSE same-day; reachable from GitHub datacenter IPs).
def p_self_edge():
    j=_get("https://harshaldasani.pages.dev/api/fii-dii?fresh=1",headers={"Accept":"application/json"}).json()
    H=j.get("history") or []
    if not H: raise ValueError("edge empty")
    L=j.get("latest") or {}; ldate=_nd(L.get("date")) if L.get("date") else None
    out=[]
    for rr in H:
        dte=_nd(rr.get("date")); fn=_f((rr.get("fii") or {}).get("net")); dn=_f((rr.get("dii") or {}).get("net"))
        fb=fs=db=ds=None
        if dte and ldate and dte==ldate:
            f=L.get("fii") or {}; dd=L.get("dii") or {}
            fb=_f(f.get("buy")); fs=_f(f.get("sell")); db=_f(dd.get("buy")); ds=_f(dd.get("sell"))
        x=row(dte,fb,fs,fn,db,ds,dn,"Site-edge")
        if x: out.append(x)
    if not out: raise ValueError("edge no rows")
    return out

# 2) NSE direct (authoritative, same-day; works from residential IPs e.g. the watchdog;
#    403s from GitHub datacenter IPs -> just logged, never fatal).
def p_nse_direct():
    import requests
    s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept":"application/json,text/plain,*/*",
        "Accept-Language":"en-US,en;q=0.9","Referer":"https://www.nseindia.com/reports-indices-fii-dii-activity"})
    s.get("https://www.nseindia.com",timeout=20); time.sleep(1)
    s.get("https://www.nseindia.com/reports-indices-fii-dii-activity",timeout=20); time.sleep(0.4)
    r=s.get(NSE_API,timeout=20); r.raise_for_status(); return _parse_nse(r.json())

# 3) NSE via public relays (best-effort; helps when direct NSE is IP-blocked).
def p_nse_proxy():
    import requests
    targets=[
        "https://r.jina.ai/"+NSE_API,
        "https://api.allorigins.win/raw?url="+urllib.parse.quote(NSE_API,safe=""),
        "https://api.codetabs.com/v1/proxy/?quest="+NSE_API,
        "https://thingproxy.freeboard.io/fetch/"+NSE_API,
    ]
    for u in targets:
        try:
            r=requests.get(u,timeout=20,headers={"User-Agent":UA,"Accept":"application/json,*/*"})
            if not r.ok: continue
            data=None
            try: data=r.json()
            except Exception:
                m=re.search(r'(\[\s*\{.*\}\s*\])',r.text,re.S); data=json.loads(m.group(1)) if m else None
            if isinstance(data,dict): data=data.get("data") if isinstance(data.get("data"),list) else None
            if isinstance(data,list):
                try: return _parse_nse(data)
                except Exception: continue
        except Exception: continue
    raise ValueError("all proxies failed")

# 4) Groww page __NEXT_DATA__ (datacenter-friendly; ~21-day history; ~1-day lag).
def p_groww_page():
    r=_get("https://groww.in/fii-dii-data",headers={"Accept":"text/html,*/*"})
    m=re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>',r.text)
    if not m: raise ValueError("no __NEXT_DATA__")
    series=_find_series(json.loads(m.group(1)))
    if not series: raise ValueError("series not found")
    out=[]
    for it in series:
        d=_nd(it.get("date") or it.get("tradeDate"))
        f=it.get("fii") or {}; dd=it.get("dii") or {}
        fn=_f(f.get("netBuySell") if f.get("netBuySell") is not None else f.get("net"))
        dn=_f(dd.get("netBuySell") if dd.get("netBuySell") is not None else dd.get("net"))
        x=row(d,_f(f.get("grossBuy")),_f(f.get("grossSell")),fn,_f(dd.get("grossBuy")),_f(dd.get("grossSell")),dn,"Groww")
        if x: out.append(x)
    if not out: raise ValueError("groww empty")
    return out

# 5) Upstox (datacenter-friendly server-rendered cash table; ~1-day lag). Independent of Groww.
def p_upstox():
    from bs4 import BeautifulSoup
    r=_get("https://upstox.com/fii-dii-data/",headers={"Accept":"text/html,*/*"})
    soup=BeautifulSoup(r.text,"html.parser"); out=[]
    for tb in soup.find_all("table"):
        trs=tb.find_all("tr")
        if len(trs)<2: continue
        hdr=" ".join(c.get_text(" ",strip=True) for c in trs[0].find_all(["td","th"])).lower()
        if any(b in hdr for b in ("%","long value","fut","opt")): continue          # skip F&O / ratio tables
        if not ("fii" in hdr and "dii" in hdr and "net purchase" in hdr): continue   # cash table only
        for tr in trs[1:]:
            cells=[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"])]
            if len(cells)<7: continue
            d=_nd(cells[0])
            if not d: continue
            x=row(d,_f(cells[1]),_f(cells[2]),_f(cells[3]),_f(cells[4]),_f(cells[5]),_f(cells[6]),"Upstox")
            if x: out.append(x)
        if out: break
    if not out: raise ValueError("upstox no cash table")
    return out

# Priority order (all are tried and merged by date; order only breaks ties on equal detail):
#   Site-edge -> NSE (same-day)  |  Groww-page, Upstox (datacenter-friendly next-day backfill)  |  proxies
PROVIDERS=[("Site-edge",p_self_edge),("NSE",p_nse_direct),("Groww-page",p_groww_page),("Upstox",p_upstox),("NSE-proxy",p_nse_proxy)]

# ---------------- store ----------------
def read_csv():
    d={}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH,newline="",encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                dt=_nd(r.get("Date"))
                if dt: d[dt]={k:r.get(k,"") for k in HDR}; d[dt]["Date"]=dt
    return d

def detail_score(r): return sum(1 for k in ("FII Buy","FII Sell","DII Buy","DII Sell") if _f(r.get(k)) is not None)

def write_csv(d):
    with open(CSV_PATH,"w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(HDR)
        for dt in sorted(d):
            r=d[dt]; w.writerow([dt,r.get("FII Buy","") or "",r.get("FII Sell","") or "",r.get("FII Net",""),
                r.get("DII Buy","") or "",r.get("DII Sell","") or "",r.get("DII Net",""),
                r.get("Source","") or "","provisional"])

def build_json(d):
    H=[]
    for dt in sorted(d):
        r=d[dt]; fn=_f(r.get("FII Net")); dn=_f(r.get("DII Net"))
        if fn is None or dn is None: continue
        fii={"net":fn}; dii={"net":dn}
        if _f(r.get("FII Buy")) is not None: fii.update(buy=_f(r["FII Buy"]),sell=_f(r["FII Sell"]))
        if _f(r.get("DII Buy")) is not None: dii.update(buy=_f(r["DII Buy"]),sell=_f(r["DII Sell"]))
        H.append({"date":dt,"fii":fii,"dii":dii})
    if not H: return
    last=H[-1]
    # preserve the 2007-2026 monthly series (drives Monthly/Yearly tabs) from the monthly CSV
    M=[]
    MCSV=os.path.join(ROOT,"fii-dii","fii_dii_monthly.csv")
    if os.path.exists(MCSV):
        with open(MCSV,newline="",encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                ym=(row.get("Month") or "").strip()[:7]
                if len(ym)!=7: continue
                fn=_f(row.get("FII Net")); dn=_f(row.get("DII Net"))
                if fn is None or dn is None: continue
                fo={"net":fn}; do={"net":dn}
                if _f(row.get("FII Buy")) is not None: fo.update(buy=_f(row["FII Buy"]),sell=_f(row["FII Sell"]))
                if _f(row.get("DII Buy")) is not None: do.update(buy=_f(row["DII Buy"]),sell=_f(row["DII Sell"]))
                M.append({"date":ym+"-01","fii":fo,"dii":do})
    json.dump({"lastUpdated":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest":{"date":last["date"],"status":"provisional","confidence":"confirmed","sources":["multi-source"],
            "fii":last["fii"] if "buy" in last["fii"] else {"buy":0,"sell":0,"net":last["fii"]["net"]},
            "dii":last["dii"] if "buy" in last["dii"] else {"buy":0,"sell":0,"net":last["dii"]["net"]}},
        "history":H,"monthly":M}, open(JSON_PATH,"w"), separators=(",",":"))

def build_xlsx():
    """Regenerate fii-dii/FII_DII_History.xlsx (Daily + Monthly sheets) so the Excel
    auto-updates alongside the CSV/JSON. Skipped if openpyxl missing."""
    try:
        import openpyxl
    except Exception:
        print("openpyxl missing; xlsx not written"); return
    XLSX=os.path.join(ROOT,"fii-dii","FII_DII_History.xlsx")
    MCSV=os.path.join(ROOT,"fii-dii","fii_dii_monthly.csv")
    wb=openpyxl.Workbook(); ds=wb.active; ds.title="Daily"; ds.append(HDR); ds.freeze_panes="A2"
    with open(CSV_PATH,newline="",encoding="utf-8-sig") as fh:
        rd=csv.DictReader(fh)
        for r in rd: ds.append([r.get(h,"") for h in HDR])
    if os.path.exists(MCSV):
        ms=wb.create_sheet("Monthly")
        with open(MCSV,newline="",encoding="utf-8-sig") as fh:
            for row in csv.reader(fh): ms.append(row)
        ms.freeze_panes="A2"
    wb.save(XLSX); print("xlsx written:",XLSX)

def main():
    d=read_csv(); before=len(d); fetched={}
    for name,fn in PROVIDERS:
        try:
            rows=fn(); print(f"{name}: {len(rows)} row(s)")
            for r in rows: fetched.setdefault(r["Date"],[]).append(r)
        except Exception as e:
            print(f"{name}: failed ({e})")
    # upsert: add missing dates; for existing, only upgrade if new row has MORE detail
    added=0; upgraded=0
    for dt,cands in fetched.items():
        best=max(cands,key=detail_score)
        if dt not in d: d[dt]=best; added+=1
        elif detail_score(best)>detail_score(d[dt]): d[dt]=best; upgraded+=1
    if added or upgraded:
        write_csv(d); build_json(d); build_xlsx()
        print(f"CSV now {len(d)} days (+{added} new, {upgraded} enriched).")
    else:
        print("No new data (nothing reachable or all already present).")
    return 0

if __name__=="__main__": raise SystemExit(main())

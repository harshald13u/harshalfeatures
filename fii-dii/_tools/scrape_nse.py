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
    return {"Date":date,"FII Buy":fb,"FII Sell":fs,"FII Net":fn,"DII Buy":db,"DII Sell":ds,"DII Net":dn,"Source":src,"Status":"provisional"}

# ---------------- providers ----------------
def p_moneycontrol():
    import requests
    from bs4 import BeautifulSoup
    url="https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"
    r=requests.get(url,headers={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"},timeout=30); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); out=[]
    for tbl in soup.find_all("table"):
        for tr in tbl.find_all("tr"):
            cells=[c.get_text(strip=True) for c in tr.find_all(["td","th"])]
            if len(cells)<7: continue
            d=_nd(cells[0])
            if not d: continue
            nums=[_f(c) for c in cells[1:]]
            if sum(1 for n in nums if n is not None)<6: continue
            # layout: Date, FIIbuy, FIIsell, FIInet, DIIbuy, DIIsell, DIInet
            rr=row(d,nums[0],nums[1],nums[2],nums[3],nums[4],nums[5],"Moneycontrol")
            if rr: out.append(rr)
    if not out: raise ValueError("no rows parsed")
    return out

def p_nse_direct():
    import requests
    s=requests.Session(); s.headers.update({"User-Agent":UA,"Accept":"application/json,text/plain,*/*",
        "Accept-Language":"en-US,en;q=0.9","Referer":"https://www.nseindia.com/reports-indices-fii-dii-activity"})
    s.get("https://www.nseindia.com",timeout=20); time.sleep(1)
    s.get("https://www.nseindia.com/reports-indices-fii-dii-activity",timeout=20); time.sleep(0.5)
    r=s.get(NSE_API,timeout=20); r.raise_for_status(); return _parse_nse(r.json())

def p_nse_proxy():
    import requests
    for prox in ["https://api.allorigins.win/raw?url=","https://corsproxy.io/?url="]:
        try:
            u=prox+urllib.parse.quote(NSE_API,safe="")
            r=requests.get(u,timeout=30,headers={"User-Agent":UA}); r.raise_for_status()
            return _parse_nse(r.json())
        except Exception: continue
    raise ValueError("proxies failed")

def _parse_nse(data):
    fii=dii=None
    for rr in data:
        c=str(rr.get("category","")).upper()
        rec=(_nd(rr.get("date")),_f(rr.get("buyValue")),_f(rr.get("sellValue")),_f(rr.get("netValue")))
        if "FII" in c or "FPI" in c: fii=rec
        elif "DII" in c: dii=rec
    if not fii or not dii: raise ValueError("nse missing")
    return [row(fii[0],fii[1],fii[2],fii[3],dii[1],dii[2],dii[3],"NSE")]

def p_groww():
    import requests
    u="https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/NSE/segment/CASH/fii_dii_activity"
    r=requests.get(u,headers={"User-Agent":UA,"Accept":"application/json"},timeout=25); r.raise_for_status()
    j=r.json(); arr=j.get("data") or j.get("fiiDiiData") or []
    out=[]
    for rr in arr:
        d=_nd(rr.get("date") or rr.get("tradeDate"))
        fn=_f(rr.get("fiiNet") or rr.get("fii_net")); dn=_f(rr.get("diiNet") or rr.get("dii_net"))
        x=row(d,_f(rr.get("fiiBuy")),_f(rr.get("fiiSell")),fn,_f(rr.get("diiBuy")),_f(rr.get("diiSell")),dn,"Groww")
        if x: out.append(x)
    if not out: raise ValueError("groww empty")
    return out

PROVIDERS=[("Moneycontrol",p_moneycontrol),("NSE",p_nse_direct),("NSE-proxy",p_nse_proxy),("Groww",p_groww)]

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
    json.dump({"lastUpdated":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest":{"date":last["date"],"status":"provisional","confidence":"confirmed","sources":["multi-source"],
            "fii":last["fii"] if "buy" in last["fii"] else {"buy":0,"sell":0,"net":last["fii"]["net"]},
            "dii":last["dii"] if "buy" in last["dii"] else {"buy":0,"sell":0,"net":last["dii"]["net"]}},
        "history":H}, open(JSON_PATH,"w"), separators=(",",":"))

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

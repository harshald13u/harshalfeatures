#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cloud scraper (GitHub Actions). Fetches latest NSE FII/DII cash figures,
upserts into fii-dii/fii_dii_history.csv (by date), and rebuilds fii-dii/history.json
for the website. No Excel needed in the cloud (CSV opens in Excel anyway).

Tries NSE directly, then a public CORS proxy (helps when NSE blocks cloud IPs).
Never writes guessed numbers — on total failure it exits 0 without changes."""
import os, csv, json, datetime, time, urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CSV_PATH = os.path.join(ROOT, "fii-dii", "fii_dii_history.csv")
JSON_PATH = os.path.join(ROOT, "fii-dii", "history.json")
HDR = ["Date","FII Buy","FII Sell","FII Net","DII Buy","DII Sell","DII Net","Source","Status"]
NSE_API = "https://www.nseindia.com/api/fiidiiTradeReact"

def f(v):
    if v in (None,""): return None
    s=str(v).replace(",","").strip()
    try: return float(s)
    except: return None

def nd(s):
    s=str(s).strip()
    for fmt in ("%d-%b-%Y","%Y-%m-%d","%d %b %Y","%d-%m-%Y"):
        try: return datetime.datetime.strptime(s,fmt).strftime("%Y-%m-%d")
        except: pass
    return None

def parse(data):
    fii=dii=None
    for row in data:
        c=str(row.get("category","")).upper()
        rec={"date":nd(row.get("date")),"buy":f(row.get("buyValue")),"sell":f(row.get("sellValue")),"net":f(row.get("netValue"))}
        if "FII" in c or "FPI" in c: fii=rec
        elif "DII" in c: dii=rec
    if not fii or not dii or not fii["date"]: raise ValueError("missing FII/DII")
    return fii,dii

def fetch():
    import requests
    H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
       "Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9",
       "Referer":"https://www.nseindia.com/reports-indices-fii-dii-activity"}
    # 1) direct
    try:
        s=requests.Session(); s.headers.update(H)
        s.get("https://www.nseindia.com",timeout=20); time.sleep(1)
        s.get("https://www.nseindia.com/reports-indices-fii-dii-activity",timeout=20); time.sleep(0.5)
        r=s.get(NSE_API,timeout=20); r.raise_for_status()
        print("source: NSE direct"); return parse(r.json())
    except Exception as e: print("NSE direct failed:",e)
    # 2) public CORS proxy (server-side fetch — can bypass cloud-IP blocks)
    for proxy in ["https://api.allorigins.win/raw?url=","https://corsproxy.io/?url="]:
        try:
            url=proxy+urllib.parse.quote(NSE_API,safe="")
            r=requests.get(url,timeout=30,headers={"User-Agent":H["User-Agent"]}); r.raise_for_status()
            print("source: proxy",proxy); return parse(r.json())
        except Exception as e: print("proxy failed:",proxy,e)
    raise RuntimeError("all sources failed")

def read_csv():
    d={}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH,newline="",encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                dt=nd(row.get("Date"))
                if dt: d[dt]=row
    return d

def write_csv(d):
    with open(CSV_PATH,"w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(HDR)
        for dt in sorted(d):
            r=d[dt]; w.writerow([dt,r.get("FII Buy",""),r.get("FII Sell",""),r.get("FII Net",""),
                                 r.get("DII Buy",""),r.get("DII Sell",""),r.get("DII Net",""),
                                 r.get("Source","NSE"),r.get("Status","provisional")])

def build_json(d):
    H=[]
    for dt in sorted(d):
        r=d[dt]; fn=f(r.get("FII Net")); dn=f(r.get("DII Net"))
        if fn is None or dn is None: continue
        fii={"net":fn}; dii={"net":dn}
        if f(r.get("FII Buy")) is not None: fii.update(buy=f(r["FII Buy"]),sell=f(r["FII Sell"]))
        if f(r.get("DII Buy")) is not None: dii.update(buy=f(r["DII Buy"]),sell=f(r["DII Sell"]))
        H.append({"date":dt,"fii":fii,"dii":dii})
    if not H: return
    last=H[-1]
    out={"lastUpdated":datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
         "latest":{"date":last["date"],"status":"provisional","confidence":"confirmed","sources":["NSE"],
                   "fii":last["fii"] if "buy" in last["fii"] else {"buy":0,"sell":0,"net":last["fii"]["net"]},
                   "dii":last["dii"] if "buy" in last["dii"] else {"buy":0,"sell":0,"net":last["dii"]["net"]}},
         "history":H}
    json.dump(out,open(JSON_PATH,"w"),separators=(",",":"))

def main():
    try: fii,dii=fetch()
    except Exception as e:
        print("No data fetched (",e,") — leaving files unchanged."); return 0
    d=read_csv(); dt=fii["date"]
    if dt in d: print("already present:",dt)
    else:
        d[dt]={"Date":dt,"FII Buy":fii["buy"] or "","FII Sell":fii["sell"] or "","FII Net":fii["net"],
               "DII Buy":dii["buy"] or "","DII Sell":dii["sell"] or "","DII Net":dii["net"],
               "Source":"NSE","Status":"provisional"}
        print("ADDED",dt,"FII net",fii["net"],"DII net",dii["net"])
    write_csv(d); build_json(d); return 0

if __name__=="__main__": raise SystemExit(main())

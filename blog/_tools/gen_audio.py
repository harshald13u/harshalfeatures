#!/usr/bin/env python3
"""Generate the English 'Listen to this article' narration MP3 for a blog post.
Free edge-tts (en-IN-NeerjaExpressiveNeural — warm, expressive Indian-English voice).
Reads the FULL visible articleBody from index.html (falls back to BlogPosting JSON-LD),
expands finance shorthand for natural speech, appends a short disclaimer (NO INVasset /
SEBI references), and writes audio.mp3 in the post folder.

Synthesizes in sentence-aligned chunks and concatenates with ffmpeg so it works even
where a single long synthesis call would time out. No API key, no cost.

Usage: python3 gen_audio.py blog/posts/<slug> [<slug2> ...]
Requires: pip install edge-tts ; ffmpeg on PATH.
"""
import json, re, sys, os, subprocess, asyncio, html as _h, tempfile
VOICE = "en-IN-NeerjaExpressiveNeural"
RATE  = "+0%"     # calm, deliberate pace for long-form listening
DISCLAIMER = "This is general information, not investment advice."
CHUNK_CHARS = 2600

def extract(post_dir):
    html = open(os.path.join(post_dir, "index.html"), encoding="utf-8").read()
    m1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    headline = re.sub(r'<[^>]+>', '', m1.group(1)).strip() if m1 else ""
    m = re.search(r'<article itemprop="articleBody">(.*?)</article>', html, re.S)
    body = _h.unescape(re.sub(r'<[^>]+>', ' ', m.group(1))) if m else ""
    if len(body) < 200:  # fallback to JSON-LD articleBody
        for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            try: d = json.loads(b)
            except Exception: continue
            nodes = d if isinstance(d, list) else [d]
            for n in list(nodes):
                if isinstance(n, dict) and n.get("@graph"): nodes += n["@graph"]
            for n in nodes:
                if isinstance(n, dict) and n.get("@type") == "BlogPosting":
                    headline = n.get("headline", "") or headline
                    body = n.get("articleBody", "") or body
    return headline, body

def speechify(t):
    t = re.sub(r'₹\s?', 'rupees ', t)
    t = re.sub(r'\$\s?([\d][\d,.]*)', r'\1 dollars', t)
    t = t.replace('%', ' percent')
    t = re.sub(r'\bbps\b', 'basis points', t)
    t = re.sub(r'\bFY\s?(\d{2})\b', r'financial year \1', t)
    t = re.sub(r'\bDXY\b', 'the dollar index', t)
    t = re.sub(r'\bCAD\b', 'current account deficit', t)
    t = re.sub(r'\bOMCs\b', 'oil marketing companies', t); t = re.sub(r'\bOMC\b', 'oil marketing company', t)
    t = re.sub(r'\bFIIs\b', 'foreign institutional investors', t); t = re.sub(r'\bFII\b', 'foreign institutional investor', t)
    t = t.replace('→', ' to ').replace('·', ', ').replace('—', ', ').replace('–', ', ')
    return re.sub(r'[ \t]+', ' ', t).strip()

def chunk(text, n):
    parts = re.split(r'(?<=[।\.\?!])\s+', text); out, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 > n and cur: out.append(cur); cur = p
        else: cur = (cur + " " + p).strip()
    if cur: out.append(cur)
    return out or [text]

async def synth_all(items):
    import edge_tts
    sem = asyncio.Semaphore(3)   # cap concurrent TTS connections (avoid throttling/timeouts)
    async def one(t, o):
        async with sem:
            await edge_tts.Communicate(t, VOICE, rate=RATE).save(o)
    await asyncio.gather(*[one(t, o) for t, o in items])

def gen(post_dir):
    headline, body = extract(post_dir)
    if len(body) < 200: print(f"  ! no body in {post_dir}"); return None
    spoken = f"{headline}. {speechify(body)} {DISCLAIMER}"
    chunks = chunk(spoken, CHUNK_CHARS); tmp = tempfile.mkdtemp()
    parts = [os.path.join(tmp, f"p{i}.mp3") for i in range(len(chunks))]
    asyncio.run(synth_all(list(zip(chunks, parts))))
    out = os.path.join(post_dir, "audio.mp3")
    if len(parts) == 1: os.replace(parts[0], out)
    else:
        lst = os.path.join(tmp, "l.txt"); open(lst,"w").write("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",lst,"-c","copy",out], check=True)
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],capture_output=True,text=True).stdout.strip()
    print(f"  + {out}  {os.path.getsize(out)//1024}KB  {float(dur):.0f}s  ({len(chunks)} chunk/s)")
    return out

if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(d); gen(d)

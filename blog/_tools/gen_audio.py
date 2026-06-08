#!/usr/bin/env python3
"""Generate 'Listen to this article' MP3 for a blog post using free edge-tts (en-IN-PrabhatNeural).
Reads the clean articleBody from the post's BlogPosting JSON-LD, preprocesses finance terms,
appends a spoken disclaimer, writes audio.mp3 in the post folder. No API key, no cost.
Usage: python3 gen_audio.py blog/posts/<slug> [<slug2> ...]"""
import json, re, sys, os, subprocess, asyncio
VOICE = "en-IN-NeerjaExpressiveNeural"
DISCLAIMER = "This is general information, not investment advice."

def extract(post_dir):
    html = open(os.path.join(post_dir, "index.html"), encoding="utf-8").read()
    headline = ""; body = ""
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
    t = re.sub(r'\bOMCs\b', 'oil marketing companies', t)
    t = re.sub(r'\bOMC\b', 'oil marketing company', t)
    t = re.sub(r'\bFIIs\b', 'foreign institutional investors', t)
    t = re.sub(r'\bFII\b', 'foreign institutional investor', t)
    t = t.replace('→', ' to ').replace('·', ', ').replace('—', ', ').replace('–', ', ')
    return re.sub(r'[ \t]+', ' ', t).strip()

async def synth(text, out):
    import edge_tts
    await edge_tts.Communicate(text, VOICE).save(out)

def gen(post_dir):
    headline, body = extract(post_dir)
    if not body:
        print(f"  ! no articleBody in {post_dir}"); return None
    spoken = f"{headline}. {speechify(body)} {DISCLAIMER}"
    out = os.path.join(post_dir, "audio.mp3")
    asyncio.run(synth(spoken, out))
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],
                         capture_output=True, text=True).stdout.strip()
    print(f"  + {out}  {os.path.getsize(out)//1024}KB  {float(dur):.0f}s")
    return out

if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(d); gen(d)

#!/usr/bin/env python3
"""Generate Hindi 'इस लेख को सुनें' narration MP3 for a Hindi blog twin.
Free edge-tts (hi-IN-MadhurNeural). Reads the FULL visible Hindi articleBody from
the post's index.html, expands ₹/$/% to Hindi words, appends a Hindi disclaimer
(NO INVasset / SEBI references), and writes audio.mp3 in the post folder.

Synthesizes in sentence-aligned chunks and concatenates with ffmpeg, so it works
even where a single long synthesis call would time out. No API key, no cost.

Usage: python3 gen_audio_hi.py hi/blog/posts/<slug> [<slug2> ...]
Requires: pip install edge-tts ; ffmpeg on PATH.
"""
import re, sys, os, asyncio, html as _h, subprocess, tempfile
VOICE = "hi-IN-SwaraNeural"   # warm, natural Indian voice
RATE = "-3%"   # slightly slower for clarity
DISCLAIMER = "यह सामान्य जानकारी है, कोई निवेश सलाह नहीं।"
CHUNK_CHARS = 2600  # keeps each synth well under any per-call timeout

def extract(post_dir):
    html = open(os.path.join(post_dir, "index.html"), encoding="utf-8").read()
    m1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    headline = re.sub(r'<[^>]+>', '', m1.group(1)).strip() if m1 else ""
    m = re.search(r'<article itemprop="articleBody">(.*?)</article>', html, re.S)
    body = re.sub(r'<[^>]+>', ' ', m.group(1)) if m else ""
    return _h.unescape(headline), _h.unescape(body)

def speechify(t):
    t = re.sub(r'₹\s?', 'रुपये ', t)
    t = re.sub(r'\$\s?([\d][\d,.]*)', r'\1 डॉलर', t)
    t = t.replace('%', ' प्रतिशत')
    t = t.replace('→', ' से ').replace('·', ', ').replace('—', ', ').replace('–', ', ')
    return re.sub(r'[ \t]+', ' ', t).strip()

def chunk(text, n_chars):
    parts = re.split(r'(?<=[।\.\?!])\s+', text)
    out, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 > n_chars and cur:
            out.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
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
    if len(body) < 200:
        print(f"  ! body too short in {post_dir}"); return None
    spoken = f"{headline}। हर्षल दसानी द्वारा। {speechify(body)} {DISCLAIMER}"
    chunks = chunk(spoken, CHUNK_CHARS)
    tmp = tempfile.mkdtemp()
    parts = [os.path.join(tmp, f"p{i}.mp3") for i in range(len(chunks))]
    asyncio.run(synth_all(list(zip(chunks, parts))))
    out = os.path.join(post_dir, "audio.mp3")
    if len(parts) == 1:
        os.replace(parts[0], out)
    else:
        lst = os.path.join(tmp, "list.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", out], check=True)
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","csv=p=0",out], capture_output=True, text=True).stdout.strip()
    print(f"  + {out}  {os.path.getsize(out)//1024}KB  {float(dur):.0f}s  ({len(chunks)} chunk/s)")
    return out

if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(d); gen(d)

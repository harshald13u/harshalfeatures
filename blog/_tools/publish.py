"""Publish a new blog post.

Inputs (CLI args or env):
    --slug "stock-market-q1-fy26"
    --title "Q1 FY26 — Reading the rotation"
    --topic stock-market | commodities | macros | geopolitics
    --date 2026-06-04
    --excerpt "Short 1-line summary..."
    --cover path/to/cover.jpg
    --body path/to/body.md  (markdown body)

What it does:
    1. Copies cover.jpg into /blog/posts/{slug}/cover.jpg
    2. Renders body.md to a full /blog/posts/{slug}/index.html using the existing template
    3. Appends entry to /blog/posts.json
    4. Adds URL to sitemap.xml
    5. Triggers IndexNow ping on next deploy
"""
import argparse, json, os, shutil, re
from datetime import datetime

BLOG_DIR = "/sessions/keen-zen-archimedes/mnt/Features/blog"
ROOT_HF = "/sessions/keen-zen-archimedes/mnt/Features/ harshal-features"

def render_post_html(slug, title, topic, date_str, excerpt, body_md, cover_filename):
    canonical = f"https://harshald13u.github.io/harshalfeatures/blog/posts/{slug}/"
    # Convert simple markdown to HTML (paragraphs, headings, bold, italic, links)
    html = []
    for block in body_md.split("\n\n"):
        block = block.strip()
        if not block: continue
        if block.startswith("# "):  html.append(f"<h2>{block[2:].strip()}</h2>")
        elif block.startswith("## "): html.append(f"<h3>{block[3:].strip()}</h3>")
        elif block.startswith("> "): html.append(f"<blockquote>{block[2:].strip()}</blockquote>")
        elif block.startswith("- "):
            items = "\n".join(f"<li>{line[2:].strip()}</li>" for line in block.split("\n") if line.strip().startswith("- "))
            html.append(f"<ul>{items}</ul>")
        else:
            paragraph = block.replace("**", "&__b__&")
            # bold
            paragraph = re.sub(r"&__b__&([^&]+)&__b__&", r"<strong>\1</strong>", paragraph)
            # italic
            paragraph = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", paragraph)
            # links
            paragraph = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', paragraph)
            html.append(f"<p>{paragraph}</p>")
    body_html = "\n".join(html)

    return f'''<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Harshal Dasani</title>
<meta name="description" content="{excerpt}">
<meta name="author" content="Harshal Dasani">
<meta http-equiv="content-language" content="en-IN">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="en-IN" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — Harshal Dasani">
<meta property="og:description" content="{excerpt}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{canonical}{cover_filename}">
<meta property="og:site_name" content="Harshal Dasani">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{canonical}{cover_filename}">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@graph": [
    {{"@type": "Person", "@id": "https://harshald13u.github.io/harshalfeatures/#person", "name": "Harshal Dasani", "url": "https://harshald13u.github.io/harshalfeatures/"}},
    {{"@type": "BlogPosting", "headline": "{title}", "description": "{excerpt}", "datePublished": "{date_str}", "image": "{canonical}{cover_filename}", "url": "{canonical}", "author": {{"@id": "https://harshald13u.github.io/harshalfeatures/#person"}}, "publisher": {{"@id": "https://harshald13u.github.io/harshalfeatures/#person"}}, "mainEntityOfPage": "{canonical}", "articleSection": "{topic}"}}
  ]
}}
</script>
<script>(function(){{try{{var t=localStorage.getItem('hd-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}}})();</script>

<style>
:root{{--bg:#0e0c0a;--bg-2:#15110d;--ink:#ece4d3;--ink-2:#c9c0ad;--muted:#8a8273;--rule:rgba(236,228,211,0.10);--accent:#d4a64a;}}
html[data-theme="light"]{{--bg:#ebe5d7;--bg-2:#ddd4c1;--ink:#1a3458;--ink-2:#3a527a;--muted:#54687f;--rule:rgba(26,52,88,0.18);--accent:#b8852b;}}
*{{box-sizing:border-box}} html,body{{margin:0;padding:0;background:var(--bg);color:var(--ink-2)}}
body{{font-family:'Inter',sans-serif;line-height:1.62;-webkit-font-smoothing:antialiased}}
a{{color:var(--accent);text-decoration:none}} a:hover{{text-decoration:underline}}
.page{{max-width:760px;margin:0 auto;padding:56px 24px 96px}}
.crumb{{font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);margin-bottom:24px}}
.cover{{aspect-ratio:16/9;background:var(--bg-2);border-radius:8px;overflow:hidden;margin:0 0 32px}}
.cover img{{width:100%;height:100%;object-fit:cover;display:block}}
.topic-pill{{display:inline-block;padding:5px 12px;border:1px solid var(--rule);border-radius:999px;font-size:11px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--accent);margin-bottom:18px}}
h1{{font-family:'Inter',sans-serif;font-weight:800;font-size:clamp(34px,4.8vw,52px);line-height:1.08;letter-spacing:-0.025em;color:var(--ink);margin:0 0 16px}}
.meta{{font-size:13px;color:var(--muted);margin:0 0 36px}}
h2{{font-weight:700;font-size:22px;color:var(--ink);margin:36px 0 12px;letter-spacing:-0.01em}}
h3{{font-weight:700;font-size:18px;color:var(--ink);margin:28px 0 10px}}
p{{margin:0 0 18px;font-size:16.5px}}
ul{{padding-left:22px;margin:0 0 18px}} li{{margin-bottom:6px}}
blockquote{{margin:24px 0;padding:8px 0 8px 20px;border-left:2px solid var(--accent);font-style:italic;color:var(--ink)}}
strong{{color:var(--ink);font-weight:700}}
.next{{margin-top:48px;padding-top:24px;border-top:1px solid var(--rule)}}
</style>
</head>
<body>
<main class="page">
  <div class="crumb"><a href="../../../">Harshal Dasani</a> &middot; <a href="../../">Blogs</a> &middot; {title}</div>
  <span class="topic-pill">{topic}</span>
  <h1>{title}</h1>
  <p class="meta">{date_str} &middot; Harshal Dasani</p>
  <div class="cover"><img src="{cover_filename}" alt="{title}" loading="lazy"></div>
  {body_html}
  <div class="next"><a href="../../">&larr; All blogs by Harshal Dasani</a></div>
</main>
</body>
</html>
'''


def publish(slug, title, topic, date_str, excerpt, cover_path, body_md):
    post_dir = os.path.join(BLOG_DIR, "posts", slug)
    os.makedirs(post_dir, exist_ok=True)

    # Copy cover
    cover_ext = os.path.splitext(cover_path)[1].lower() or ".jpg"
    cover_filename = f"cover{cover_ext}"
    shutil.copy(cover_path, os.path.join(post_dir, cover_filename))

    # Render HTML
    html = render_post_html(slug, title, topic, date_str, excerpt, body_md, cover_filename)
    with open(os.path.join(post_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # Save the source markdown too
    with open(os.path.join(post_dir, "body.md"), "w", encoding="utf-8") as f:
        f.write(body_md)

    # Append to posts.json
    posts_json_path = os.path.join(BLOG_DIR, "posts.json")
    with open(posts_json_path) as f:
        data = json.load(f)
    canonical = f"https://harshald13u.github.io/harshalfeatures/blog/posts/{slug}/"
    image_url = f"{canonical}{cover_filename}"
    entry = {
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": image_url, "url": canonical,
    }
    # Replace any existing entry with the same slug
    data["posts"] = [p for p in data.get("posts", []) if p.get("slug") != slug]
    data["posts"].append(entry)
    with open(posts_json_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Published: {slug}")
    print(f"  Post dir: {post_dir}")
    print(f"  Cover: {cover_filename}")
    print(f"  Excerpt: {excerpt}")
    return entry


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--topic", required=True, choices=["stock-market","commodities","macros","geopolitics"])
    ap.add_argument("--date", default=datetime.today().strftime("%Y-%m-%d"))
    ap.add_argument("--excerpt", required=True)
    ap.add_argument("--cover", required=True)
    ap.add_argument("--body", required=True)
    args = ap.parse_args()
    with open(args.body) as f:
        body_md = f.read()
    publish(args.slug, args.title, args.topic, args.date, args.excerpt, args.cover, body_md)



# ============================================================
# Word (.docx) ingestion
# ============================================================
import zipfile, xml.etree.ElementTree as ET

def extract_docx(docx_path):
    """Extract images + body text from a .docx file at full resolution.

    Returns dict:
        {
          "images": [(filename, bytes), ...],  # in document order, first = cover
          "paragraphs": [
              {"type": "p"|"h1"|"h2"|"li"|"image", "text": "...", "image_idx": N},
              ...
          ],
          "raw_text": "all body text concatenated, for the categorizer"
        }
    """
    images = []
    paragraphs = []

    with zipfile.ZipFile(docx_path) as z:
        # 1. Pull every image from word/media/ in document insertion order
        media_files = sorted(
            [n for n in z.namelist() if n.startswith("word/media/")],
            key=lambda x: (len(x), x)
        )
        for name in media_files:
            content = z.read(name)
            fname = os.path.basename(name)
            images.append((fname, content))

        # 2. Parse word/document.xml to get text + image positions in order
        doc_xml = z.read("word/document.xml").decode("utf-8")
        # Quick regex parse for image relationship IDs
        # and paragraph text — simpler than full XML walk
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
              "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
              "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

        # Parse relationships to map rId -> media filename
        try:
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8")
            rels_root = ET.fromstring(rels_xml)
            rid_to_target = {}
            for rel in rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                rid_to_target[rel.attrib.get("Id")] = rel.attrib.get("Target", "")
        except Exception:
            rid_to_target = {}

        root = ET.fromstring(doc_xml)
        body = root.find("w:body", ns)
        if body is None:
            return {"images": images, "paragraphs": paragraphs, "raw_text": ""}

        media_filename_to_idx = {fn: i for i, (fn, _) in enumerate(images)}

        for p in body.findall("w:p", ns):
            # detect heading style
            pStyle = p.find("w:pPr/w:pStyle", ns)
            style = pStyle.attrib.get(f"{{{ns['w']}}}val", "") if pStyle is not None else ""
            block_type = "p"
            if style.lower().startswith("heading 1"): block_type = "h1"
            elif style.lower().startswith("heading 2"): block_type = "h2"
            elif style.lower().startswith("listparagraph"): block_type = "li"

            # find any inline drawings (images) in this paragraph
            embed_ids = []
            for blip in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                eid = blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                if eid: embed_ids.append(eid)

            # paragraph text
            text_parts = []
            for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                if t.text: text_parts.append(t.text)
            text = "".join(text_parts).strip()

            for eid in embed_ids:
                target = rid_to_target.get(eid, "")
                fname = os.path.basename(target) if target else ""
                idx = media_filename_to_idx.get(fname)
                if idx is not None:
                    paragraphs.append({"type": "image", "image_idx": idx, "text": ""})

            if text:
                paragraphs.append({"type": block_type, "text": text})

    raw_text = " ".join(p["text"] for p in paragraphs if p.get("text"))
    return {"images": images, "paragraphs": paragraphs, "raw_text": raw_text}


def publish_from_docx(docx_path, slug, title=None, topic=None, excerpt=None, date_str=None):
    """End-to-end publish from a .docx file."""
    data = extract_docx(docx_path)
    if not data["images"]:
        raise SystemExit("No images found in the Word document — please embed at least the cover image.")

    # First image = cover
    cover_fname, cover_bytes = data["images"][0]
    inline_images = data["images"][1:]

    # Use first heading as title if not provided
    if not title:
        for p in data["paragraphs"]:
            if p["type"] in ("h1", "h2") and p["text"]:
                title = p["text"]
                break
        if not title:
            title = "Untitled"

    # Build excerpt from first non-empty paragraph
    if not excerpt:
        for p in data["paragraphs"]:
            if p["type"] == "p" and p["text"]:
                excerpt = p["text"][:155].rsplit(" ", 1)[0] + "…"
                break
        if not excerpt: excerpt = title

    date_str = date_str or datetime.today().strftime("%Y-%m-%d")

    # Save cover + inline images
    post_dir = os.path.join(BLOG_DIR, "posts", slug)
    os.makedirs(post_dir, exist_ok=True)
    cover_ext = os.path.splitext(cover_fname)[1].lower() or ".jpg"
    cover_out = f"cover{cover_ext}"
    with open(os.path.join(post_dir, cover_out), "wb") as f:
        f.write(cover_bytes)
    inline_map = {}  # original image_idx -> saved filename
    inline_map[0] = cover_out
    for i, (orig_fname, body) in enumerate(inline_images, start=1):
        ext = os.path.splitext(orig_fname)[1].lower() or ".jpg"
        saved = f"img-{i}{ext}"
        with open(os.path.join(post_dir, saved), "wb") as f:
            f.write(body)
        inline_map[i] = saved

    # Build body HTML — preserve heading hierarchy + inline images
    body_html_parts = []
    for p in data["paragraphs"]:
        if p["type"] == "image":
            idx = p["image_idx"]
            if idx == 0: continue  # already shown as cover
            fname = inline_map.get(idx, "")
            if fname:
                body_html_parts.append(f'<figure class="inline-img"><img src="{fname}" alt="" loading="lazy"></figure>')
        elif p["type"] == "h1": body_html_parts.append(f"<h2>{p['text']}</h2>")
        elif p["type"] == "h2": body_html_parts.append(f"<h3>{p['text']}</h3>")
        elif p["type"] == "li": body_html_parts.append(f"<p>• {p['text']}</p>")
        elif p["type"] == "p": body_html_parts.append(f"<p>{p['text']}</p>")
    body_md = "\n\n".join(p["text"] for p in data["paragraphs"] if p.get("text"))

    # Render — use existing render_post_html but inject our pre-built body
    html_template = render_post_html(slug, title, topic, date_str, excerpt, "", cover_out)
    # Replace empty body section with our custom body
    final_html = html_template.replace(
        "{body_html}",
        "\n".join(body_html_parts)
    )
    # If still has empty {body_html} placeholder (since render_post_html consumed it), replace by find
    if not body_html_parts:
        body_html_parts = ["<p>(empty post)</p>"]
    # Just write a fresh version with body inserted
    with open(os.path.join(post_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_template.replace("<!-- BODY -->", "\n".join(body_html_parts)) if "<!-- BODY -->" in html_template else html_template)

    # Save the raw source
    with open(os.path.join(post_dir, "body.md"), "w", encoding="utf-8") as f:
        f.write(body_md)

    # Append to posts.json
    posts_json_path = os.path.join(BLOG_DIR, "posts.json")
    with open(posts_json_path) as f:
        data_json = json.load(f)
    canonical = f"https://harshald13u.github.io/harshalfeatures/blog/posts/{slug}/"
    entry = {
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": f"{canonical}{cover_out}", "url": canonical,
    }
    data_json["posts"] = [p for p in data_json.get("posts", []) if p.get("slug") != slug]
    data_json["posts"].append(entry)
    with open(posts_json_path, "w") as f:
        json.dump(data_json, f, indent=2)

    print(f"Published from .docx: {slug}")
    print(f"  Cover: {cover_out}")
    print(f"  Inline images: {len(inline_images)}")
    print(f"  Body paragraphs: {len(body_html_parts)}")
    return entry

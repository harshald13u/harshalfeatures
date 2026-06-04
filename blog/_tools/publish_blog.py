"""publish_blog.py — Harshal Dasani / Blog publisher v2.

Reads the latest blog .docx in /Features/Blogs/ (top-level only — ignores _system/)
per the spec in Blogs/_system/blog-system.md, and produces:

    /Features/blog/posts/<slug>/index.html       (full post page)
    /Features/blog/posts/<slug>/cover.png        (light theme cover)
    /Features/blog/posts/<slug>/cover-dark.png   (dark theme cover)
    /Features/blog/posts/<slug>/body.md          (raw body for re-render)
    /Features/blog/posts.json                    (appends entry)

    /Features/ harshal-features/sitemap.xml      (adds the post URL — deployed-side)
    /Features/ harshal-features/news-sitemap.xml (Google News rolling 48h window)

Word file format (strict — see Blogs/_system/blog-system.md):
    [Heading 1]   Title
    [Normal]      By Harshal Dasani — Business Head, INVasset PMS · DD Mon YYYY
    [Normal]      Topic: <stock-market|commodities|macros|geopolitics>
    [Normal]      Date: YYYY-MM-DD
    [Normal]      Slug: <kebab-case-slug>
    [Normal]      Excerpt: <≤160 char card one-liner>
    [Normal]      SEO Title: <≤60 char>
    [Normal]      Meta Description: <≤155 char>
    [Normal]      Focus Keywords: term1, term2, term3
    [Normal]      Image Alt: <descriptive alt>
    [Normal]      Image Caption: <≤100 char one-line>
    [Normal]      Author: Harshal Dasani
    <IMG>         Light cover (1600x900, full resolution, no recompression)
    [Normal]      Caption: <one-line>
    [Heading 2]   Section heading
    [Normal]      Body paragraph
    [Heading 3]   Sub-section (optional)
    ...
    [Normal]      COVER — DARK MODE (label)
    <IMG>         Dark cover (same image, dark canvas)

Usage:
    python3 publish_blog.py <docx_path>
or as a module:
    from publish_blog import publish_blog
    entry = publish_blog("/path/to/2026-06-04_slug.docx")
"""
import os, sys, json, re, shutil, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FEATURES = "/sessions/keen-zen-archimedes/mnt/Features"
BLOG_DIR = f"{FEATURES}/blog"
POSTS_DIR = f"{BLOG_DIR}/posts"
POSTS_JSON = f"{BLOG_DIR}/posts.json"
DEPLOYED = f"{FEATURES}/ harshal-features"
SITEMAP_PATH = f"{DEPLOYED}/sitemap.xml"
NEWS_SITEMAP_PATH = f"{DEPLOYED}/news-sitemap.xml"
SITE_BASE = "https://harshald13u.github.io/harshalfeatures"
ENTITIES_PATH = f"{BLOG_DIR}/_tools/entities.json"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

METADATA_LABELS = [
    "Topic", "Date", "Slug", "Excerpt", "SEO Title", "Meta Description",
    "Focus Keywords", "Image Alt", "Image Caption", "Author",
]
DARK_COVER_MARKER = "COVER — DARK MODE"   # em-dash per spec


# ---------------------------------------------------------------------------
# .docx extraction
# ---------------------------------------------------------------------------
def extract_docx(docx_path):
    """Walk the .docx and return an ordered stream of paragraphs and images.

    Returns:
        {
          "images": [(filename, bytes), ...],           # only those used in document body
          "paragraphs": [
              {"type": "h1"|"h2"|"h3"|"p"|"image", "text": str, "image_idx": int|None},
              ...
          ]
        }
    """
    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")
        rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8")
        # rId -> word/media/<file>
        rels_root = ET.fromstring(rels_xml)
        rid_to_target = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels_root.findall(f"{{{PKG_NS}}}Relationship")
        }
        # Cache image bytes
        media_bytes = {}
        for name in z.namelist():
            if name.startswith("word/media/"):
                media_bytes[os.path.basename(name)] = z.read(name)

    root = ET.fromstring(doc_xml)
    body = root.find(f"{{{W_NS}}}body")
    paragraphs = []
    images = []
    fname_to_idx = {}

    def style_of(p):
        pStyle = p.find(f"{{{W_NS}}}pPr/{{{W_NS}}}pStyle")
        if pStyle is None:
            return ""
        return pStyle.attrib.get(f"{{{W_NS}}}val", "")

    def text_of(p):
        return "".join((t.text or "") for t in p.iter(f"{{{W_NS}}}t"))

    def embed_ids_of(p):
        out = []
        for blip in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
            eid = blip.attrib.get(f"{{{R_NS}}}embed")
            if eid:
                out.append(eid)
        return out

    for p in body.findall(f"{{{W_NS}}}p"):
        style = style_of(p).lower()
        # Heading style detection. Word stores them as "Heading1" or "Heading 1"
        norm = style.replace(" ", "")
        if norm.startswith("heading1") or norm == "title":
            block_type = "h1"
        elif norm.startswith("heading2"):
            block_type = "h2"
        elif norm.startswith("heading3"):
            block_type = "h3"
        else:
            block_type = "p"

        # Inline images first (preserve insertion order)
        for eid in embed_ids_of(p):
            target = rid_to_target.get(eid, "")
            fname = os.path.basename(target)
            if not fname or fname not in media_bytes:
                continue
            if fname not in fname_to_idx:
                fname_to_idx[fname] = len(images)
                images.append((fname, media_bytes[fname]))
            paragraphs.append({"type": "image", "text": "", "image_idx": fname_to_idx[fname]})

        text = text_of(p).strip()
        if text:
            paragraphs.append({"type": block_type, "text": text, "image_idx": None})

    return {"images": images, "paragraphs": paragraphs}


# ---------------------------------------------------------------------------
# Metadata parsing
# ---------------------------------------------------------------------------
def parse_metadata_block(paragraphs):
    """Find the bold-labeled metadata block, return dict + the index ranges to skip.

    Returns:
        (metadata: dict[str -> str], skip_idxs: set[int])
    """
    label_pattern = re.compile(
        r"^\s*(?P<label>" + "|".join(re.escape(L) for L in METADATA_LABELS) + r")\s*:\s*(?P<value>.*)$"
    )
    metadata = {}
    skip = set()
    for i, p in enumerate(paragraphs):
        if p["type"] != "p":
            continue
        m = label_pattern.match(p["text"])
        if m:
            metadata[m.group("label")] = m.group("value").strip()
            skip.add(i)
    return metadata, skip


def find_first_image_idx(paragraphs):
    for i, p in enumerate(paragraphs):
        if p["type"] == "image":
            return i
    return None


def find_dark_marker_idx(paragraphs):
    """Return the index of the paragraph that contains 'COVER — DARK MODE' (or close variants)."""
    for i, p in enumerate(paragraphs):
        if p["type"] != "p":
            continue
        text = p["text"].upper().replace("–", "—").replace("-", "—")
        if "COVER" in text and "DARK MODE" in text:
            return i
    return None


def find_byline_idx(paragraphs):
    for i, p in enumerate(paragraphs):
        if p["type"] == "p" and p["text"].lower().startswith("by harshal dasani"):
            return i
    return None


def find_caption_idx(paragraphs, after_idx):
    """First 'Caption: ...' line after the light cover image."""
    for i in range(after_idx + 1, len(paragraphs)):
        p = paragraphs[i]
        if p["type"] != "p":
            continue
        if p["text"].lower().startswith("caption:"):
            return i
    return None


# ---------------------------------------------------------------------------
# Body HTML render
# ---------------------------------------------------------------------------
def html_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


def inline_entity_links(text, entities, used_in_post):
    """Wrap FIRST mention of each known entity in the post with a Wikidata sameAs link.

    Matches the entity by `name` OR any `alias`. An entity is only linked once per post,
    keyed by the canonical name in `used_in_post` so callers can read it back for JSON-LD.

    `entities` should already be filtered to those with a wikidata Q-ID.
    """
    if not entities:
        return text

    # Build (candidate_string, entity) pairs, sorted by length DESC so we prefer
    # longer matches first ("Tata Consultancy Services" before "TCS").
    cands = []
    for ent in entities:
        name = ent.get("name", "")
        if not name:
            continue
        for cand in [name] + list(ent.get("aliases") or []):
            cand = cand.strip()
            if cand:
                cands.append((cand, ent))
    cands.sort(key=lambda x: -len(x[0]))

    out = text
    for cand, ent in cands:
        name = ent["name"]
        if name in used_in_post:
            continue
        qid = ent.get("wikidata")
        if not qid:
            continue
        # Case-sensitive for all-uppercase candidates (tickers / acronyms), case-insensitive otherwise.
        flags = 0 if cand.isupper() else re.IGNORECASE
        pat = re.compile(r"(?<![A-Za-z0-9_])(" + re.escape(cand) + r")(?![A-Za-z0-9_])", flags)
        for m in pat.finditer(out):
            # Skip if the match is inside an existing tag
            prefix = out[:m.start()]
            if prefix.rfind("<") > prefix.rfind(">"):
                continue
            link = f'<a href="https://www.wikidata.org/wiki/{qid}" rel="external nofollow noopener" target="_blank">{m.group(1)}</a>'
            out = out[:m.start()] + link + out[m.end():]
            used_in_post.add(name)
            break
    return out


def render_body_html(paragraphs, skip_idxs, dark_marker_idx, light_cover_idx,
                     dark_cover_idx, caption_idx, image_caption,
                     post_dir, entities=None):
    """Render the body HTML.

    Skips: metadata block, byline (rendered elsewhere), the light cover image (rendered as hero),
    the 'Caption:' line under the cover (used as figcaption), the DARK MODE marker label, the dark cover image.
    """
    hard_skip = set(skip_idxs)
    if dark_marker_idx is not None:
        hard_skip.add(dark_marker_idx)
    if light_cover_idx is not None:
        hard_skip.add(light_cover_idx)
    if dark_cover_idx is not None:
        hard_skip.add(dark_cover_idx)
    if caption_idx is not None:
        hard_skip.add(caption_idx)

    used_entities = set()
    parts = []
    for i, p in enumerate(paragraphs):
        if i in hard_skip:
            continue
        if p["type"] == "image":
            # Any remaining inline image (unusual — spec says only cover images). Render as figure.
            idx = p["image_idx"]
            # Image file already saved by caller
            fname = f"img-{idx}.png"
            parts.append(f'<figure class="inline-figure"><img src="{fname}" alt="" loading="lazy"></figure>')
            continue

        text = html_escape(p["text"])
        if entities:
            text = inline_entity_links(text, entities, used_entities)

        if p["type"] == "h1":
            # Should not appear in body (the H1 lives in <main>).
            parts.append(f"<h2>{text}</h2>")
        elif p["type"] == "h2":
            parts.append(f'<h2 id="{slugify_anchor(p["text"])}">{text}</h2>')
        elif p["type"] == "h3":
            parts.append(f'<h3 id="{slugify_anchor(p["text"])}">{text}</h3>')
        else:
            parts.append(f"<p>{text}</p>")

    return "\n".join(parts)


def slugify_anchor(s):
    s = re.sub(r"[^A-Za-z0-9\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:80] or "section"


# ---------------------------------------------------------------------------
# Image saving — light + dark covers, lossless
# ---------------------------------------------------------------------------
def save_cover(images, idx, post_dir, basename):
    """Write image bytes to post_dir/basename + native ext, return filename used."""
    fname, blob = images[idx]
    ext = os.path.splitext(fname)[1].lower() or ".png"
    out_name = f"{basename}{ext}"
    with open(os.path.join(post_dir, out_name), "wb") as f:
        f.write(blob)
    return out_name


# ---------------------------------------------------------------------------
# JSON-LD + meta
# ---------------------------------------------------------------------------
def article_jsonld(title, excerpt, slug, topic, date_str, canonical, light_cover_url,
                   focus_keywords, image_alt, used_entities, entities):
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    published_iso = f"{date_str}T09:00:00+05:30"

    about = []
    if entities:
        idx = {e.get("name"): e for e in entities}
        for name in used_entities:
            ent = idx.get(name)
            if not ent or not ent.get("wikidata"):
                continue
            about.append({
                "@type": "Thing",
                "name": name,
                "sameAs": f"https://www.wikidata.org/wiki/{ent['wikidata']}",
            })

    keywords_list = [k.strip() for k in focus_keywords.split(",") if k.strip()] if focus_keywords else []

    article = {
        "@type": "NewsArticle",
        "@id": f"{canonical}#article",
        "headline": title[:110],
        "alternativeHeadline": title,
        "description": excerpt,
        "datePublished": published_iso,
        "dateModified": today_iso,
        "url": canonical,
        "mainEntityOfPage": canonical,
        "image": {
            "@type": "ImageObject",
            "url": light_cover_url,
            "width": 1600,
            "height": 900,
            "caption": image_alt or title,
        },
        "author": {"@id": f"{SITE_BASE}/#person"},
        "publisher": {"@id": f"{SITE_BASE}/#person"},
        "articleSection": topic.replace("-", " ").title(),
        "inLanguage": "en-IN",
        "isAccessibleForFree": True,
    }
    if keywords_list:
        article["keywords"] = keywords_list
    if about:
        article["about"] = about

    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Harshal Dasani", "item": f"{SITE_BASE}/"},
            {"@type": "ListItem", "position": 2, "name": "Blogs", "item": f"{SITE_BASE}/blog/"},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    }

    person = {
        "@type": "Person",
        "@id": f"{SITE_BASE}/#person",
        "name": "Harshal Dasani",
        "url": f"{SITE_BASE}/",
        "image": f"{SITE_BASE}/harshal-dasani.jpg",
        "jobTitle": "Business Head, INVasset PMS",
        "worksFor": {"@type": "Organization", "name": "INVasset PMS", "url": "https://invasset.com/"},
        "sameAs": [
            "https://www.linkedin.com/in/harshaldasani/",
            "https://twitter.com/HarshalDasanii",
            "https://x.com/HarshalDasanii",
        ],
    }

    graph = {"@context": "https://schema.org", "@graph": [person, article, breadcrumb]}
    return json.dumps(graph, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Sitemaps
# ---------------------------------------------------------------------------
def upsert_sitemap_post(sitemap_path, post_url, today, image_url=None, image_caption=None):
    """Add the post URL to sitemap.xml if absent; refresh lastmod."""
    if not os.path.exists(sitemap_path):
        print(f"[sitemap] WARN: {sitemap_path} not found, skipping")
        return
    xml = open(sitemap_path, "r", encoding="utf-8").read()
    if post_url in xml:
        # Already there — refresh its lastmod
        xml = re.sub(
            r"(<loc>" + re.escape(post_url) + r"</loc>\s*<lastmod>)[0-9-]+(</lastmod>)",
            rf"\g<1>{today}\g<2>",
            xml,
        )
        open(sitemap_path, "w", encoding="utf-8").write(xml)
        return
    # Insert before </urlset>
    img_block = ""
    if image_url:
        cap = html_escape(image_caption or "")
        img_block = f"""
    <image:image>
      <image:loc>{image_url}</image:loc>
      <image:title>{cap}</image:title>
    </image:image>"""
    block = f"""  <url>
    <loc>{post_url}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.85</priority>{img_block}
  </url>
"""
    xml = xml.replace("</urlset>", block + "</urlset>")
    open(sitemap_path, "w", encoding="utf-8").write(xml)


def upsert_news_sitemap(news_sitemap_path, post_url, title, date_str, language="en"):
    """Maintain a rolling 48-hour Google News sitemap.

    Strategy: rebuild from scratch each call — only keep <url> blocks whose news:publication_date
    is within the last 48 hours from now.
    """
    if not os.path.exists(news_sitemap_path):
        print(f"[news-sitemap] WARN: {news_sitemap_path} not found, skipping")
        return
    xml = open(news_sitemap_path, "r", encoding="utf-8").read()
    pub_iso = f"{date_str}T09:00:00+05:30"
    new_entry = f"""  <url>
    <loc>{post_url}</loc>
    <news:news>
      <news:publication>
        <news:name>Harshal Dasani</news:name>
        <news:language>{language}</news:language>
      </news:publication>
      <news:publication_date>{pub_iso}</news:publication_date>
      <news:title>{html_escape(title)}</news:title>
    </news:news>
  </url>
"""
    # Drop the empty comment placeholder if present
    xml = re.sub(r"<!--[^>]*?Auto-populated[^>]*?-->", "", xml)
    # Strip existing entry for the same URL
    xml = re.sub(
        r"\s*<url>\s*<loc>" + re.escape(post_url) + r"</loc>[\s\S]*?</url>",
        "",
        xml,
    )
    # Insert before </urlset>
    xml = xml.replace("</urlset>", new_entry + "</urlset>")
    open(news_sitemap_path, "w", encoding="utf-8").write(xml)


# ---------------------------------------------------------------------------
# Post HTML template
# ---------------------------------------------------------------------------
POST_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">

<title>{seo_title} — Harshal Dasani</title>
<meta name="description" content="{meta_description}">
<meta name="keywords" content="{keywords}">
<meta name="author" content="Harshal Dasani">
<meta name="publisher" content="Harshal Dasani">
<meta name="application-name" content="Harshal Dasani">
<meta http-equiv="content-language" content="en-IN">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="googlebot" content="index, follow">
<meta name="bingbot" content="index, follow">
<meta name="news_keywords" content="{keywords}">
<meta name="article:section" content="{topic_label}">
<meta name="article:author" content="Harshal Dasani">
<meta name="article:published_time" content="{date_iso}">
<meta name="article:modified_time" content="{modified_iso}">

<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="en-IN" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:site_name" content="Harshal Dasani">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{meta_description}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{light_cover_url}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1600">
<meta property="og:image:height" content="900">
<meta property="og:image:alt" content="{image_alt}">
<meta property="og:locale" content="en_IN">
<meta property="article:published_time" content="{date_iso}">
<meta property="article:modified_time" content="{modified_iso}">
<meta property="article:author" content="Harshal Dasani">
<meta property="article:section" content="{topic_label}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@HarshalDasanii">
<meta name="twitter:creator" content="@HarshalDasanii">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{meta_description}">
<meta name="twitter:image" content="{light_cover_url}">
<meta name="twitter:image:alt" content="{image_alt}">
<meta name="twitter:label1" content="Author">
<meta name="twitter:data1" content="Harshal Dasani — Business Head, INVasset PMS">
<meta name="twitter:label2" content="Section">
<meta name="twitter:data2" content="{topic_label}">

<meta name="theme-color" content="#0e0c0a" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#ebe5d7" media="(prefers-color-scheme: light)">

<link rel="manifest" href="../../../manifest.json">
<link rel="apple-touch-icon" href="../../../apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="512x512" href="../../../icon-512.png">
<link rel="icon" type="image/png" sizes="192x192" href="../../../icon-192.png">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">

<script type="application/ld+json">
{jsonld}
</script>
<script>(function(){{try{{var t=localStorage.getItem('hd-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}}})();</script>

<style>
:root{{--bg:#0e0c0a;--bg-2:#15110d;--ink:#ece4d3;--ink-2:#c9c0ad;--muted:#8a8273;--rule:rgba(236,228,211,0.10);--accent:#d4a64a;}}
html[data-theme="light"]{{--bg:#ebe5d7;--bg-2:#ddd4c1;--ink:#1a3458;--ink-2:#3a527a;--muted:#54687f;--rule:rgba(26,52,88,0.18);--accent:#b8852b;}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0;background:var(--bg);color:var(--ink-2);transition:background-color .3s,color .3s}}
body{{font-family:'Inter',sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased;font-size:16.5px}}
/* Desktop reading size — matches home page pattern (zoom: 1.3 at >=1180px) */
@media (min-width: 1180px){{body{{zoom:1.3}}}}
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
.theme-toggle{{position:fixed;top:18px;right:18px;width:42px;height:42px;border-radius:50%;border:1px solid var(--rule);background:var(--bg-2);color:var(--ink);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:18px;z-index:1000}}
.page{{max-width:760px;margin:0 auto;padding:56px 24px 96px}}
.crumb{{font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);margin-bottom:24px}}
.crumb a{{color:var(--muted)}}
.crumb a:hover{{color:var(--accent)}}
.topic-pill{{display:inline-block;padding:5px 12px;border:1px solid var(--rule);border-radius:999px;font-size:11px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--accent);margin-bottom:18px;background:var(--bg-2)}}
h1{{font-family:'Inter',sans-serif;font-weight:800;font-size:clamp(30px,4.6vw,46px);line-height:1.12;letter-spacing:-0.02em;color:var(--ink);margin:0 0 14px}}
.subtitle{{font-size:18.5px;color:var(--ink-2);line-height:1.5;margin:0 0 22px;font-weight:400}}
.byline{{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted);margin:0 0 30px;flex-wrap:wrap}}
.byline strong{{color:var(--ink);font-weight:600}}
.cover{{position:relative;margin:0 0 14px;border-radius:8px;overflow:hidden;border:1px solid var(--rule);aspect-ratio:16/9;background:var(--bg-2)}}
.cover img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}}
/* Default theme = dark → show dark cover only. Light theme → show light cover only.
   Pure data-theme driven; we DO NOT use prefers-color-scheme (which can disagree with the user's manual theme choice). */
.cover .light-only{{opacity:0}}
.cover .dark-only{{opacity:1}}
html[data-theme="light"] .cover .light-only{{opacity:1}}
html[data-theme="light"] .cover .dark-only{{opacity:0}}
figcaption{{font-size:13px;color:var(--muted);font-style:italic;text-align:center;margin:0 0 32px}}
h2{{font-weight:700;font-size:24px;color:var(--ink);margin:38px 0 12px;letter-spacing:-0.01em;padding-bottom:6px;border-bottom:1px solid var(--rule)}}
h3{{font-weight:700;font-size:18px;color:var(--accent);margin:26px 0 8px}}
p{{margin:0 0 18px}}
.inline-figure{{margin:24px 0}}
.inline-figure img{{width:100%;height:auto;border-radius:6px;border:1px solid var(--rule)}}
blockquote{{margin:26px 0;padding:6px 0 6px 22px;border-left:3px solid var(--accent);font-style:italic;color:var(--ink);font-size:18px}}
strong{{color:var(--ink);font-weight:700}}
.next{{margin-top:54px;padding-top:24px;border-top:1px solid var(--rule);display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}
.next a{{font-size:13px}}
.footer-meta{{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.6}}
@media print{{.theme-toggle{{display:none}}}}
</style>
</head>
<body>
<button class="theme-toggle" aria-label="Toggle theme" onclick="(function(){{var c=document.documentElement.getAttribute('data-theme')||'dark';var n=c==='light'?'dark':'light';document.documentElement.setAttribute('data-theme',n);try{{localStorage.setItem('hd-theme',n)}}catch(e){{}}}})()">☼</button>
<main class="page" itemscope itemtype="https://schema.org/NewsArticle">
  <nav class="crumb" aria-label="Breadcrumb"><a href="../../../">Harshal Dasani</a> &middot; <a href="../../">Blogs</a> &middot; <span>{topic_label}</span></nav>
  <span class="topic-pill">{topic_label}</span>
  <h1 itemprop="headline">{title_html}</h1>
  <p class="subtitle" itemprop="description">{excerpt_html}</p>
  <p class="byline">By <strong itemprop="author">Harshal Dasani</strong> &middot; <span>Business Head, INVasset PMS</span> &middot; <time itemprop="datePublished" datetime="{date_iso}">{date_pretty}</time></p>
  <figure class="cover">
    <img src="{light_cover_filename}" alt="{image_alt}" width="1600" height="900" loading="eager" fetchpriority="high" itemprop="image" class="light-only">
    <img src="{dark_cover_filename}" alt="{image_alt}" width="1600" height="900" loading="eager" fetchpriority="high" class="dark-only">
  </figure>
  <figcaption>{image_caption_html}</figcaption>
  <article itemprop="articleBody">
{body_html}
  </article>
  <div class="next">
    <a href="../../">&larr; All blogs by Harshal Dasani</a>
    <a href="../../../tracker/">Media Features Tracker &rarr;</a>
  </div>
  <p class="footer-meta">Published {date_pretty} &middot; Updated {modified_pretty} &middot; <a href="../../../">harshald13u.github.io/harshalfeatures</a></p>
</main>
<script>
// Dual-cover swap is driven entirely by CSS opacity on data-theme.
// We also fire a pageshow listener so bfcache returns to the right cover.
(function(){{
  function refresh(){{
    // No-op: CSS already keys off [data-theme]. Just bump a tiny inline custom property to
    // force any cached state to reflow on bfcache returns.
    document.documentElement.style.setProperty('--cover-tick', Date.now());
  }}
  refresh();
  window.addEventListener('pageshow', refresh);
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def pretty_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%-d %B %Y")


def load_entities():
    if not os.path.exists(ENTITIES_PATH):
        return []
    try:
        with open(ENTITIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Flatten any grouping
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            flat = []
            for v in data.values():
                if isinstance(v, list):
                    flat.extend(v)
            return flat
    except Exception as e:
        print(f"[entities] warn: {e}")
    return []


# ---------------------------------------------------------------------------
# Main publish
# ---------------------------------------------------------------------------
def publish_blog(docx_path):
    print(f"[publish] reading {docx_path}")
    ex = extract_docx(docx_path)
    paras = ex["paragraphs"]
    images = ex["images"]
    if not images:
        raise SystemExit("No images in .docx — cover image is required.")

    metadata, skip = parse_metadata_block(paras)
    missing = [L for L in METADATA_LABELS if L not in metadata]
    if missing:
        raise SystemExit(f"Metadata block missing required labels: {missing}")

    # Title = first Heading 1
    title = None
    for i, p in enumerate(paras):
        if p["type"] == "h1":
            title = p["text"]
            skip.add(i)
            break
    if not title:
        raise SystemExit("No Heading 1 found — title required.")

    byline_idx = find_byline_idx(paras)
    if byline_idx is not None:
        skip.add(byline_idx)

    # Find covers
    dark_marker = find_dark_marker_idx(paras)
    # Light cover = first image paragraph (before dark marker)
    light_cover_p_idx = None
    for i, p in enumerate(paras):
        if p["type"] == "image":
            if dark_marker is None or i < dark_marker:
                light_cover_p_idx = i
                break
    if light_cover_p_idx is None:
        raise SystemExit("No light cover image found before the DARK MODE marker.")

    # Dark cover = first image paragraph AFTER the dark marker
    dark_cover_p_idx = None
    if dark_marker is not None:
        for i in range(dark_marker + 1, len(paras)):
            if paras[i]["type"] == "image":
                dark_cover_p_idx = i
                break
    if dark_cover_p_idx is None:
        print("[publish] WARN: dark cover not found — falling back to light cover for both themes.")

    light_img_idx = paras[light_cover_p_idx]["image_idx"]
    dark_img_idx = paras[dark_cover_p_idx]["image_idx"] if dark_cover_p_idx is not None else light_img_idx

    caption_idx = find_caption_idx(paras, light_cover_p_idx)

    # --- Identifiers / paths ---
    slug = metadata["Slug"].strip()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise SystemExit(f"Slug not kebab-case ASCII: {slug!r}")
    date_str = metadata["Date"].strip()
    topic = metadata["Topic"].strip().lower()
    if topic not in {"stock-market", "commodities", "macros", "geopolitics"}:
        raise SystemExit(f"Invalid topic: {topic}")
    excerpt = metadata["Excerpt"].strip()
    seo_title = metadata["SEO Title"].strip()
    meta_desc = metadata["Meta Description"].strip()
    focus_kw = metadata["Focus Keywords"].strip()
    image_alt = metadata["Image Alt"].strip()
    image_caption = metadata["Image Caption"].strip()

    post_dir = os.path.join(POSTS_DIR, slug)
    os.makedirs(post_dir, exist_ok=True)

    # Save covers at full resolution, native ext
    light_cover_filename = save_cover(images, light_img_idx, post_dir, "cover")
    dark_cover_filename = save_cover(images, dark_img_idx, post_dir, "cover-dark")
    print(f"[publish] covers saved: light={light_cover_filename} dark={dark_cover_filename}")

    # Render body — strip metadata + byline + cover markers
    canonical = f"{SITE_BASE}/blog/posts/{slug}/"
    light_cover_url = f"{canonical}{light_cover_filename}"
    dark_cover_url = f"{canonical}{dark_cover_filename}"

    entities = load_entities()
    # Filter to entities with a Wikidata Q-ID so sameAs is always present
    entities_with_qid = [e for e in entities if e.get("name") and e.get("wikidata")]
    used_entities = set()

    body_html = render_body_html(
        paras, skip, dark_marker, light_cover_p_idx, dark_cover_p_idx, caption_idx,
        image_caption, post_dir, entities=entities_with_qid,
    )
    # Recover the set of entities actually used by re-scanning the rendered HTML
    for ent in entities_with_qid:
        qid = ent.get("wikidata") or ""
        if not qid:
            continue
        if re.search(r"wikidata\.org/wiki/" + re.escape(qid) + r"\b", body_html):
            used_entities.add(ent["name"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_iso = f"{date_str}T09:00:00+05:30"
    modified_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    jsonld = article_jsonld(
        title=title, excerpt=excerpt, slug=slug, topic=topic, date_str=date_str,
        canonical=canonical, light_cover_url=light_cover_url,
        focus_keywords=focus_kw, image_alt=image_alt,
        used_entities=used_entities, entities=entities_with_qid,
    )

    topic_label = {
        "stock-market": "Stock Market",
        "commodities": "Commodities",
        "macros": "Macros",
        "geopolitics": "Geopolitics",
    }[topic]

    html = POST_TEMPLATE.format(
        seo_title=html_escape(seo_title),
        meta_description=html_escape(meta_desc),
        keywords=html_escape(focus_kw),
        canonical=canonical,
        og_title=html_escape(seo_title),
        light_cover_url=light_cover_url,
        image_alt=html_escape(image_alt),
        light_cover_filename=light_cover_filename,
        dark_cover_filename=dark_cover_filename,
        topic_label=topic_label,
        title_html=html_escape(title),
        excerpt_html=html_escape(excerpt),
        image_caption_html=html_escape(image_caption),
        date_iso=date_iso,
        date_pretty=pretty_date(date_str),
        modified_iso=modified_iso,
        modified_pretty=pretty_date(today),
        body_html=body_html,
        jsonld=jsonld,
    )

    with open(os.path.join(post_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[publish] wrote {post_dir}/index.html  ({len(html)} bytes)")

    # Save the body text for re-rendering later if needed
    body_md_lines = []
    for i, p in enumerate(paras):
        if i in skip or p["type"] == "image":
            continue
        if i in (dark_marker, light_cover_p_idx, dark_cover_p_idx, caption_idx):
            continue
        prefix = {"h1": "# ", "h2": "## ", "h3": "### ", "p": ""}.get(p["type"], "")
        body_md_lines.append(prefix + p["text"])
    with open(os.path.join(post_dir, "body.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(body_md_lines))

    # Append to posts.json
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON) as f:
            data = json.load(f)
    else:
        data = {"posts": []}
    data["posts"] = [p for p in data.get("posts", []) if p.get("slug") != slug]
    data["posts"].append({
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": light_cover_url, "url": canonical,
    })
    data["posts"].sort(key=lambda p: p.get("date", ""), reverse=True)
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[publish] posts.json updated ({len(data['posts'])} posts total)")

    # Sitemap + news-sitemap (DEPLOYED side)
    upsert_sitemap_post(SITEMAP_PATH, canonical, today, light_cover_url, image_caption)
    upsert_news_sitemap(NEWS_SITEMAP_PATH, canonical, title, date_str)
    print(f"[publish] sitemap.xml + news-sitemap.xml updated")

    return {
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": light_cover_url, "url": canonical,
        "post_dir": post_dir,
        "light_cover": light_cover_filename, "dark_cover": dark_cover_filename,
        "used_entities": sorted(used_entities),
        "body_paragraphs": sum(1 for p in paras if p["type"] in ("p","h2","h3")) - len(skip),
    }


def find_latest_blog():
    """Return the newest .docx in Blogs/ (ignores _system/, ignores temp files starting with ~$)."""
    blogs_dir = f"{FEATURES}/Blogs"
    candidates = []
    for fn in os.listdir(blogs_dir):
        if fn.startswith("~$") or fn.startswith("."):
            continue
        if not fn.lower().endswith(".docx"):
            continue
        path = os.path.join(blogs_dir, fn)
        if not os.path.isfile(path):
            continue
        m = re.match(r"(\d{4}-\d{2}-\d{2})_", fn)
        if m:
            key = (m.group(1), os.path.getmtime(path))
        else:
            key = ("0000-00-00", os.path.getmtime(path))
        candidates.append((key, path))
    if not candidates:
        raise SystemExit("No .docx blogs in /Features/Blogs/")
    candidates.sort(reverse=True)
    return candidates[0][1]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = find_latest_blog()
    result = publish_blog(target)
    print()
    print("=" * 60)
    print(json.dumps(result, indent=2, ensure_ascii=False))

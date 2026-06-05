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
FEATURES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo/workspace root
BLOG_DIR = f"{FEATURES}/blog"
POSTS_DIR = f"{BLOG_DIR}/posts"
POSTS_JSON = f"{BLOG_DIR}/posts.json"
LEGACY_DEPLOYED = os.path.join(FEATURES, " harshal-features")
DEPLOYED = LEGACY_DEPLOYED if os.path.isdir(LEGACY_DEPLOYED) else FEATURES
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

    # Walk paragraphs AND tables in document order. We iterate body children directly
    # so a w:tbl interleaved between w:p elements lands in the right position.
    for child in list(body):
        tag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag

        if tag == "p":
            p = child
            style = style_of(p).lower()
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

        elif tag == "tbl":
            # Parse the table into rows of cells (text only). Header detection:
            # row 0 is treated as <thead> if it looks like header (no numbers, all bold-ish).
            tbl = child
            rows_data = []
            for tr in tbl.findall(f"{{{W_NS}}}tr"):
                row_cells = []
                for tc in tr.findall(f"{{{W_NS}}}tc"):
                    cell_text = "".join((t.text or "") for t in tc.iter(f"{{{W_NS}}}t")).strip()
                    # gridSpan for merged cells
                    gridSpan = tc.find(f"{{{W_NS}}}tcPr/{{{W_NS}}}gridSpan")
                    colspan = int(gridSpan.attrib.get(f"{{{W_NS}}}val", "1")) if gridSpan is not None else 1
                    row_cells.append({"text": cell_text, "colspan": colspan})
                if row_cells:
                    rows_data.append(row_cells)
            if rows_data:
                paragraphs.append({"type": "table", "rows": rows_data, "text": "", "image_idx": None})

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
def normalize_dashes(s):
    if not s:
        return s
    s = s.replace("&mdash;", "\u2014").replace("&#8212;", "\u2014")
    s = re.sub(r"[ \t]*\u2014[ \t]*", ", ", s)
    s = re.sub(r",[ \t]*([.,;:!?])", r"\1", s)
    s = re.sub(r",[ \t]*(</[A-Za-z])", r"\1", s)
    return s


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

        if p["type"] == "table":
            rows = p.get("rows", [])
            if not rows:
                continue
            # Heuristic for thead: row 0 if all cells are short text and it's not a single full-width cell
            thead_html = ""
            tbody_rows = rows
            first = rows[0]
            def _is_datalike(s):
                s = (s or "").strip()
                if not s:
                    return False
                if s[0] in "₹$€£":
                    return True
                return bool(re.match(r"^[~≈]?\s*[\d][\d,\.\s]*\s*(cr|bn|mn|k|%|crore|lakh|x)?$", s, re.I))
            is_header_row = (
                len(first) >= 2 and
                not any(_is_datalike(c.get("text", "")) for c in first)
            )
            def _cell_attrs(c):
                cs = c.get("colspan", 1)
                return f' colspan="{cs}"' if cs > 1 else ""
            if is_header_row:
                header_cells = []
                for c in first:
                    header_cells.append(f"<th{_cell_attrs(c)}>{html_escape(c.get('text',''))}</th>")
                thead_html = "<thead><tr>" + "".join(header_cells) + "</tr></thead>"
                tbody_rows = rows[1:]
            body_trs = []
            for r in tbody_rows:
                # If the row is a single-cell "section divider" (spanning all columns), render as a sub-header
                if len(r) == 1 and r[0].get("colspan", 1) >= len(first):
                    cell_html = inline_entity_links(html_escape(r[0].get("text", "")), entities or [], used_entities)
                    body_trs.append(f'<tr class="tbl-section"><td colspan="{len(first)}">{cell_html}</td></tr>')
                else:
                    cells = []
                    for c in r:
                        cell_html = inline_entity_links(html_escape(c.get("text", "")), entities or [], used_entities)
                        cells.append(f"<td{_cell_attrs(c)}>{cell_html}</td>")
                    _t0 = (r[0].get("text", "") if r else "").strip().lower()
                    _is_total = _t0.startswith(("total", "combined", "overall", "grand total", "net total"))
                    body_trs.append(('<tr class="tbl-total">' if _is_total else "<tr>") + "".join(cells) + "</tr>")
            tbody_html = "<tbody>" + "".join(body_trs) + "</tbody>"
            parts.append(f'<div class="table-wrap"><table class="post-table">{thead_html}{tbody_html}</table></div>')
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
# SEO standard: Key Takeaways box + FAQ (FAQPage schema). All optional —
# the publisher emits them only when the .docx contains the named sections.
# ---------------------------------------------------------------------------
TAKEAWAYS_TITLES = {"key takeaways", "takeaways", "the takeaways", "tl;dr", "summary"}
FAQ_TITLES = {"faq", "faqs", "frequently asked questions", "questions and answers", "q&a", "q & a"}

def extract_special_sections(paragraphs):
    """Pull a 'Key Takeaways' H2 block (bullets) and an 'FAQ' H2 block (H3 question +
    paragraph answer) out of the body so they render as a styled box / FAQPage.

    Returns (takeaways:list[str], faq:list[(q,a)], skip_idxs:set[int]).
    """
    takeaways, faq, skip = [], [], set()
    n = len(paragraphs)
    i = 0
    while i < n:
        p = paragraphs[i]
        if p.get("type") == "h2":
            t = (p.get("text") or "").strip().lower().rstrip(":")
            if t in TAKEAWAYS_TITLES:
                skip.add(i); i += 1
                while i < n and paragraphs[i].get("type") == "p":
                    txt = re.sub(r"^[\u2022\u2023\u25E6\u2043\u2219*\-]\s*", "", paragraphs[i]["text"].strip())
                    if txt:
                        takeaways.append(txt)
                    skip.add(i); i += 1
                continue
            if t in FAQ_TITLES:
                skip.add(i); i += 1
                while i < n and paragraphs[i].get("type") != "h2":
                    pp = paragraphs[i]
                    if pp.get("type") == "h3":
                        q = pp["text"].strip()
                        skip.add(i); i += 1
                        ans = []
                        while i < n and paragraphs[i].get("type") == "p":
                            ans.append(paragraphs[i]["text"].strip())
                            skip.add(i); i += 1
                        a = " ".join(x for x in ans if x).strip()
                        if q and a:
                            faq.append((q, a))
                    else:
                        skip.add(i); i += 1
                continue
        i += 1
    return takeaways, faq, skip


def render_takeaways_html(items):
    if not items:
        return ""
    lis = "".join(f"<li>{html_escape(t)}</li>" for t in items)
    return ('<div class="key-takeaways"><div class="kt-label">Key takeaways</div>'
            f"<ul>{lis}</ul></div>\n")


def render_faq_html(faq):
    if not faq:
        return ""
    items = "\n    ".join(
        f'<div class="faq-q"><h3>{html_escape(q)}</h3><p>{html_escape(a)}</p></div>'
        for q, a in faq
    )
    return ('  <section class="post-faq" aria-labelledby="faq-heading">\n'
            '    <h2 id="faq-heading">Frequently asked questions</h2>\n    '
            + items + "\n  </section>\n")


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
                   focus_keywords, image_alt, used_entities, entities, word_count, reading_minutes,
                   article_body_text=None, mentioned_entities=None, faq_pairs=None):
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    published_iso = f"{date_str}T09:00:00+05:30"

    # `about` = the core entities the article is centrally about (E-E-A-T strong signal)
    about = []
    # `mentions` = every other entity the article mentions but isn't centrally about
    mentions = []
    if entities:
        idx = {e.get("name"): e for e in entities}
        used = set(used_entities or [])
        mentioned = set(mentioned_entities or []) - used  # exclude any duplicate
        for name in used:
            ent = idx.get(name)
            if not ent or not ent.get("wikidata"):
                continue
            about.append({
                "@type": "Thing",
                "name": name,
                "sameAs": f"https://www.wikidata.org/wiki/{ent['wikidata']}",
            })
        for name in mentioned:
            ent = idx.get(name)
            if not ent or not ent.get("wikidata"):
                continue
            mentions.append({
                "@type": "Thing",
                "name": name,
                "sameAs": f"https://www.wikidata.org/wiki/{ent['wikidata']}",
            })

    keywords_list = [k.strip() for k in focus_keywords.split(",") if k.strip()] if focus_keywords else []

    article = {
        "@type": "BlogPosting",
        "@id": f"{canonical}#article",
        "headline": title[:110],
        "alternativeHeadline": title,
        "description": excerpt,
        "datePublished": published_iso,
        "dateModified": today_iso,
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "image": {
            "@type": "ImageObject",
            "url": light_cover_url,
            "width": 1600,
            "height": 900,
            "caption": image_alt or title,
            "license": f"{SITE_BASE}/",
            "acquireLicensePage": f"{SITE_BASE}/",
        },
        "author": {"@id": f"{SITE_BASE}/#person"},
        "publisher": {"@id": f"{SITE_BASE}/#org"},
        "copyrightHolder": {"@id": f"{SITE_BASE}/#person"},
        "copyrightYear": int(date_str[:4]),
        "articleSection": topic.replace("-", " ").title(),
        "inLanguage": "en-IN",
        "isAccessibleForFree": True,
        "wordCount": word_count,
        "timeRequired": f"PT{reading_minutes}M",
        # Speakable signals to Google Assistant / voice surfaces which parts of the page are summarisable
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": ["h1", ".subtitle"],
        },
    }
    if article_body_text:
        # Truncate huge body to a sane 8000 char window for the schema (Google's accepted limit)
        article["articleBody"] = article_body_text[:8000]
    if keywords_list:
        article["keywords"] = keywords_list
    if about:
        article["about"] = about
    if mentions:
        article["mentions"] = mentions

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
        "description": "Harshal Dasani — markets professional and writer with over a decade in Indian equity markets. Business Head at INVasset PMS, Mumbai. CFA candidate; CA Level II.",
        "worksFor": {"@type": "Organization", "name": "INVasset PMS", "url": "https://invasset.com/"},
        "knowsAbout": ["Indian equity markets", "Portfolio Management Services", "Macroeconomics", "Commodities", "Geopolitics"],
        "alumniOf": "The Institute of Chartered Accountants of India",
        "sameAs": [
            "https://www.linkedin.com/in/harshal-dasani-/",
            "https://x.com/HarshalDasanii",
        ],
    }

    # WebSite with SearchAction so Google can render a site-wide search box in SERPs
    website = {
        "@type": "WebSite",
        "@id": f"{SITE_BASE}/#website",
        "url": f"{SITE_BASE}/",
        "name": "Harshal Dasani",
        "description": "Long-form notes on Indian markets, commodities, macros and geopolitics by Harshal Dasani.",
        "publisher": {"@id": f"{SITE_BASE}/#org"},
        "inLanguage": "en-IN",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{SITE_BASE}/blog/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }

    org = {
        "@type": "Organization",
        "@id": f"{SITE_BASE}/#org",
        "name": "Harshal Dasani",
        "url": f"{SITE_BASE}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"{SITE_BASE}/icon-512.png",
            "width": 512,
            "height": 512,
        },
    }

    nodes = [person, org, website, article, breadcrumb]
    if faq_pairs:
        nodes.append({
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "mainEntity": [
                {"@type": "Question", "name": q,
                 "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in faq_pairs
            ],
        })
    graph = {"@context": "https://schema.org", "@graph": nodes}
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
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
<meta name="googlebot" content="index, follow">
<meta name="bingbot" content="index, follow">
<meta name="news_keywords" content="{keywords}">
<meta name="standout" content="{canonical}">
<meta name="article:section" content="{topic_label}">
<meta name="article:author" content="Harshal Dasani">
<meta name="article:published_time" content="{date_iso}">
<meta name="article:modified_time" content="{modified_iso}">
<meta name="rating" content="general">
<meta name="referrer" content="no-referrer-when-downgrade">

<!-- Dublin Core (recognised by academic / news indexers like Highbeam, ProQuest) -->
<meta name="DC.title" content="{seo_title}">
<meta name="DC.creator" content="Harshal Dasani">
<meta name="DC.date" content="{date_iso}">
<meta name="DC.description" content="{meta_description}">
<meta name="DC.language" content="en-IN">
<meta name="DC.publisher" content="Harshal Dasani">
<meta name="DC.subject" content="{topic_label}">
<meta name="DC.identifier" content="{canonical}">
<meta name="DC.rights" content="(c) Harshal Dasani — long-form analysis, not investment advice">

<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="en-IN" href="{canonical}">
<link rel="alternate" hreflang="x-default" href="{canonical}">
<link rel="alternate" type="application/rss+xml" title="Harshal Dasani — Blog feed" href="../../feed.xml">

<meta property="og:type" content="article">
<meta property="og:site_name" content="Harshal Dasani">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{meta_description}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{light_cover_url}">
<meta property="og:image:secure_url" content="{light_cover_url}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1600">
<meta property="og:image:height" content="900">
<meta property="og:image:alt" content="{image_alt}">
<meta property="og:locale" content="en_IN">
<meta property="article:published_time" content="{date_iso}">
<meta property="article:modified_time" content="{modified_iso}">
<meta property="article:author" content="Harshal Dasani">
<meta property="article:section" content="{topic_label}">
{article_tag_meta}

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
html,body{{margin:0;padding:0;background:var(--bg);color:var(--ink-2);transition:background-color .3s,color .3s;overflow-x:hidden}}
body{{font-family:'Inter',sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased;font-size:16.5px}}
/* No CSS zoom — page renders at native 100% browser zoom. */
a{{color:var(--accent);text-decoration:none}}
a:hover{{text-decoration:underline}}
.theme-toggle{{position:fixed;top:18px;right:18px;width:42px;height:42px;border-radius:50%;border:1px solid var(--rule);background:var(--bg-2);color:var(--ink);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:18px;z-index:1000}}
.page{{width:100%;max-width:1280px;margin:0 auto;padding:56px 24px 96px}}
.crumb{{display:flex;justify-content:space-between;align-items:center;gap:16px;font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);margin-bottom:24px}}
.crumb a{{color:var(--muted)}}
.crumb a:hover{{color:var(--accent)}}
.crumb-back{{white-space:nowrap}}
.crumb-trail{{text-align:right}}
@media(max-width:520px){{.crumb{{flex-direction:column;align-items:flex-start;gap:8px}}.crumb-trail{{text-align:left}}}}
.topic-pill{{display:inline-block;padding:5px 12px;border:1px solid var(--rule);border-radius:999px;font-size:11px;font-weight:600;letter-spacing:1.2px;text-transform:uppercase;color:var(--accent);margin-bottom:18px;background:var(--bg-2)}}
h1{{font-family:'Inter',sans-serif;font-weight:800;font-size:clamp(30px,4.6vw,46px);line-height:1.12;letter-spacing:0;color:var(--ink);margin:0 0 14px;overflow-wrap:anywhere}}
.subtitle{{font-size:18.5px;color:var(--ink-2);line-height:1.5;margin:0 0 22px;font-weight:400}}
.byline{{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted);margin:0 0 30px;flex-wrap:wrap}}
.byline strong{{color:var(--ink);font-weight:600}}
/* Cover sits IN LINE with the article column — same width as the body text (no break-out). */
.cover{{position:relative;display:block;margin:0 auto 14px;border-radius:8px;overflow:hidden;border:1px solid var(--rule);background:var(--bg-2);
       width:100%;max-width:1040px;
       aspect-ratio:16/9;cursor:zoom-in;text-decoration:none}}
.cover img{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;background:var(--bg-2)}}
/* Default theme = dark → show dark cover only. Light theme → show light cover only.
   Pure data-theme driven; we DO NOT use prefers-color-scheme (which can disagree with the user's manual theme choice). */
.cover .light-only{{opacity:1}}
.cover .dark-only{{opacity:0}}
html[data-theme="light"] .cover .light-only{{opacity:0}}
html[data-theme="light"] .cover .dark-only{{opacity:1}}
@media (max-width: 800px){{.cover{{margin-left:0;transform:none;width:100%}}}}
figcaption{{font-size:13px;color:var(--muted);font-style:italic;text-align:center;margin:0 0 32px}}
p, figcaption, .subtitle{{overflow-wrap:break-word}}
@media (max-width: 600px){{
  .page{{padding:48px 20px 84px}}
  h1{{font-size:clamp(30px,8.5vw,36px);line-height:1.1}}
  .subtitle{{font-size:17px;line-height:1.48}}
  .page figcaption{{text-align:left;line-height:1.45}}
}}
h2{{font-weight:700;font-size:24px;color:var(--ink);margin:38px 0 12px;letter-spacing:-0.01em;padding-bottom:6px;border-bottom:1px solid var(--rule)}}
h3{{font-weight:700;font-size:18px;color:var(--accent);margin:26px 0 8px}}
p{{margin:0 0 18px}}
.inline-figure{{margin:24px 0}}
.inline-figure img{{width:100%;height:auto;border-radius:6px;border:1px solid var(--rule)}}
/* Tables — editorial design, theme-aware, horizontal scroll on narrow viewports.
   Lifted card with rounded corners + subtle shadow; navy header band; gold section dividers;
   tabular-nums right-aligned data columns; hairline row separators only (no full grid). */
.table-wrap{{
  margin:32px 0;
  overflow-x:auto;
  border-radius:12px;
  background:var(--bg-2);
  box-shadow:0 1px 0 var(--rule), 0 6px 22px -8px rgba(0,0,0,0.18);
  border:1px solid var(--rule);
}}
html[data-theme="light"] .table-wrap{{box-shadow:0 1px 0 var(--rule), 0 8px 24px -10px rgba(26,52,88,0.10)}}
.post-table{{
  width:100%;
  border-collapse:collapse;
  font-size:14.5px;
  color:var(--ink-2);
}}
/* HEADER BAND — high contrast, all caps, locked colour for both themes */
.post-table thead th{{
  text-align:left;
  padding:14px 18px;
  background:var(--ink);
  color:var(--bg);
  font-weight:700;
  font-size:11.5px;
  letter-spacing:0.9px;
  text-transform:uppercase;
  border-bottom:none;
  white-space:nowrap;
}}
.post-table thead th:not(:first-child){{text-align:right}}
.post-table thead th:first-child{{border-top-left-radius:11px}}
.post-table thead th:last-child{{border-top-right-radius:11px}}

/* DATA ROWS */
.post-table tbody td{{
  padding:12px 18px;
  border-bottom:1px solid var(--rule);
  vertical-align:middle;
  line-height:1.5;
}}
.post-table tbody tr:last-child td{{border-bottom:none}}
.post-table tbody tr:last-child td:first-child{{border-bottom-left-radius:11px}}
.post-table tbody tr:last-child td:last-child{{border-bottom-right-radius:11px}}
/* Zebra striping */
.post-table tbody tr:nth-child(even):not(.tbl-section):not(.tbl-total) td{{
  background:linear-gradient(0deg, rgba(255,255,255,0.015), rgba(255,255,255,0.015)), var(--bg-2);
}}
html[data-theme="light"] .post-table tbody tr:nth-child(even):not(.tbl-section):not(.tbl-total) td{{
  background:linear-gradient(0deg, rgba(26,52,88,0.025), rgba(26,52,88,0.025)), var(--bg-2);
}}
/* Subtle hover */
.post-table tbody tr:hover td{{background:rgba(212,166,74,0.08);transition:background-color 0.15s ease}}
html[data-theme="light"] .post-table tbody tr:hover td{{background:rgba(184,133,43,0.08)}}
/* First column = entity / row label — bolded primary ink */
.post-table tbody td:first-child{{font-weight:600;color:var(--ink);letter-spacing:-0.005em}}
/* Other columns = numbers — right-aligned, tabular-nums, comfortable spacing */
.post-table tbody td:not(:first-child){{
  font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum";
  text-align:right;
  color:var(--ink);
  font-weight:500;
}}

/* SECTION DIVIDER ROWS — "kicker" treatment, gold rule + uppercase label */
.post-table tr.tbl-section td{{
  background:var(--bg);
  color:var(--accent);
  font-weight:700;
  font-size:11px;
  letter-spacing:1.2px;
  text-transform:uppercase;
  padding:11px 18px 10px;
  border-bottom:1px solid var(--rule);
  border-top:2px solid var(--accent);
  text-align:left;
}}
.post-table tr.tbl-section + tr td{{padding-top:14px}}
.post-table tr.tbl-total td{{background:rgba(212,166,74,0.10);border-top:2px solid var(--accent);border-bottom:none;font-weight:700;color:var(--ink);padding:14px 18px}}
html[data-theme="light"] .post-table tr.tbl-total td{{background:rgba(184,133,43,0.12)}}
.post-table tr.tbl-total td:not(:first-child){{color:var(--accent)}}

/* Mobile: tighten padding so the table doesn't blow up horizontal scroll on tiny screens */
@media (max-width: 600px){{
  .post-table thead th, .post-table tbody td{{padding:10px 12px;font-size:13.5px}}
  .post-table tr.tbl-section td{{padding:9px 12px;font-size:10.5px;letter-spacing:1px}}
}}
blockquote{{margin:26px 0;padding:6px 0 6px 22px;border-left:3px solid var(--accent);font-style:italic;color:var(--ink);font-size:18px}}
strong{{color:var(--ink);font-weight:700}}
.next{{margin-top:54px;padding-top:24px;border-top:1px solid var(--rule);display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}
.next a{{font-size:13px}}
.footer-meta{{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.6}}
.reading-time{{font-variant-numeric:tabular-nums}}
/* Share strip below the article */
.share{{margin-top:48px;padding-top:22px;border-top:1px solid var(--rule);display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--muted)}}
.share-label{{font-size:11px;letter-spacing:1.4px;text-transform:uppercase;color:var(--muted);margin-right:6px}}
.share a{{display:inline-flex;align-items:center;gap:6px;padding:7px 12px;border:1px solid var(--rule);border-radius:999px;color:var(--ink-2);background:var(--bg-2);text-decoration:none;font-size:12px;font-weight:600}}
.share a:hover{{color:var(--accent);border-color:var(--accent);text-decoration:none}}
.share svg{{width:14px;height:14px;flex-shrink:0}}
/* Author bio block — strong E-E-A-T signal */
.author-bio{{margin-top:40px;padding:22px 24px;background:var(--bg-2);border:1px solid var(--rule);border-radius:10px;display:flex;gap:18px;align-items:flex-start}}
.author-bio img{{width:72px;height:72px;border-radius:50%;object-fit:cover;flex-shrink:0;border:1px solid var(--rule)}}
.author-bio-body{{flex:1;min-width:0}}
.author-bio h3{{color:var(--ink);font-size:16px;font-weight:700;margin:0 0 4px}}
.author-bio p{{font-size:13.5px;color:var(--ink-2);margin:0 0 10px;line-height:1.55}}
.author-bio .author-links{{display:flex;gap:14px;font-size:12px}}
.author-bio .author-links a{{color:var(--accent);font-weight:600}}
@media (max-width: 600px){{
  .author-bio{{flex-direction:column;align-items:flex-start}}
  .author-bio img{{width:56px;height:56px}}
}}
.key-takeaways{{margin:6px 0 30px;padding:18px 22px;background:var(--bg-2);border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:8px}}
.key-takeaways .kt-label{{font-size:11px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;color:var(--accent);margin-bottom:10px}}
.key-takeaways ul{{margin:0;padding-left:18px}}
.key-takeaways li{{margin:0 0 8px;color:var(--ink-2);font-size:15px;line-height:1.55}}
.post-faq{{margin:46px 0 8px}}
.post-faq>h2{{margin-bottom:2px}}
.faq-q{{border-top:1px solid var(--rule);padding:16px 0}}
.faq-q h3{{font-size:16px;font-weight:700;color:var(--ink);margin:0 0 7px}}
.faq-q p{{margin:0;font-size:15px;line-height:1.6;color:var(--ink-2)}}
@media print{{.theme-toggle,.share{{display:none}}}}
</style>
</head>
<body>
<button class="theme-toggle" aria-label="Toggle theme" onclick="(function(){{var c=document.documentElement.getAttribute('data-theme')||'dark';var n=c==='light'?'dark':'light';document.documentElement.setAttribute('data-theme',n);try{{localStorage.setItem('hd-theme',n)}}catch(e){{}}}})()">☼</button>
<main class="page" itemscope itemtype="https://schema.org/BlogPosting">
  <nav class="crumb" aria-label="Breadcrumb"><a class="crumb-back" href="../../">&larr; Back to Blogs</a><span class="crumb-trail"><a href="../../../">Harshal Dasani</a> &middot; <a href="../../">Blogs</a> &middot; <span>{topic_label}</span></span></nav>
  <span class="topic-pill">{topic_label}</span>
  <h1 itemprop="headline">{title_html}</h1>
  <p class="subtitle" itemprop="description">{excerpt_html}</p>
  <p class="byline">By <strong itemprop="author">Harshal Dasani</strong> &middot; <span>Business Head, INVasset PMS</span> &middot; <time itemprop="datePublished" datetime="{date_iso}">{date_pretty}</time> &middot; <span class="reading-time" aria-label="Reading time">{reading_minutes} min read &middot; {word_count_pretty} words</span></p>
  <figure class="cover" role="button" tabindex="0" aria-label="Open cover in full resolution" data-light="{light_cover_filename}" data-dark="{dark_cover_filename}">
    <img src="{light_cover_filename}" alt="{image_alt}" width="1600" height="900" loading="eager" fetchpriority="high" itemprop="image" class="light-only">
    <img src="{dark_cover_filename}" alt="{image_alt}" width="1600" height="900" loading="eager" fetchpriority="high" class="dark-only">
  </figure>
  <figcaption>{image_caption_html}</figcaption>
  <article itemprop="articleBody">
{body_html}
  </article>
{faq_html}{related_html}  <div class="share" role="group" aria-label="Share this article">
    <span class="share-label">Share</span>
    <a href="https://twitter.com/intent/tweet?url={canonical_enc}&amp;text={share_title_enc}&amp;via=HarshalDasanii" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.244 2H21l-6.5 7.43L22 22h-6.797l-4.86-6.34L4.6 22H2l7.04-8.04L1.86 2h6.97l4.32 5.71L18.244 2zm-2.39 18h1.604L7.243 4H5.55l10.305 16z"/></svg>
      X / Twitter
    </a>
    <a href="https://www.linkedin.com/sharing/share-offsite/?url={canonical_enc}" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14zM8.339 18.337V9.81H5.6v8.527h2.739zM6.969 8.605c.945 0 1.532-.6 1.532-1.351-.018-.768-.587-1.35-1.514-1.35-.928 0-1.532.582-1.532 1.35 0 .751.587 1.351 1.496 1.351h.018zm11.391 9.732v-4.892c0-2.526-1.351-3.7-3.151-3.7-1.453 0-2.103.793-2.467 1.351V9.81H10.003c.036.757 0 8.527 0 8.527h2.739v-4.762c0-.243.018-.485.09-.659.196-.485.643-.987 1.395-.987.984 0 1.378.75 1.378 1.85v4.558h2.755z"/></svg>
      LinkedIn
    </a>
    <a href="https://www.youtube.com/@marketswitharshal" target="_blank" rel="noopener noreferrer">
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
      YouTube
    </a>
  </div>
  <aside class="author-bio" itemscope itemtype="https://schema.org/Person">
    <img src="../../../harshal-dasani.jpg" alt="Harshal Dasani — Business Head, INVasset PMS" loading="lazy" itemprop="image" width="72" height="72">
    <div class="author-bio-body">
      <h3 itemprop="name">About Harshal Dasani</h3>
      <p itemprop="description">Over a decade in Indian equity markets — equity research, portfolio strategy, capital flows. Currently Business Head at <a href="https://invasset.com/" rel="external" target="_blank" itemprop="worksFor">INVasset PMS</a>, Mumbai. CFA candidate · CA Level II. Long-form notes on equities, commodities, macros and geopolitics. <a href="../../../tracker/">See media features &rarr;</a></p>
      <div class="author-links">
        <a href="https://www.linkedin.com/in/harshal-dasani-/" target="_blank" rel="noopener noreferrer" itemprop="sameAs">LinkedIn</a>
        <a href="https://x.com/HarshalDasanii" target="_blank" rel="noopener noreferrer" itemprop="sameAs">X (Twitter)</a>
        <a href="https://www.youtube.com/@marketswitharshal" target="_blank" rel="noopener noreferrer" itemprop="sameAs">YouTube</a>
        <a href="../../">All posts</a>
      </div>
    </div>
  </aside>
  <div class="next">
    <a href="../../">&larr; All blogs by Harshal Dasani</a>
    <a href="../../../tracker/">Media Features Tracker &rarr;</a>
  </div>
  <p class="footer-meta">Published {date_pretty} &middot; Updated {modified_pretty} &middot; <a href="../../../">harshald13u.github.io/harshalfeatures</a></p>
</main>
<script>
// Cover swap is CSS-only (opacity keyed on [data-theme]). pageshow keeps bfcache returns in sync.
// Click/Enter on the cover opens the ACTIVE-theme image at full resolution in a new tab.
(function(){{
  function refresh(){{
    document.documentElement.style.setProperty('--cover-tick', Date.now());
  }}
  refresh();
  window.addEventListener('pageshow', refresh);

  var cover = document.querySelector('.cover');
  if (!cover) return;
  function activeCoverSrc(){{
    var t = document.documentElement.getAttribute('data-theme') || 'dark';
    return cover.getAttribute(t === 'light' ? 'data-dark' : 'data-light');
  }}
  function openFull(){{
    var src = activeCoverSrc();
    if (src) window.open(src, '_blank', 'noopener');
  }}
  cover.addEventListener('click', openFull);
  cover.addEventListener('keydown', function(e){{
    if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); openFull(); }}
  }});
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
    return f"{dt.day} {dt.strftime('%B %Y')}"


def word_count_of(text):
    return len(re.findall(r"\b[\w'’‘-]+\b", text or ""))


def reading_minutes(words, wpm=220):
    """Estimate reading time in whole minutes (rounded up, minimum 1)."""
    if not words:
        return 1
    import math
    return max(1, math.ceil(words / wpm))


def url_enc(s):
    import urllib.parse
    return urllib.parse.quote(s or "", safe="")


def render_related_html(current_slug):
    """Auto 'Related analysis' cross-links (topic cluster) from the 2 most recent OTHER posts."""
    if not os.path.exists(POSTS_JSON):
        return ""
    try:
        with open(POSTS_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    labels = {"stock-market": "Stock Market", "commodities": "Commodities", "macros": "Macros", "geopolitics": "Geopolitics"}
    posts = [p for p in data.get("posts", []) if p.get("slug") and p.get("slug") != current_slug]
    posts = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)[:2]
    if not posts:
        return ""
    links = ""
    for p in posts:
        topic = labels.get(p.get("topic", ""), (p.get("topic", "") or "Blog").replace("-", " ").title())
        links += ('    <a href="../' + html_escape(p.get("slug", "")) + '/" style="display:block;border-top:1px solid var(--rule);padding:14px 2px;text-decoration:none">'
                  '<span style="display:block;font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--accent);margin-bottom:5px">' + html_escape(topic) + '</span>'
                  '<span style="display:block;font-size:16px;font-weight:700;color:var(--ink);line-height:1.32">' + html_escape(p.get("title", "")) + '</span></a>\n')
    return ('  <section class="post-related" aria-label="Related analysis" style="margin:44px 0 8px">\n'
            '    <h2>Related analysis</h2>\n' + links + '  </section>\n')


def build_rss_feed(feed_path, site_base):
    """Generate /blog/feed.xml — RSS 2.0 — from posts.json."""
    if not os.path.exists(POSTS_JSON):
        return
    with open(POSTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    posts = sorted(data.get("posts", []), key=lambda p: p.get("date",""), reverse=True)[:30]
    now_rfc822 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for p in posts:
        try:
            dt = datetime.strptime(p["date"], "%Y-%m-%d")
            pub = dt.strftime("%a, %d %b %Y 09:00:00 +0530")
        except Exception:
            pub = now_rfc822
        title = (p.get("title") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        excerpt = (p.get("excerpt") or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        url = p.get("url") or ""
        image = p.get("image") or ""
        image_l = image.lower()
        image_type = "image/jpeg" if image_l.endswith((".jpg", ".jpeg")) else ("image/webp" if image_l.endswith(".webp") else "image/png")
        items.append(f"""    <item>
      <title>{title}</title>
      <link>{url}</link>
      <guid isPermaLink="true">{url}</guid>
      <pubDate>{pub}</pubDate>
      <description><![CDATA[{excerpt}]]></description>
      <category>{(p.get('topic') or '').replace('-', ' ').title()}</category>
      <enclosure url="{image}" type="{image_type}"/>
      <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Harshal Dasani</dc:creator>
    </item>""")

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Harshal Dasani — Blog</title>
    <link>{site_base}/blog/</link>
    <atom:link href="{site_base}/blog/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Long-form notes on Indian equity markets, commodities, macros and geopolitics by Harshal Dasani — over a decade in Indian markets, currently Business Head at INVasset PMS, Mumbai.</description>
    <language>en-IN</language>
    <copyright>(c) Harshal Dasani</copyright>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
    <generator>publish_blog.py v2</generator>
    <managingEditor>noreply@harshald13u.github.io (Harshal Dasani)</managingEditor>
    <webMaster>noreply@harshald13u.github.io (Harshal Dasani)</webMaster>
    <ttl>60</ttl>
    <image>
      <url>{site_base}/harshal-dasani.jpg</url>
      <title>Harshal Dasani</title>
      <link>{site_base}/blog/</link>
    </image>
{chr(10).join(items)}
  </channel>
</rss>
"""
    rss = normalize_dashes(rss)
    os.makedirs(os.path.dirname(feed_path), exist_ok=True)
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(rss)
    print(f"[rss] wrote {feed_path}  ({len(rss)} bytes, {len(posts)} items)")


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
    title = normalize_dashes(title)
    excerpt = normalize_dashes(excerpt)
    seo_title = normalize_dashes(seo_title)
    meta_desc = normalize_dashes(meta_desc)
    image_alt = normalize_dashes(image_alt)
    image_caption = normalize_dashes(image_caption)

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

    takeaways_items, faq_pairs, special_skip = extract_special_sections(paras)
    skip = set(skip) | special_skip
    takeaways_html = render_takeaways_html(takeaways_items)
    faq_html = render_faq_html(faq_pairs)
    related_html = render_related_html(slug)
    body_html = takeaways_html + render_body_html(
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

    # Word count and reading time (220 wpm — Medium / industry average)
    plain_body_text = " ".join(p["text"] for i, p in enumerate(paras)
                                if i not in skip and p["type"] != "image"
                                and i not in (dark_marker, light_cover_p_idx, dark_cover_p_idx, caption_idx))
    wc = word_count_of(plain_body_text)
    rt = reading_minutes(wc)

    # Mentioned entities = a second scan over the body (whole-word, case-insensitive)
    # that catches entities WITHOUT a Wikidata Q-ID, plus any aliases not used as the
    # primary link in the post. Used for the `mentions` array in JSON-LD.
    all_entities = entities  # includes those without Q-IDs
    mentioned_entities = set()
    for ent in all_entities:
        name = ent.get("name") or ""
        if not name or name in used_entities:
            continue
        # If no Q-ID we can't enrich it, so skip
        if not ent.get("wikidata"):
            continue
        cands = [name] + list(ent.get("aliases") or [])
        for cand in cands:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(cand) + r"(?![A-Za-z0-9_])",
                         plain_body_text, 0 if cand.isupper() else re.IGNORECASE):
                mentioned_entities.add(name)
                break

    jsonld = article_jsonld(
        title=title, excerpt=excerpt, slug=slug, topic=topic, date_str=date_str,
        canonical=canonical, light_cover_url=light_cover_url,
        focus_keywords=focus_kw, image_alt=image_alt,
        used_entities=used_entities, entities=entities_with_qid,
        word_count=wc, reading_minutes=rt,
        article_body_text=plain_body_text,
        mentioned_entities=mentioned_entities,
        faq_pairs=faq_pairs,
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
        canonical_enc=url_enc(canonical),
        share_title_enc=url_enc(seo_title),
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
        faq_html=faq_html,
        related_html=related_html,
        jsonld=jsonld,
        word_count_pretty=f"{wc:,}",
        reading_minutes=rt,
        article_tag_meta="\n".join(
            f'<meta property="article:tag" content="{html_escape(k.strip())}">'
            for k in (focus_kw.split(",") if focus_kw else []) if k.strip()
        ),
    )

    html = normalize_dashes(html)
    with open(os.path.join(post_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[publish] wrote {post_dir}/index.html  ({len(html)} bytes)")

    # body.md
    body_md_lines = []
    for i, p in enumerate(paras):
        if i in skip or p["type"] in ("image", "table"): continue
        if i in (dark_marker, light_cover_p_idx, dark_cover_p_idx, caption_idx): continue
        prefix = {"h1":"# ","h2":"## ","h3":"### ","p":""}.get(p["type"], "")
        body_md_lines.append(prefix + p["text"])
    with open(os.path.join(post_dir, "body.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(body_md_lines))

    # posts.json
    if os.path.exists(POSTS_JSON):
        with open(POSTS_JSON, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"posts": []}
    entry = {
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": light_cover_url, "url": canonical,
    }
    data["posts"] = [entry] + [p for p in data.get("posts", []) if p.get("slug") != slug]
    data["posts"].sort(key=lambda p: p.get("date", ""), reverse=True)
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[publish] posts.json updated ({len(data['posts'])} posts total)")

    upsert_sitemap_post(SITEMAP_PATH, canonical, today, light_cover_url, image_caption)
    upsert_news_sitemap(NEWS_SITEMAP_PATH, canonical, title, date_str)
    print(f"[publish] sitemap.xml + news-sitemap.xml updated")

    build_rss_feed(f"{BLOG_DIR}/feed.xml", SITE_BASE)
    build_rss_feed(f"{DEPLOYED}/blog/feed.xml", SITE_BASE)

    return {
        "slug": slug, "title": title, "topic": topic, "date": date_str,
        "excerpt": excerpt, "image": light_cover_url, "url": canonical,
        "post_dir": post_dir,
        "light_cover": light_cover_filename, "dark_cover": dark_cover_filename,
        "word_count": wc, "reading_minutes": rt,
        "used_entities": sorted(used_entities),
        "mentioned_entities": sorted(mentioned_entities),
        "tables": sum(1 for p in paras if p.get("type") == "table"),
    }


def find_latest_blog():
    blogs_dir = f"{FEATURES}/Blogs"
    candidates = []
    for fn in os.listdir(blogs_dir):
        if fn.startswith("~$") or fn.startswith("."): continue
        if not fn.lower().endswith(".docx"): continue
        path = os.path.join(blogs_dir, fn)
        if not os.path.isfile(path): continue
        m = re.match(r"(\d{4}-\d{2}-\d{2})_", fn)
        key = (m.group(1) if m else "0000-00-00", os.path.getmtime(path))
        candidates.append((key, path))
    if not candidates:
        raise SystemExit("No .docx blogs in /Features/Blogs/")
    candidates.sort(reverse=True)
    return candidates[0][1]


if __name__ == "__main__":
    target = sys.ar
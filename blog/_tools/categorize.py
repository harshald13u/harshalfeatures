"""Topic classifier for Harshal Dasani's blog posts.

Takes blog title + body text, returns ranked confidence scores for the 4 topics:
Stock Market, Commodities, Macros, Geopolitics.

Usage from bash:
    python3 categorize.py "Your blog title" "Body text here..."

Or programmatically:
    from categorize import classify
    result = classify(title, body)
    # -> {"stock-market": 0.45, "commodities": 0.08, "macros": 0.32, "geopolitics": 0.15,
    #     "best": "stock-market", "confidence": 0.45, "rationale": "matched 12 stock-market keywords..."}
"""

import re
import sys
import json

# Weighted keyword sets. Higher weight = stronger signal.
KEYWORDS = {
    "stock-market": [
        # Indices & exchanges
        ("nifty", 3), ("sensex", 3), ("nse", 2), ("bse", 2),
        # Equity terms
        ("equity", 2), ("equities", 2), ("stock", 1), ("stocks", 1),
        ("share", 1), ("shares", 1), ("listing", 2),
        # Capital action
        ("ipo", 3), ("fpo", 2), ("ofs", 2), ("buyback", 2), ("bonus issue", 3),
        ("rights issue", 2), ("dividend", 1), ("demerger", 2), ("merger", 1),
        # Sectors
        ("banking", 2), ("it stocks", 3), ("infosys", 2), ("tcs", 2), ("hdfc", 2),
        ("reliance", 2), ("adani", 2), ("vedanta", 2), ("defence stock", 2),
        ("pharma", 1), ("metals", 1), ("fmcg", 1), ("auto", 1),
        # Market structure
        ("fii", 3), ("dii", 3), ("foreign portfolio", 2), ("sector rotation", 3),
        ("valuation", 2), ("multibagger", 2), ("q1 result", 2), ("q2 result", 2),
        ("q3 result", 2), ("q4 result", 2), ("earnings", 2), ("smallcap", 2),
        ("midcap", 2), ("largecap", 2), ("bull market", 2), ("bear market", 2),
    ],
    "commodities": [
        ("gold", 3), ("silver", 3), ("platinum", 3), ("palladium", 2),
        ("bullion", 3), ("precious metal", 3),
        ("copper", 3), ("aluminium", 2), ("zinc", 2), ("nickel", 2), ("lead", 1),
        ("base metal", 3), ("base metals", 3),
        ("crude", 3), ("crude oil", 3), ("brent", 2), ("wti", 2), ("opec", 2),
        ("natural gas", 2),
        ("mcx", 3), ("comex", 3), ("lme", 2),
        ("commodity", 2), ("commodities", 2), ("metal etf", 2), ("gold etf", 3),
        ("silver etf", 3), ("supply chain", 2), ("supply cycle", 3),
        ("hindustan zinc", 2), ("hindustan copper", 2), ("vedanta aluminium", 2),
    ],
    "macros": [
        ("rbi", 3), ("federal reserve", 3), ("fed", 2), ("ecb", 2), ("boj", 2),
        ("central bank", 3), ("monetary policy", 3), ("repo rate", 3),
        ("rate cut", 3), ("rate hike", 3), ("inflation", 3), ("deflation", 2),
        ("cpi", 3), ("wpi", 3), ("gdp", 3), ("fiscal deficit", 2),
        ("fiscal policy", 2), ("monetary", 2), ("yield curve", 3),
        ("bond yield", 3), ("10-year yield", 3), ("us treasury", 2),
        ("dxy", 3), ("dollar index", 3), ("rupee", 3), ("currency", 2),
        ("forex", 2), ("us dollar", 2), ("trade deficit", 2), ("capital flow", 2),
        ("budget", 2), ("union budget", 3), ("recession", 2), ("liquidity", 2),
        ("quantitative easing", 2), ("qe", 1),
    ],
    "geopolitics": [
        ("geopolitics", 3), ("geopolitical", 3),
        ("us-china", 3), ("china tension", 2), ("taiwan", 2),
        ("russia", 2), ("ukraine", 2), ("nato", 2),
        ("middle east", 3), ("israel", 3), ("iran", 3), ("gaza", 2),
        ("hamas", 2), ("hezbollah", 2), ("strait of hormuz", 3),
        ("gulf", 2), ("opec+", 2), ("saudi", 1),
        ("tariff", 3), ("trade war", 3), ("trade deal", 2), ("sanction", 3),
        ("sanctions", 3), ("embargo", 2),
        ("supply route", 2), ("trade route", 2), ("export ban", 2),
        ("trump", 1), ("biden", 1), ("modi visit", 1),
        ("conflict", 1), ("war", 1), ("ceasefire", 2),
        ("g7", 2), ("g20", 2), ("brics", 2), ("opec meeting", 2),
    ],
}


def _tokenize(text):
    return re.sub(r"[^a-z0-9\s\-+]", " ", text.lower())


def classify(title, body):
    full = _tokenize((title or "") + " " + (title or "") + " " + (body or ""))
    # Title counted twice for extra weight
    raw_scores = {}
    matches = {}
    for topic, kw_list in KEYWORDS.items():
        score = 0
        topic_matches = []
        for kw, w in kw_list:
            n = full.count(kw)
            if n:
                score += n * w
                topic_matches.append(f"{kw}×{n}")
        raw_scores[topic] = score
        matches[topic] = topic_matches

    total = sum(raw_scores.values()) or 1
    pct = {t: round(s / total, 3) for t, s in raw_scores.items()}
    best = max(pct, key=pct.get)
    sorted_topics = sorted(pct.items(), key=lambda x: -x[1])

    return {
        "scores_raw": raw_scores,
        "scores_pct": pct,
        "ranked": sorted_topics,
        "best": best,
        "confidence": pct[best],
        "matches_per_topic": {t: matches[t] for t in raw_scores},
        "rationale": f"Top topic: {best} ({pct[best]*100:.0f}% of weighted keyword hits). "
                     f"2nd: {sorted_topics[1][0]} ({sorted_topics[1][1]*100:.0f}%). "
                     f"Strongest matches: {', '.join(matches[best][:6]) or 'none'}",
    }


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else ""
    body = sys.argv[2] if len(sys.argv) > 2 else ""
    if not title and not body:
        body = sys.stdin.read()
    out = classify(title, body)
    print(json.dumps(out, indent=2))

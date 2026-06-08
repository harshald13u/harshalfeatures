#!/usr/bin/env python3
"""Auto-submit blog URLs to the Google Indexing API on publish.
Run by GitHub Actions on every push that touches blog posts/sitemaps.
Reads the service-account JSON from env GOOGLE_INDEXING_KEY (a GitHub secret).
Safe no-op if the key is absent."""
import os, json, sys

SITE = "https://harshaldasani.pages.dev"

def post_urls():
    urls = [SITE + "/blog/"]
    pj = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "posts.json")
    try:
        data = json.load(open(pj, encoding="utf-8"))
        for p in data.get("posts", []):
            slug = p.get("slug")
            if slug:
                urls.append(f"{SITE}/blog/posts/{slug}/")
    except Exception as e:
        print("posts.json read failed:", e)
    return urls

def main():
    key = os.environ.get("GOOGLE_INDEXING_KEY")
    if not key:
        print("GOOGLE_INDEXING_KEY not set - skipping Google indexing (no-op).")
        return
    from google.oauth2 import service_account
    import google.auth.transport.requests
    import requests
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key), scopes=["https://www.googleapis.com/auth/indexing"])
    creds.refresh(google.auth.transport.requests.Request())
    headers = {"Authorization": "Bearer " + creds.token, "Content-Type": "application/json"}
    for u in post_urls():
        try:
            r = requests.post("https://indexing.googleapis.com/v3/urlNotifications:publish",
                              headers=headers, json={"url": u, "type": "URL_UPDATED"}, timeout=20)
            print(u, "->", r.status_code, r.text[:140])
        except Exception as e:
            print(u, "-> error", e)

if __name__ == "__main__":
    main()

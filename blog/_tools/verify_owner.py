#!/usr/bin/env python3
"""One-time: make the service account a VERIFIED OWNER of the Search Console
property via the Site Verification API (works around the GSC 'Add user -> Owner'
"email not found" bug for github.io service accounts).
Run by the Verify-SA-Owner GitHub Action. Uses GOOGLE_INDEXING_KEY (GitHub secret)."""
import os, sys, json

SITE = "https://harshald13u.github.io/harshalfeatures/"
SCOPES = ["https://www.googleapis.com/auth/siteverification"]

def _creds():
    from google.oauth2 import service_account
    import google.auth.transport.requests
    c = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_INDEXING_KEY"]), scopes=SCOPES)
    c.refresh(google.auth.transport.requests.Request())
    return c

def gettoken():
    import requests
    r = requests.post("https://www.googleapis.com/siteVerification/v1/token",
        headers={"Authorization": "Bearer " + _creds().token, "Content-Type": "application/json"},
        json={"verificationMethod": "FILE", "site": {"type": "SITE", "identifier": SITE}}, timeout=30)
    print("getToken:", r.status_code, r.text[:300])
    r.raise_for_status()
    tok = r.json()["token"]
    # Host the token file at the site root (= repo root -> /<tok>)
    with open(tok, "w") as f:
        f.write("google-site-verification: " + tok + "\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write("token_file=" + tok + "\n")
    print("Wrote token file:", tok)

def verify():
    import requests
    r = requests.post("https://www.googleapis.com/siteVerification/v1/webResource?verificationMethod=FILE",
        headers={"Authorization": "Bearer " + _creds().token, "Content-Type": "application/json"},
        json={"site": {"type": "SITE", "identifier": SITE}}, timeout=30)
    print("verify:", r.status_code, r.text[:400])
    r.raise_for_status()
    print("SERVICE ACCOUNT IS NOW A VERIFIED OWNER.")

if __name__ == "__main__":
    {"gettoken": gettoken, "verify": verify}[sys.argv[1]]()

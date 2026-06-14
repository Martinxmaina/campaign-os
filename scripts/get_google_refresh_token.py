#!/usr/bin/env python3
"""One-time script to get a Google OAuth2 refresh token for Sheets access.

Run this ONCE locally:
    python scripts/get_google_refresh_token.py

It opens a browser, you approve access, then it prints the three values
you paste into Railway as env vars.

Requirements (local only — not needed in production):
    pip install google-auth-oauthlib
"""
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Run: pip install google-auth-oauthlib")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    # Joseph spine (TB.0) — calendar + inbox feeds. Adding these requires a
    # one-time re-consent; until that refresh token is minted the feeds no-op.
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

print("""
=============================================================
 Campaign OS — Google Sheets OAuth2 Setup
=============================================================

Before running this you need:
  1. A Google Cloud project with the Sheets API enabled
  2. An OAuth2 client (type: Desktop App)
     → console.cloud.google.com → APIs & Services → Credentials
     → Create Credentials → OAuth client ID → Desktop app
     → Download JSON

Enter your OAuth2 client details below.
""")

client_id = input("Client ID (ends with .apps.googleusercontent.com): ").strip()
client_secret = input("Client Secret: ").strip()

if not client_id or not client_secret:
    print("Both values are required.")
    sys.exit(1)

client_config = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

print("\nOpening browser for Google sign-in...")
print("Sign in with the account that has access to the content intake sheet.\n")

creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

print("""
=============================================================
 SUCCESS — Add these 3 vars to Railway:
=============================================================
""")
print(f"GOOGLE_SHEETS_CLIENT_ID={client_id}")
print(f"GOOGLE_SHEETS_CLIENT_SECRET={client_secret}")
print(f"GOOGLE_SHEETS_REFRESH_TOKEN={creds.refresh_token}")
print("""
Also set:
  CONTENT_INTAKE_SHEET_ID=1cHFwSI-W2B_sXMewVVUhPQJ16ZtFONGJl2OQux7UqJE
  CONTENT_INTAKE_SHEET_RANGE=Sheet1!A:P   ← change tab name if needed
=============================================================
""")

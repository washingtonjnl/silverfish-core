"""One-off helper to obtain a Google Drive refresh token for Silverfish.

This is NOT part of the core or the API — it is a developer/operator utility for
single-tenant setups. It runs the OAuth consent flow in your browser once and
prints a refresh token to paste into ``.env.local`` as
``SILVERFISH_GDRIVE_REFRESH_TOKEN``. (In a multi-tenant SaaS, the product runs
this flow per user instead; the core never does the consent flow.)

Prerequisites:
  * The 'gdrive' extra installed:  uv sync --extra gdrive
  * A Google Cloud project with the Drive API enabled and an OAuth client of
    type "Desktop app"; pass its client id/secret below (env or prompt).

Usage:
  SILVERFISH_GDRIVE_CLIENT_ID=... SILVERFISH_GDRIVE_CLIENT_SECRET=... \
    python scripts/gdrive_authorize.py
"""

import os
import sys

# Full Drive scope: create folders, upload, share. Narrow later if desired.
_SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> int:
    client_id = os.environ.get("SILVERFISH_GDRIVE_CLIENT_ID") or input("OAuth client id: ").strip()
    client_secret = (
        os.environ.get("SILVERFISH_GDRIVE_CLIENT_SECRET") or input("OAuth client secret: ").strip()
    )
    if not client_id or not client_secret:
        print("client id and secret are required", file=sys.stderr)
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Install the gdrive extra first:  uv sync --extra gdrive",
            file=sys.stderr,
        )
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
    # Opens a browser, runs a local redirect server, completes consent.
    credentials = flow.run_local_server(port=0)

    if not credentials.refresh_token:
        print(
            "No refresh token returned. Revoke prior access for this app at "
            "https://myaccount.google.com/permissions and try again.",
            file=sys.stderr,
        )
        return 1

    print("\nAdd this to .env.local:\n")
    print(f"SILVERFISH_GDRIVE_REFRESH_TOKEN={credentials.refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

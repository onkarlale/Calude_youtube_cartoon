"""Run ONCE on your own computer to get a YouTube refresh token.
1. Put your downloaded OAuth file next to this script as client_secret.json
2. pip install google-auth-oauthlib
3. python get_refresh_token.py  (log in with the YouTube channel's Google account)
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", scopes=["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open("client_secret.json"))
c = info.get("installed") or info.get("web")
print("\nAdd these as GitHub Actions secrets:\n")
print("YT_CLIENT_ID     =", c["client_id"])
print("YT_CLIENT_SECRET =", c["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)

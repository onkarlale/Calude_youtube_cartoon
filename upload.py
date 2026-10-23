import config
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def _service():
    creds = Credentials(
        None,
        refresh_token=config.YT_REFRESH_TOKEN,
        client_id=config.YT_CLIENT_ID,
        client_secret=config.YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)

def upload(video_path, title, description, tags, thumb_path=None):
    yt = _service()
    if config.FORMAT == "short":
        title = (title[:88] + " #Shorts")
        description += "\n\n#Shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:15],
            "categoryId": config.CATEGORY_ID,
        },
        "status": {
            "privacyStatus": config.PRIVACY,
            "selfDeclaredMadeForKids": config.MADE_FOR_KIDS,
            "containsSyntheticMedia": True,  # AI-generated voice/visuals disclosure
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    actual = resp.get("status", {}).get("privacyStatus", "unknown")
    print(f"Uploaded: https://youtu.be/{vid}")
    print(f"   Requested privacy: {config.PRIVACY} | Privacy YouTube applied: {actual}")
    if actual != config.PRIVACY:
        print("   WARNING: YouTube did not apply the requested privacy. Uploads from API projects that have not "
              "passed Google's API compliance audit are locked to private. Set the video to Public in YouTube Studio, "
              "or apply for the audit.")
    if thumb_path and config.FORMAT == "long":
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb_path)).execute()
        except Exception as e:
            print(f"Thumbnail not set (channel may need phone verification): {e}")
    return vid

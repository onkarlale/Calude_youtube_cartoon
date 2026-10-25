import urllib.request
import xml.etree.ElementTree as ET
import config


def get_trends(limit=15):
    """Today's trending Google searches (free public RSS). Returns [] if anything goes wrong."""
    if not config.USE_TRENDS:
        return []
    try:
        url = f"https://trends.google.com/trending/rss?geo={config.TRENDS_GEO}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read()
        titles = [t.text.strip() for t in ET.fromstring(data).findall("./channel/item/title") if t.text]
        print("  trending topics:", ", ".join(titles[:limit]))
        return titles[:limit]
    except Exception as e:
        print("  trends unavailable:", e)
        return []

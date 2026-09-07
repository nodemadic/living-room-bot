#!/usr/bin/env python3
"""Turn Spotify CSV exports (Exportify format) into living-room notes.

For each data/*.csv: search YouTube for every track, write notes/<Playlist>.md
with one link per matched track and a "Not found" list for the rest. Nothing is
written to YouTube here; the resulting notes go into the vault and the normal
sync takes it from there.

Each search costs 100 quota units (10,000/day), so ~100 tracks a day.

Usage:  python3 match.py data/*.csv [--limit N]
Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (or .env)
"""
import csv
import os
import re
import sys
from pathlib import Path

import requests

from sync import access_token, load_env

API = "https://www.googleapis.com/youtube/v3"


def clean(s):
    s = re.sub(r"\s*[-(\[]\s*(remaster(ed)?|live|radio edit|feat\.?|ft\.?)[^)\]]*[)\]]?\s*$", "", s, flags=re.I)
    return s.strip()


def search(session, artist, title):
    q = f"{artist} {title}"
    r = session.get(
        f"{API}/search",
        params={"part": "snippet", "q": q, "type": "video", "videoCategoryId": "10",
                "maxResults": 3, "fields": "items(id/videoId,snippet(title,channelTitle))"},
        timeout=30,
    )
    if r.status_code == 403 and "quota" in r.text.lower():
        raise SystemExit("YouTube quota exhausted for today; rerun tomorrow.")
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0] if items else None


def main():
    load_env()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {access_token()}"
    Path("notes").mkdir(exist_ok=True)
    used = 0

    for f in args:
        rows = list(csv.DictReader(open(f, encoding="utf-8")))
        if limit:
            rows = rows[:limit]
        name = Path(f).stem.replace("_", " ")
        found, missing = [], []
        for r in rows:
            artist = r["Artist Name(s)"].split(";")[0]
            title = r["Track Name"]
            hit = search(s, artist, clean(title))
            used += 100
            label = f"{artist} - {title}"
            if hit:
                vid = hit["id"]["videoId"]
                yt_title = hit["snippet"]["title"]
                found.append(f"- [{label}](https://music.youtube.com/watch?v={vid}) <!-- yt: {yt_title} -->")
                print(f"  ok  {label}  ->  {yt_title}")
            else:
                missing.append(f"- {label}")
                print(f"  --  {label}")
        body = "\n".join(found)
        if missing:
            body += "\n\n## Not found on YouTube\n\n" + "\n".join(missing)
        note = (
            "---\n"
            "type: living-room\n"
            f"title: {name}\n"
            "description: Moved from Spotify\n"
            "author: AI\n"
            "tags: [ai, living-room]\n"
            "---\n"
            f"# {name}\n\n"
            "Each link is the YouTube match for a Spotify track. The comment after a link is the YouTube "
            "title it matched, so wrong matches are easy to spot. Fix or delete lines freely.\n\n"
            + body + "\n"
        )
        Path("notes", f"{name}.md").write_text(note, encoding="utf-8")
        print(f"{name}: {len(found)} matched, {len(missing)} not found")
    print(f"quota used: ~{used}")


if __name__ == "__main__":
    main()

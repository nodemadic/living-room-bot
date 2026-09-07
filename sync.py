#!/usr/bin/env python3
"""Mirror catalog.json onto a YouTube account as playlists.

The vault is the truth. For every playlist in the catalog:
  - a playlist tagged with its slug is created if missing, retitled if the title changed
  - videos missing from it are added, videos not in the note are removed
Playlists the bot created (tagged) that no longer appear in the catalog are deleted.
Playlists the bot did not create are never touched, so you can still make your own.

Tagging: the bot writes `[lrb:<slug>]` at the end of each playlist description.

Env vars (GitHub Actions secrets, or a local .env):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Usage:  python3 sync.py [catalog.json] [--dry-run]
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

API = "https://www.googleapis.com/youtube/v3"
TAG_RE = re.compile(r"\[lrb:([a-z0-9-]+)\]")


def load_env():
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def access_token():
    keys = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    vals = {k: os.environ.get(k, "").strip() for k in keys}
    missing = [k for k, v in vals.items() if not v]
    if missing:
        sys.exit(f"missing env/secrets: {', '.join(missing)}")
    for k, v in vals.items():
        print(f"{k}: {len(v)} chars, starts {v[:4]!r}")
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": vals["YT_CLIENT_ID"],
            "client_secret": vals["YT_CLIENT_SECRET"],
            "refresh_token": vals["YT_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"token refresh failed ({r.status_code}): {r.text}")
    return r.json()["access_token"]


class YT:
    def __init__(self, token, dry_run=False):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.dry = dry_run
        self.units = 0

    def _req(self, method, path, cost, **kw):
        self.units += cost
        for attempt in range(4):
            r = self.s.request(method, f"{API}/{path}", timeout=60, **kw)
            if r.status_code in (500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json() if r.text else {}

    def paged(self, path, params):
        items = []
        params = dict(params, maxResults=50)
        while True:
            data = self._req("GET", path, 1, params=params)
            items += data.get("items", [])
            tok = data.get("nextPageToken")
            if not tok:
                return items
            params["pageToken"] = tok

    def my_playlists(self):
        return self.paged("playlists", {"part": "snippet,status", "mine": "true"})

    def playlist_items(self, pid):
        return self.paged("playlistItems", {"part": "snippet", "playlistId": pid})

    def create_playlist(self, title, description, privacy):
        if self.dry:
            return {"id": f"dry-{title}"}
        return self._req(
            "POST", "playlists", 50, params={"part": "snippet,status"},
            json={"snippet": {"title": title, "description": description},
                  "status": {"privacyStatus": privacy}},
        )

    def update_playlist(self, pid, title, description, privacy):
        if self.dry:
            return
        self._req(
            "PUT", "playlists", 50, params={"part": "snippet,status"},
            json={"id": pid, "snippet": {"title": title, "description": description},
                  "status": {"privacyStatus": privacy}},
        )

    def delete_playlist(self, pid):
        if not self.dry:
            self._req("DELETE", "playlists", 50, params={"id": pid})

    def add_video(self, pid, vid):
        if self.dry:
            return
        self._req(
            "POST", "playlistItems", 50, params={"part": "snippet"},
            json={"snippet": {"playlistId": pid,
                              "resourceId": {"kind": "youtube#video", "videoId": vid}}},
        )

    def remove_item(self, item_id):
        if not self.dry:
            self._req("DELETE", "playlistItems", 50, params={"id": item_id})


def tagged_desc(desc, slug):
    desc = TAG_RE.sub("", desc or "").rstrip()
    return (desc + "\n\n" if desc else "") + f"[lrb:{slug}]"


def main():
    load_env()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    catalog = json.loads(Path(args[0] if args else "catalog.json").read_text(encoding="utf-8"))
    yt = YT(access_token(), dry_run=dry)

    existing = {}
    for pl in yt.my_playlists():
        m = TAG_RE.search(pl["snippet"].get("description", ""))
        if m:
            existing[m.group(1)] = pl

    wanted = {p["slug"]: p for p in catalog["playlists"]}
    log = []

    for slug, p in wanted.items():
        title = p["title"][:150]
        desc = tagged_desc(p.get("description", ""), slug)[:5000]
        privacy = p.get("privacy") or "unlisted"
        pl = existing.get(slug)
        if pl is None:
            pl = yt.create_playlist(title, desc, privacy)
            log.append(f"+ playlist '{title}'")
            current = []
        else:
            sn = pl["snippet"]
            if sn["title"] != title or sn.get("description", "") != desc or pl["status"]["privacyStatus"] != privacy:
                yt.update_playlist(pl["id"], title, desc, privacy)
                log.append(f"~ playlist '{title}' (details updated)")
            current = yt.playlist_items(pl["id"])
        pid = pl["id"]

        have = {}
        for it in current:
            vid = it["snippet"]["resourceId"].get("videoId")
            if vid:
                have.setdefault(vid, it["id"])
        want = p["videos"]
        for vid in want:
            if vid not in have:
                yt.add_video(pid, vid)
                log.append(f"  + {vid} -> '{title}'")
        for vid, item_id in have.items():
            if vid not in want:
                yt.remove_item(item_id)
                log.append(f"  - {vid} from '{title}'")
        # duplicates inside YouTube (same video twice) are also trimmed
        seen = set()
        for it in current:
            vid = it["snippet"]["resourceId"].get("videoId")
            if vid in want and vid in seen:
                yt.remove_item(it["id"])
                log.append(f"  - duplicate {vid} from '{title}'")
            seen.add(vid)

    for slug, pl in existing.items():
        if slug not in wanted:
            yt.delete_playlist(pl["id"])
            log.append(f"- playlist '{pl['snippet']['title']}' (note removed)")

    print("\n".join(log) if log else "nothing to change")
    print(f"\n{'DRY RUN, ' if dry else ''}quota used: ~{yt.units} units")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scan an Obsidian vault for notes with `type: living-room` and write catalog.json.

One note = one playlist. Playlist title comes from `title:` in frontmatter, else the
note's filename. Optional `description:` in frontmatter. Every YouTube link in the
body becomes a playlist item, in the order it appears. Everything else in the note
is ignored, so the note can hold whatever else you want.

Usage:  python3 build_catalog.py /path/to/vault [-o catalog.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".obsidian", ".trash", "_to_delete", "node_modules", ".git"}

YT_ID = r"([A-Za-z0-9_-]{11})"
YT_PATTERNS = [
    re.compile(r"(?:youtube\.com|youtube-nocookie\.com)/watch\?(?:[^\s\"'<>)]*&)?v=" + YT_ID),
    re.compile(r"youtu\.be/" + YT_ID),
    re.compile(r"youtube\.com/(?:shorts|embed|live|v)/" + YT_ID),
]


def parse_frontmatter(text):
    """Tiny YAML-ish frontmatter reader: only flat `key: value` lines. Good enough here."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    body = text[end + 4:]
    fm = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            fm[m.group(1)] = v
    return fm, body


def video_ids(body):
    seen, out = set(), []
    # find every URL-ish token, in document order
    for m in re.finditer(r"https?://[^\s\"'<>)\]]+", body):
        url = m.group(0)
        for pat in YT_PATTERNS:
            mm = pat.search(url)
            if mm:
                vid = mm.group(1)
                if vid not in seen:
                    seen.add(vid)
                    out.append(vid)
                break
    return out


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "untitled"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vault")
    ap.add_argument("-o", "--out", default="catalog.json")
    args = ap.parse_args()

    root = Path(args.vault)
    playlists = []
    for p in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"skip {p}: {e}", file=sys.stderr)
            continue
        fm, body = parse_frontmatter(text)
        if fm.get("type", "").strip().lower() != "living-room":
            continue
        title = fm.get("title") or p.stem
        ids = video_ids(body)
        playlists.append(
            {
                "slug": slugify(fm.get("slug") or p.stem),
                "title": title,
                "description": fm.get("description", ""),
                "privacy": fm.get("privacy", "unlisted"),
                "source": str(p.relative_to(root)),
                "videos": ids,
            }
        )
        print(f"{p.relative_to(root)}: {len(ids)} videos -> '{title}'")

    catalog = {"version": 1, "playlists": playlists}
    Path(args.out).write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(playlists)} playlists, {sum(len(x['videos']) for x in playlists)} videos")


if __name__ == "__main__":
    main()

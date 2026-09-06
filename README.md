# living-room-bot

Mirrors "living room" notes from an Obsidian vault onto a YouTube account as playlists,
so the account can be signed into any TV and just show the good stuff.

## How it works

1. Any note in the vault with `type: living-room` in its frontmatter is a playlist.
   Title = `title:` or the filename. Optional `description:` and `privacy:` (public / unlisted / private, default unlisted).
   Every YouTube link in the body is an item, in order. Everything else in the note is ignored.
2. `build_catalog.py <vault>` turns those notes into `catalog.json`.
3. Pushing `catalog.json` to `main` runs the GitHub Action, which runs `sync.py` against YouTube.
   The vault is the truth: added links get added, removed links get removed, removed notes delete the playlist.
   Playlists the bot didn't create are never touched.

## One-time setup

- Google Cloud project with YouTube Data API v3 enabled and an OAuth "Desktop app" client. Download its JSON.
- `python3 auth.py client_secret.json` on your own machine, signed in as the bot account. It prints three values.
- Add them as repository secrets: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.

## Run by hand

    python3 build_catalog.py ~/Brain -o catalog.json
    python3 sync.py catalog.json --dry-run   # show what would change
    python3 sync.py catalog.json

Quota: YouTube gives 10,000 units a day; adding or removing one video costs 50. First big import may need two days.

`docs/` is the tiny site at bot.mirrordev.net that Google's OAuth consent screen requires.

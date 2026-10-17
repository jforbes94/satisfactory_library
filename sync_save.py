#!/usr/bin/env python
"""Connector: pull the newest Satisfactory save into this repo, then run the report.

It looks in your game save folder, finds the most recent .sav for a session,
copies it here, and (by default) builds factory_graph.html from it.

    python sync_save.py                          # newest save in SAVE_DIR -> report
    python sync_save.py --session "My Session"   # only saves whose name starts with this
    python sync_save.py --source "D:\\path\\SaveGames"   # a different folder
    python sync_save.py --no-run                 # just copy, don't build the report
    python sync_save.py --list                   # show what sessions/saves are there

Everything is parametrized. Configure your own machine with env vars (or flags):
    SATISFACTORY_SAVE_DIR      your game SaveGames folder (default: %LOCALAPPDATA%/FactoryGame/Saved)
    SATISFACTORY_SAVE_SESSION  a save-name prefix to match (default: "" = any .sav)
"""
import argparse
import glob
import os
import shutil
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

# Defaults resolve per-machine from the environment -- no personal paths baked in.
# %LOCALAPPDATA% is the standard Windows location of the FactoryGame saves; override
# with --source or SATISFACTORY_SAVE_DIR. The parent "Saved" folder is searched
# recursively so both SaveGames\<id> and any backup folder are covered; newest wins.
DEFAULT_SOURCE = os.environ.get(
    "SATISFACTORY_SAVE_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FactoryGame", "Saved"),
)
# Empty prefix matches every .sav. Set SATISFACTORY_SAVE_SESSION (or --session) to
# the name you save under if you want to pull only that one (not random autosaves).
DEFAULT_SESSION = os.environ.get("SATISFACTORY_SAVE_SESSION", "")


def _all_saves(source: str):
    if not os.path.isdir(source):
        sys.exit(f"Save folder not found:\n  {source}\n"
                 f"Pass the right one with --source \"<path>\".")
    return glob.glob(os.path.join(source, "**", "*.sav"), recursive=True)


def _session_of(path: str) -> str:
    """'MySave_autosave_1-08.05.26-...' -> 'MySave' (name before the first '_')."""
    base = os.path.basename(path)
    # session is everything up to '_autosave' or the first date-like chunk
    for marker in ("_autosave", "-"):
        if marker in base:
            base = base.split(marker, 1)[0]
    return base.replace(".sav", "").strip()


def list_saves(source: str) -> None:
    saves = _all_saves(source)
    if not saves:
        print(f"No .sav files under {source}")
        return
    by_session = defaultdict(list)
    for s in saves:
        by_session[_session_of(s)].append(s)
    print(f"Sessions in {source}:")
    for session, files in sorted(by_session.items()):
        newest = max(files, key=os.path.getmtime)
        import datetime
        when = datetime.datetime.fromtimestamp(os.path.getmtime(newest))
        print(f"  {session:20s}  {len(files):2d} saves  "
              f"newest {when:%Y-%m-%d %H:%M}  ({os.path.basename(newest)})")


def find_latest(source: str, session: str) -> str:
    matches = [s for s in _all_saves(source)
               if os.path.basename(s).lower().startswith(session.lower())]
    if not matches:
        sys.exit(f"No saves for session '{session}' under {source}. "
                 f"Try --list to see what's there.")
    return max(matches, key=os.path.getmtime)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync newest save into the repo and run the report.")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="game SaveGames folder")
    ap.add_argument("--session", default=DEFAULT_SESSION, help="session name prefix to match")
    ap.add_argument("--dest", default=HERE, help="where to copy the save (default: repo root)")
    ap.add_argument("--no-run", action="store_true", help="copy only; skip building the report")
    ap.add_argument("--list", action="store_true", help="list sessions/saves and exit")
    a = ap.parse_args()

    if a.list:
        list_saves(a.source)
        return

    latest = find_latest(a.source, a.session)
    dest = os.path.join(a.dest, os.path.basename(latest))
    if os.path.abspath(latest) != os.path.abspath(dest):
        shutil.copy2(latest, dest)  # copy2 preserves the save's timestamp
    size_kb = os.path.getsize(dest) / 1024
    print(f"Synced newest '{a.session}' save ({size_kb:.0f} KB)")
    print(f"  from {latest}")
    print(f"  ->   {dest}\n")

    if not a.no_run:
        import factory_report
        factory_report.run(dest)


if __name__ == "__main__":
    main()

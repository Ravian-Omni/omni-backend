#!/bin/sh
# Archive a local DAXAGENT's data for the hosted app (src/seed.py): a consistent copy of the database
# (SQLite's backup, safe while the app runs), the task and chat folders, and the path they came from.
# Usage: scripts/seed_archive.sh [data dir, default ~/.daxagent] [output, default ./seed.tar.gz]
set -e
SRC="${1:-$HOME/.daxagent}"
OUT="${2:-$PWD/seed.tar.gz}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
sqlite3 "$SRC/daxagent.db" ".backup '$STAGE/daxagent.db'"
for d in "$SRC"/*; do
  case "$(basename "$d")" in daxagent.db*|before-seed-*|seed.tar.gz) ;; *) cp -R "$d" "$STAGE/" ;; esac
done
printf '%s' "$SRC" > "$STAGE/seed-root.txt"
tar -czf "$OUT" -C "$STAGE" .
echo "$OUT ($(du -h "$OUT" | cut -f1))"

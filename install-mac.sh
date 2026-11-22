#!/bin/bash
# Install or update a Fusion add-in from github.com/nvdberg/fusion-addins (Mac).
#
#   Easiest: open Terminal and paste
#     curl -fsSL https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-mac.sh | bash
#   (for RotaryUnwrap:  ... | bash -s RotaryUnwrap)
#   Or double-click "Install on Mac.command" in the unzipped download.
#
# It copies the add-in into Fusion's own add-in folder, where Fusion finds it and starts it by itself.
# An update keeps your own files (drawer presets, last settings). Nothing else is changed.
set -euo pipefail

REPO="nvdberg/fusion-addins"
ADDINS="${FUSION_ADDINS_DIR:-$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns}"
KEEP=('*_presets.json' '*_last.json' 'update_seen.json')    # the user's own files, kept on update

HERE=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
NAME="${1:-}"
if [[ -z "$NAME" && -n "$HERE" ]]; then              # double-clicked next to an unzipped add-in folder
    for m in "$HERE"/*/*.manifest; do
        [[ -f "$m" ]] || continue
        d="$(basename "$(dirname "$m")")"
        [[ "$(basename "$m" .manifest)" == "$d" ]] && { NAME="$d"; break; }
    done
fi
NAME="${NAME:-NMJoinery}"
[[ "$NAME" =~ ^[A-Za-z]+$ ]] || { echo "Unknown add-in name: $NAME"; exit 1; }

echo "== Installing $NAME into Fusion"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP:?}"' EXIT

SRC=""
[[ -n "$HERE" && -f "$HERE/$NAME/$NAME.manifest" ]] && SRC="$HERE/$NAME"
if [[ -z "$SRC" ]]; then
    echo "   looking for the newest release on GitHub ..."
    url="$(curl -fsSL "https://api.github.com/repos/$REPO/releases?per_page=50" |
           grep -o "\"browser_download_url\": *\"[^\"]*/$NAME-[0-9.]*\.zip\"" | head -1 |
           sed 's/.*"\(https[^"]*\)"$/\1/')"
    [[ -n "$url" ]] || { echo "No $NAME release found on github.com/$REPO"; exit 1; }
    echo "   downloading $(basename "$url")"
    curl -fsSL -o "$TMP/addin.zip" "$url"
    mkdir "$TMP/x"
    ditto -x -k "$TMP/addin.zip" "$TMP/x"
    SRC="$TMP/x/$NAME"
fi
[[ -f "$SRC/$NAME.manifest" ]] || { echo "No $NAME folder with $NAME.manifest found"; exit 1; }

# put the new version together first, with the user's own files from the old one
ditto "$SRC" "$TMP/new"
DEST="$ADDINS/$NAME"
kept=0
if [[ -d "$DEST" ]]; then
    shopt -s nullglob
    for k in "${KEEP[@]}"; do
        for f in "$DEST"/$k; do [[ -e "$f" ]] || continue; cp -p "$f" "$TMP/new/"; kept=$((kept + 1)); done
    done
    shopt -u nullglob
fi
find "$TMP/new" \( -name '__pycache__' -o -name '.DS_Store' \) -prune -exec rm -rf {} +

mkdir -p "$ADDINS"
rm -rf "${ADDINS:?}/${NAME:?}"
ditto "$TMP/new" "$DEST"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

ver="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$DEST/$NAME.manifest")"
echo "== Done: $NAME $ver is in Fusion's add-in folder"
[[ $kept -gt 0 ]] && echo "   kept $kept of your own file(s) (presets / last settings)"
if pgrep -qf "Autodesk Fusion" 2>/dev/null; then
    echo "   Fusion is open: quit and restart it to load this version."
else
    echo "   Start Fusion: $NAME starts by itself."
fi
echo "   (Check: Utilities > Add-ins > Scripts and Add-Ins: $NAME with Run on and Run on Startup ticked.)"

#!/usr/bin/env bash
# Aktualizacja gry na serwerze dedykowanym (KAN-183). Uruchamia ją co 5 min timer systemd
# (warofsteam-aktualizacja.timer) jako użytkownik warofsteam.
# Pobiera wersja.json z publicznego repo gry (to samo, z którego korzysta launcher); gdy jest nowy commit:
# paczka .pck (sprawdzana sha256), w razie potrzeby Godot w wersji z wersja.json, przestawia dowiązania
# aktualna.pck / godot i NA KOŃCU podmienia gra/wersja.json – serwer widzi nową wersję i po bitwie (albo od
# razu, gdy jest pusty) kończy pracę, a systemd uruchamia go z nową paczką.
set -euo pipefail
BASE="${WOS_BASE:-https://raw.githubusercontent.com/Strabowski/war-of-steam-gra/main}"
DIR="${WOS_DIR:-/opt/warofsteam}"
GRA="$DIR/gra"
GODOT_DIR="$DIR/godot"
mkdir -p "$GRA" "$GODOT_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 3 -o "$TMP/wersja.json" "$BASE/wersja.json"
field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$TMP/wersja.json" "$1"; }
COMMIT="$(field commit)"; PCK="$(field pck)"; SHA="$(field sha256)"; GVER="$(field godot)"
[[ "$PCK" =~ ^[A-Za-z0-9._-]+\.pck$ ]] || { echo "Dziwna nazwa paczki: $PCK"; exit 1; }
[[ "$GVER" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "Dziwna wersja Godota: $GVER"; exit 1; }

if [ -f "$GRA/wersja.json" ] && cmp -s "$TMP/wersja.json" "$GRA/wersja.json" && [ -s "$GRA/$PCK" ]; then
	exit 0          # bez zmian
fi
echo "Nowa wersja gry: $COMMIT (Godot $GVER)"

# Godot (Linux, ten sam numer wersji co przy eksporcie paczki) – ~150 MB, tylko gdy się zmienił
GBIN="$GODOT_DIR/godot-$GVER"
if [ ! -x "$GBIN" ]; then
	TAG="$GVER"; [[ "$TAG" =~ \.0$ ]] && TAG="${TAG%.0}"        # 4.7.0 → wydanie „4.7-stable”
	curl -fsSL --retry 3 -o "$TMP/godot.zip" \
		"https://github.com/godotengine/godot/releases/download/${TAG}-stable/Godot_v${TAG}-stable_linux.x86_64.zip"
	python3 -c 'import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$TMP/godot.zip" "$TMP/g"
	install -m 755 "$TMP/g/Godot_v${TAG}-stable_linux.x86_64" "$GBIN.tmp" && mv "$GBIN.tmp" "$GBIN"
	echo "Pobrany Godot $GVER"
fi

if [ ! -s "$GRA/$PCK" ]; then
	curl -fsSL --retry 3 -o "$TMP/$PCK" "$BASE/$PCK"
	GOT="$(sha256sum "$TMP/$PCK" | cut -d' ' -f1)"
	[ "$GOT" = "$SHA" ] || { echo "Zła suma kontrolna paczki ($GOT ≠ $SHA) – pomijam"; exit 1; }
	mv "$TMP/$PCK" "$GRA/$PCK"
fi

ln -sfn "$GBIN" "$GODOT_DIR/godot.tmp" && mv -T "$GODOT_DIR/godot.tmp" "$GODOT_DIR/godot"
ln -sfn "$GRA/$PCK" "$GRA/aktualna.pck.tmp" && mv -T "$GRA/aktualna.pck.tmp" "$GRA/aktualna.pck"
cp "$TMP/wersja.json" "$GRA/wersja.json.tmp" && mv "$GRA/wersja.json.tmp" "$GRA/wersja.json"
echo "Gotowe: $PCK"

# porządki: 3 najnowsze paczki i 2 najnowsze Godoty
ls -1t "$GRA"/WarOfSteam-*.pck 2>/dev/null | tail -n +4 | xargs -r rm -f
ls -1t "$GODOT_DIR"/godot-* 2>/dev/null | tail -n +3 | xargs -r rm -f

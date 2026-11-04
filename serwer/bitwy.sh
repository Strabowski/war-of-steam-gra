#!/usr/bin/env bash
# Ile bitew 10v10 ma działać naraz na tym serwerze (KAN-206). Jako root:  warofsteam-bitwy N   (1–4)
#   bitwa 1 – usługa warofsteam, port z /etc/warofsteam/serwer.cfg (zwykle 7777)
#   bitwa N – usługa warofsteam@N, /etc/warofsteam/serwer-N.cfg, port = port bitwy 1 + N − 1
# Konfigurację kolejnej bitwy tworzy z serwer.cfg (raz – potem można ją zmieniać ręcznie). Konta są wspólne,
# statystyki w jednym katalogu (raport pokazuje wszystkie bitwy).   warofsteam-bitwy  (bez liczby) – stan.
set -euo pipefail
MAX=4
CFG=/etc/warofsteam/serwer.cfg
[ "$(id -u)" = 0 ] || { echo "Uruchom jako root (sudo)."; exit 1; }
[ -f "$CFG" ] || { echo "Brak $CFG – najpierw instalacja serwera."; exit 1; }
BASE_PORT="$(sed -n 's/^port=\([0-9]*\).*/\1/p' "$CFG" | head -1)"; BASE_PORT="${BASE_PORT:-7777}"

status() {
	printf "%-7s %-6s %-10s %s\n" "Bitwa" "Port" "Stan" "Usługa"
	printf "%-7s %-6s %-10s %s\n" 1 "$BASE_PORT" "$(systemctl is-active warofsteam || true)" warofsteam
	for i in $(seq 2 $MAX); do
		[ -f "/etc/warofsteam/serwer-$i.cfg" ] || systemctl is-enabled --quiet "warofsteam@$i" 2>/dev/null || continue
		port="$(sed -n 's/^port=\([0-9]*\).*/\1/p' "/etc/warofsteam/serwer-$i.cfg" 2>/dev/null | head -1)"
		printf "%-7s %-6s %-10s %s\n" "$i" "${port:-?}" "$(systemctl is-active "warofsteam@$i" || true)" "warofsteam@$i"
	done
}

if [ $# -eq 0 ]; then status; exit 0; fi
N="$1"
[[ "$N" =~ ^[1-9]$ ]] && [ "$N" -le $MAX ] || { echo "Podaj liczbę bitew 1–$MAX."; exit 1; }

for i in $(seq 2 $MAX); do
	C="/etc/warofsteam/serwer-$i.cfg"
	if [ "$i" -le "$N" ]; then
		if [ ! -f "$C" ]; then
			PORT=$((BASE_PORT + i - 1))
			python3 - "$CFG" "$C" "$i" "$PORT" <<'PY'
import re, sys
src, dst, n, port = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(src, encoding="utf-8").read()
text = re.sub(r"(?m)^port=.*$", "port=" + port, text, count=1)
text = re.sub(r'(?m)^nazwa="?([^"\n]*)"?$', lambda m: 'nazwa="%s – bitwa %s"' % (m.group(1), n), text, count=1)
text = re.sub(r"(?m)^numer=.*\n", "", text)
text = re.sub(r"(?m)^\[serwer\]$", "[serwer]\nnumer=" + n, text, count=1)
open(dst, "w", encoding="utf-8").write(text)
PY
			chmod 644 "$C"
			echo "Nowa konfiguracja: $C (port $PORT)"
		fi
		PORT="$(sed -n 's/^port=\([0-9]*\).*/\1/p' "$C" | head -1)"
		if command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
			ufw allow "$PORT/udp" comment "War of Steam bitwa $i" > /dev/null
		fi
		systemctl enable --now "warofsteam@$i" > /dev/null 2>&1
	else
		systemctl disable --now "warofsteam@$i" > /dev/null 2>&1 || true
	fi
done
sleep 3
status
echo
echo "Gracze wybierają bitwę portem w menu (adres serwera bez zmian). Zapora w panelu VPS / Proxmox: otwórz porty UDP z tabeli."

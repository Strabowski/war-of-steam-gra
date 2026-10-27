#!/usr/bin/env bash
# Instalacja serwera dedykowanego War of Steam na Ubuntu 24.04+ (KAN-183). Jednym poleceniem, jako root:
#   curl -fsSL https://raw.githubusercontent.com/Strabowski/war-of-steam-gra/main/serwer/instaluj.sh | sudo bash
# Można uruchomić ponownie (np. po zmianie skryptów) – konfiguracji /etc/warofsteam/serwer.cfg nie nadpisuje.
# Port inny niż 7777: WOS_PORT=7800 … | sudo -E bash
set -euo pipefail
BASE="${WOS_BASE:-https://raw.githubusercontent.com/Strabowski/war-of-steam-gra/main}"
PORT="${WOS_PORT:-7777}"
[ "$(id -u)" = 0 ] || { echo "Uruchom jako root (sudo)."; exit 1; }

echo "== Pakiety"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 > /dev/null

echo "== Użytkownik i foldery"
id warofsteam > /dev/null 2>&1 || useradd --system --home-dir /var/lib/warofsteam --create-home --shell /usr/sbin/nologin warofsteam
install -d -o warofsteam -g warofsteam /opt/warofsteam/gra /opt/warofsteam/godot /var/lib/warofsteam
install -d /etc/warofsteam

echo "== Skrypty"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for f in aktualizuj.sh konta.py warofsteam.service warofsteam-aktualizacja.service warofsteam-aktualizacja.timer serwer.cfg.przyklad; do
	curl -fsSL --retry 3 -o "$TMP/$f" "$BASE/serwer/$f"
done
install -m 755 "$TMP/aktualizuj.sh" /opt/warofsteam/aktualizuj.sh
install -m 644 "$TMP"/warofsteam*.service "$TMP/warofsteam-aktualizacja.timer" /etc/systemd/system/
if [ ! -f /etc/warofsteam/serwer.cfg ]; then
	sed "s/^port=7777/port=$PORT/" "$TMP/serwer.cfg.przyklad" > /etc/warofsteam/serwer.cfg
	echo "   nowa konfiguracja: /etc/warofsteam/serwer.cfg"
else
	echo "   konfiguracja zostaje: /etc/warofsteam/serwer.cfg (wzór: /etc/warofsteam/serwer.cfg.przyklad)"
fi
install -m 644 "$TMP/serwer.cfg.przyklad" /etc/warofsteam/serwer.cfg.przyklad
# konta graczy (KAN-183): polecenie warofsteam-konta, plik czytelny tylko dla roota i serwera
install -m 755 "$TMP/konta.py" /usr/local/bin/warofsteam-konta
[ -f /etc/warofsteam/konta.json ] || echo '{"konta": {}}' > /etc/warofsteam/konta.json
chown root:warofsteam /etc/warofsteam/konta.json; chmod 640 /etc/warofsteam/konta.json
grep -q '^\[konta\]' /etc/warofsteam/serwer.cfg || printf '\n[konta]\nplik="/etc/warofsteam/konta.json"\n' >> /etc/warofsteam/serwer.cfg
PORT="$(sed -n 's/^port=\([0-9]*\).*/\1/p' /etc/warofsteam/serwer.cfg | head -1)"; PORT="${PORT:-7777}"

echo "== Gra (pierwsze pobranie: Godot ~150 MB + paczka gry)"
sudo -u warofsteam env WOS_BASE="$BASE" /opt/warofsteam/aktualizuj.sh

echo "== Zapora"
if command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
	ufw allow "$PORT/udp" comment "War of Steam" > /dev/null
	echo "   ufw: otwarty port $PORT/udp"
else
	echo "   ufw wyłączony – port $PORT/udp otwórz też w panelu dostawcy VPS, jeśli ma własną zaporę"
fi

echo "== Usługi"
systemctl daemon-reload
systemctl enable --now warofsteam-aktualizacja.timer > /dev/null
systemctl enable warofsteam > /dev/null
systemctl restart warofsteam
sleep 5
systemctl --no-pager --lines=8 status warofsteam || true

IP="$(curl -fsS -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | cut -d' ' -f1)"
cat <<TXT

Gotowe. Serwer gry działa na $IP, port $PORT (UDP).
  Konta graczy:   sudo warofsteam-konta dodaj NICK   (wypisuje hasło; lista: sudo warofsteam-konta lista)
  Gracze: menu → nick i hasło z konta, adres $IP, port $PORT → „Dołącz do gry”.
  Dziennik:       journalctl -u warofsteam -f
  Konfiguracja:   sudo nano /etc/warofsteam/serwer.cfg  →  sudo systemctl restart warofsteam
  Aktualizacja:   sama co 5 min (po scaleniu do main i publikacji gry); od razu: sudo systemctl start warofsteam-aktualizacja
TXT

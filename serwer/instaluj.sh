#!/usr/bin/env bash
# Instalacja serwera dedykowanego War of Steam na Ubuntu 24.04+ (KAN-183). Jednym poleceniem, jako root:
#   curl -fsSL https://raw.githubusercontent.com/Strabowski/war-of-steam-gra/main/serwer/instaluj.sh | sudo bash
# Można uruchomić ponownie (np. po zmianie skryptów) – konfiguracji /etc/warofsteam/serwer.cfg nie nadpisuje.
# Port inny niż 7777: WOS_PORT=7800 … | sudo -E bash
# Panel www (KAN-209) pod domeną WOS_DOMENA (domyślnie wos.spoolmatic.com; rekord A i porty TCP 80/443 na tę maszynę).
set -euo pipefail
BASE="${WOS_BASE:-https://raw.githubusercontent.com/Strabowski/war-of-steam-gra/main}"
PORT="${WOS_PORT:-7777}"
DOMENA="${WOS_DOMENA:-wos.spoolmatic.com}"
[ "$(id -u)" = 0 ] || { echo "Uruchom jako root (sudo)."; exit 1; }
# Godot 4 wymaga procesora z SSE4.2 – maszyna wirtualna z ogólnym typem procesora (np. „kvm64”) go nie ma
if ! grep -qw sse4_2 /proc/cpuinfo; then
	echo "Procesor maszyny nie ma instrukcji SSE4.2 – serwer gry się nie uruchomi."
	echo "W panelu VPS / Proxmox ustaw typ procesora na „host” (albo x86-64-v2-AES), zatrzymaj i uruchom maszynę, potem powtórz instalację."
	exit 1
fi

echo "== Pakiety"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 nginx certbot python3-certbot-nginx > /dev/null

echo "== Użytkownik i foldery"
id warofsteam > /dev/null 2>&1 || useradd --system --home-dir /var/lib/warofsteam --create-home --shell /usr/sbin/nologin warofsteam
install -d -o warofsteam -g warofsteam /opt/warofsteam/gra /opt/warofsteam/godot /var/lib/warofsteam
install -d /etc/warofsteam

echo "== Skrypty"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for f in aktualizuj.sh konta.py raport.py bitwy.sh warofsteam.service warofsteam@.service warofsteam-aktualizacja.service warofsteam-aktualizacja.timer serwer.cfg.przyklad; do
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
# statystyki testów (KAN-185): pliki zdarzeń serwera i polecenie raportu
install -m 755 "$TMP/raport.py" /usr/local/bin/warofsteam-raport
# kilka bitew naraz (KAN-206): szablon usługi warofsteam@N i polecenie warofsteam-bitwy N
install -m 644 "$TMP/warofsteam@.service" /etc/systemd/system/warofsteam@.service
install -m 755 "$TMP/bitwy.sh" /usr/local/bin/warofsteam-bitwy
install -d -o warofsteam -g warofsteam -m 750 /var/lib/warofsteam/statystyki

echo "== Panel www (konta graczy, bitwy, statystyki)"
# KAN-209: konta są w bazie panelu; panel zapisuje plik kont dla serwerów gry w /var/lib/warofsteam/konta
# (katalog z bitem setgid – plik ma grupę warofsteam, serwer gry go czyta, panel pisze).
id wospanel > /dev/null 2>&1 || useradd --system --home-dir /var/lib/warofsteam-panel --create-home --shell /usr/sbin/nologin wospanel
usermod -aG warofsteam wospanel
install -d -o wospanel -g wospanel -m 750 /var/lib/warofsteam-panel
install -d -o wospanel -g warofsteam -m 2750 /var/lib/warofsteam/konta
install -d -o wospanel -g warofsteam -m 2750 /var/lib/warofsteam/sterowanie   # KAN-211: ustawienia bitew, wyrzucenia
install -d /opt/warofsteam/panel
for f in wos_panel.py baza.py strony.py statystyki.py sterowanie.py warofsteam-panel.service warofsteam-kopia.service warofsteam-kopia.timer; do
	curl -fsSL --retry 3 -o "$TMP/$f" "$BASE/serwer/panel/$f"
done
install -m 644 "$TMP/wos_panel.py" "$TMP/baza.py" "$TMP/strony.py" "$TMP/statystyki.py" "$TMP/sterowanie.py" /opt/warofsteam/panel/
install -m 644 "$TMP/warofsteam-panel.service" "$TMP/warofsteam-kopia.service" "$TMP/warofsteam-kopia.timer" /etc/systemd/system/
install -d -o wospanel -g wospanel -m 750 /var/lib/warofsteam-panel/kopie
# RODO (KAN-212): dziennik systemu (journalctl) też ma adresy IP graczy – trzymamy go najwyżej 90 dni
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nMaxRetentionSec=90day\n' > /etc/systemd/journald.conf.d/warofsteam.conf
systemctl restart systemd-journald || true
[ -f /etc/warofsteam/panel.cfg ] || cat > /etc/warofsteam/panel.cfg <<CFG
; Panel www War of Steam (KAN-209). Po zmianie: sudo systemctl restart warofsteam-panel
[panel]
baza=/var/lib/warofsteam-panel/panel.db
konta_gry=/var/lib/warofsteam/konta/konta.json
sekret=/var/lib/warofsteam-panel/sekret
adres=127.0.0.1
port=8090
; e-mail organizatora na stronie /prywatnosc (puste – bez adresu)
kontakt=
CFG
cat > /usr/local/bin/warofsteam-panel <<'SH'
#!/bin/sh
# Panel War of Steam – polecenia awaryjne (KAN-209): wlasciciel EMAIL NICK · gracz EMAIL NICK [admin] · haslo LOGIN · lista
exec sudo -u wospanel python3 /opt/warofsteam/panel/wos_panel.py --config=/etc/warofsteam/panel.cfg "$@"
SH
chmod 755 /usr/local/bin/warofsteam-panel
cat > /usr/local/bin/warofsteam-konta <<'SH'
#!/bin/sh
echo "Konta graczy są teraz w panelu www (Gracze → Nowe konto). Awaryjnie: sudo warofsteam-panel pomoc"
SH
chmod 755 /usr/local/bin/warofsteam-konta
# stare konta (warofsteam-konta) → panel, raz; serwery gry czytają nowy plik kont
if [ -f /etc/warofsteam/konta.json ] && [ ! -f /var/lib/warofsteam-panel/panel.db ]; then
	install -o wospanel -g wospanel -m 600 /etc/warofsteam/konta.json /var/lib/warofsteam-panel/stare-konta.json
	warofsteam-panel import /var/lib/warofsteam-panel/stare-konta.json
fi
[ -f /var/lib/warofsteam/konta/konta.json ] || warofsteam-panel lista > /dev/null      # tworzy bazę …
sudo -u wospanel python3 -c "import sys; sys.path.insert(0,'/opt/warofsteam/panel'); import wos_panel; c=wos_panel.load_config('/etc/warofsteam/panel.cfg'); from baza import Db; Db(c['baza'], c['konta_gry']).export_game_accounts()"
for c in /etc/warofsteam/serwer.cfg /etc/warofsteam/serwer-*.cfg; do
	[ -f "$c" ] || continue
	if grep -q '^\[konta\]' "$c"; then
		sed -i 's#^plik=.*#plik="/var/lib/warofsteam/konta/konta.json"#' "$c"
	else
		printf '\n[konta]\nplik="/var/lib/warofsteam/konta/konta.json"\n' >> "$c"
	fi
done
# nginx → panel (127.0.0.1:8090), certyfikat Let's Encrypt
cat > /etc/nginx/sites-available/warofsteam-panel <<NG
server {
	listen 80;
	listen [::]:80;
	server_name $DOMENA;
	server_tokens off;
	client_max_body_size 64k;
	location / {
		proxy_pass http://127.0.0.1:8090;
		proxy_set_header Host \$host;
		proxy_set_header X-Real-IP \$remote_addr;
		proxy_set_header X-Forwarded-Proto \$scheme;
	}
}
NG
ln -sfn /etc/nginx/sites-available/warofsteam-panel /etc/nginx/sites-enabled/warofsteam-panel
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx
# zawsze: plik strony wyżej jest nadpisywany bez HTTPS – certbot dopisuje go z powrotem (istniejący certyfikat zostaje,
# nowy tylko przy pierwszej instalacji albo gdy wygasa)
certbot --nginx -d "$DOMENA" --non-interactive --agree-tos --register-unsafely-without-email --redirect --keep-until-expiring -q \
	|| echo "   UWAGA: brak HTTPS – sprawdź rekord A $DOMENA i port TCP 80 z internetu, potem powtórz instalację"
curl -fsS -o /dev/null --max-time 10 "https://$DOMENA/logowanie" && echo "   panel: https://$DOMENA działa" \
	|| echo "   UWAGA: https://$DOMENA nie odpowiada (sprawdź: nginx -t; journalctl -u warofsteam-panel)"
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
systemctl enable warofsteam-panel > /dev/null
systemctl restart warofsteam-panel
systemctl enable --now warofsteam-kopia.timer > /dev/null   # KAN-212: kopia co noc + porządki RODO
systemctl restart warofsteam
for unit in $(systemctl list-units --plain --no-legend 'warofsteam@*.service' | awk '{print $1}'); do
	systemctl restart "$unit"                # kolejne bitwy – też z nowymi skryptami
done
sleep 5
systemctl --no-pager --lines=8 status warofsteam || true

IP="$(curl -fsS -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | cut -d' ' -f1)"
cat <<TXT

Gotowe. Serwer gry działa na $IP, port $PORT (UDP).
  Kilka bitew:    sudo warofsteam-bitwy 4   (bitwy 1–4 na portach $PORT–$((PORT + 3)); bez liczby – stan)
  Statystyki:     sudo warofsteam-raport   (dzisiaj; --dni=7, --csv=/tmp/raport – pliki do Excela)
  Panel www:      https://$DOMENA   (bitwy, gracze, statystyki)
  Kopie panelu:   co noc w /var/lib/warofsteam-panel/kopie (14 ostatnich); od razu: sudo warofsteam-panel kopia
  Prywatność:     https://$DOMENA/prywatnosc  (kontakt: kontakt=… w /etc/warofsteam/panel.cfg)
  Właściciel:     sudo warofsteam-panel wlasciciel TWOJ@EMAIL NICK   (raz; wypisuje hasło do panelu i gry)
  Gracze: Ustawienia → Konto (e-mail i hasło), potem „Bitwa losowa”.
  Dziennik:       journalctl -u warofsteam -f
  Konfiguracja:   sudo nano /etc/warofsteam/serwer.cfg  →  sudo systemctl restart warofsteam
  Aktualizacja:   sama co 5 min (po scaleniu do main i publikacji gry); od razu: sudo systemctl start warofsteam-aktualizacja
TXT

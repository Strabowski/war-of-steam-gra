#!/usr/bin/env python3
"""Panel www War of Steam (KAN-208/209) – serwer HTTP na 127.0.0.1 za nginx (HTTPS), tylko biblioteka standardowa.

  python3 wos_panel.py --config=/etc/warofsteam/panel.cfg serwuj                     – serwer panelu (usługa systemd)
  python3 wos_panel.py --config=… wlasciciel EMAIL NICK                              – konto właściciela (raz), wypisuje hasło
  python3 wos_panel.py --config=… gracz EMAIL NICK [admin]                           – konto awaryjnie z serwera
  python3 wos_panel.py --config=… haslo EMAIL_LUB_NICK                               – awaryjny reset hasła
  python3 wos_panel.py --config=… import PLIK                                        – konta ze starego pliku gry
  python3 wos_panel.py --config=… lista
  python3 wos_panel.py --config=… kopia                                              – kopia: baza panelu, sterowanie, statystyki
  python3 wos_panel.py --config=… odtworz PLIK.tar.gz                                – baza panelu z kopii (potem restart usługi)
Na serwerze: sudo warofsteam-panel <polecenie> (to samo, z właściwą konfiguracją i użytkownikiem).

Bezpieczeństwo: sesja w ciasteczku podpisanym HMAC (HttpOnly, Secure, SameSite=Strict) z wersją konta (zmiana hasła
lub wyłączenie unieważnia sesje), token CSRF w każdym formularzu, limit nieudanych logowań z IP.
"""
import base64
import configparser
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strony  # noqa: E402
from baza import Db, PanelError  # noqa: E402
from statystyki import Stats, player_events  # noqa: E402
from sterowanie import Control, SteerError  # noqa: E402

DEFAULTS = {
    "baza": "/var/lib/warofsteam-panel/panel.db",
    "konta_gry": "/var/lib/warofsteam/konta/konta.json",
    "sekret": "/var/lib/warofsteam-panel/sekret",
    "statystyki": "/var/lib/warofsteam/statystyki",    # pliki zdarzeń i stan bitew z serwerów gry (tylko odczyt)
    "sterowanie": "/var/lib/warofsteam/sterowanie/sterowanie.json",   # ustawienia bitew i wyrzucenia (KAN-211)
    "kopie": "/var/lib/warofsteam-panel/kopie",       # codzienne kopie (KAN-212)
    "kopie_ile": "14",
    "kontakt": "",                                    # e-mail organizatora na stronie o prywatności (puste – bez adresu)
    "adres": "127.0.0.1",
    "port": "8090",
    "bezpieczne_ciasteczko": "tak",          # „nie” tylko do testów bez HTTPS
}
SESSION_HOURS = 12
COOKIE = "wos_sesja"
LOGIN_MAX_FAILURES = 8                       # nieudanych logowań z jednego IP …
LOGIN_WINDOW_S = 600                         # … w 10 min → blokada do końca okna


def load_config(path: str) -> dict:
    cfg = configparser.ConfigParser()
    if path and os.path.exists(path):
        cfg.read(path, encoding="utf-8")
    out = dict(DEFAULTS)
    if cfg.has_section("panel"):
        for k in DEFAULTS:
            if cfg.has_option("panel", k):
                out[k] = cfg.get("panel", k).strip().strip('"')
    return out


def load_secret(path: str) -> bytes:
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read().strip()
            if len(data) >= 32:
                return data
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = secrets.token_hex(32).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return data


class Panel:
    def __init__(self, config: dict):
        self.config = config
        self.db = Db(config["baza"], config["konta_gry"])
        self.stats = Stats(config["statystyki"])
        self.control = Control(config["sterowanie"], config["statystyki"])
        self.secret = load_secret(config["sekret"])
        self.secure_cookie = config["bezpieczne_ciasteczko"].lower() not in ("nie", "no", "0", "false")
        self.failures = {}
        self.lock = threading.Lock()

    # --- sesje ----------------------------------------------------------------------------------------------

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.secret, payload, hashlib.sha256).hexdigest()

    def make_session(self, user) -> str:
        data = json.dumps({"u": user["id"], "v": user["wersja_sesji"], "x": int(time.time()) + SESSION_HOURS * 3600},
                          separators=(",", ":")).encode()
        b = base64.urlsafe_b64encode(data).decode().rstrip("=")
        return b + "." + self._sign(b.encode())

    def session_user(self, cookie: str):
        if not cookie or "." not in cookie:
            return None
        b, sig = cookie.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(b.encode()), sig):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
        except (ValueError, json.JSONDecodeError):
            return None
        if data.get("x", 0) < time.time():
            return None
        user = self.db.user(int(data.get("u", 0)))
        if user is None or not user["aktywne"] or user["wersja_sesji"] != data.get("v"):
            return None
        return user

    def csrf_token(self, cookie: str) -> str:
        return self._sign(("csrf:" + cookie).encode())[:32]

    # --- limit logowań ----------------------------------------------------------------------------------------

    def blocked(self, ip: str) -> bool:
        with self.lock:
            now = time.time()
            recent = [t for t in self.failures.get(ip, []) if now - t < LOGIN_WINDOW_S]
            self.failures[ip] = recent
            return len(recent) >= LOGIN_MAX_FAILURES

    def failed(self, ip: str) -> None:
        with self.lock:
            self.failures.setdefault(ip, []).append(time.time())


class Handler(BaseHTTPRequestHandler):
    panel: Panel = None
    server_version = "WarOfSteamPanel"
    sys_version = ""

    # --- pomocnicze -------------------------------------------------------------------------------------------

    def log_message(self, fmt, *args):            # dziennik usługi: bez zapytań (hasła idą tylko POST-em)
        pass

    def client_ip(self) -> str:
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def cookie(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def send(self, code: int, body: str, headers=None) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'")
        if self.panel.secure_cookie:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str, cookie: str = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if cookie is not None:
            flags = "Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if self.panel.secure_cookie else "")
            if cookie == "":
                self.send_header("Set-Cookie", "%s=; %s; Max-Age=0" % (COOKIE, flags))
            else:
                self.send_header("Set-Cookie", "%s=%s; %s; Max-Age=%d" % (COOKIE, cookie, flags, SESSION_HOURS * 3600))
        self.end_headers()

    def form(self) -> dict:
        n = min(int(self.headers.get("Content-Length", "0") or 0), 64 * 1024)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    # --- obsługa --------------------------------------------------------------------------------------------

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method: str) -> None:
        p = self.panel
        url = urllib.parse.urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        cookie = self.cookie()
        user = p.session_user(cookie)
        csrf = p.csrf_token(cookie) if user else ""
        f = self.form() if method == "POST" else {}
        try:
            if path == "/logowanie":
                return self.login(method, f)
            if path == "/prywatnosc":
                return self.send(200, strony.privacy_page(p.config.get("kontakt", ""), user, csrf))
            if user is None:
                return self.redirect("/logowanie")
            if method == "POST" and not hmac.compare_digest(f.get("csrf", ""), csrf):
                return self.send(403, strony.error_page(403, "Formularz wygasł – odśwież stronę i spróbuj ponownie.", user, csrf))
            if path == "/wyloguj" and method == "POST":
                return self.redirect("/logowanie", cookie="")
            if path == "/":
                return self.redirect("/admin/gracze" if user["role"] in ("owner", "admin") else "/konto")
            if path == "/konto":
                return self.send(200, strony.account_page(user, csrf, progress=p.stats.player(user["nick"])))
            if path == "/konto/dane":
                return self.my_data(user)
            if path == "/konto/haslo" and method == "POST":
                return self.change_password(user, csrf, f)
            if path.startswith("/admin"):
                if user["role"] not in ("owner", "admin"):
                    return self.send(403, strony.error_page(403, "Tylko dla administratorów.", user, csrf))
                return self.admin(method, path, user, csrf, f)
            return self.send(404, strony.error_page(404, "Nie ma takiej strony.", user, csrf))
        except PanelError as err:
            return self.send(400, strony.error_page(400, str(err), user, csrf))

    def login(self, method: str, f: dict) -> None:
        p = self.panel
        if method == "GET":
            return self.send(200, strony.login_page())
        ip = self.client_ip()
        login = f.get("login", "").strip()[:200]
        if p.blocked(ip):
            return self.send(429, strony.login_page("Zbyt wiele nieudanych prób – spróbuj za 10 minut.", login))
        user = p.db.by_login(login) if login else None
        if user is None or not p.db.check_password(user, f.get("haslo", "")) or not user["aktywne"]:
            p.failed(ip)
            msg = "Konto jest wyłączone." if user is not None and user["aktywne"] == 0 and p.db.check_password(
                user, f.get("haslo", "")) else "Zły e-mail / nick albo hasło."
            return self.send(401, strony.login_page(msg, login))
        p.db.touch_login(user["id"])
        return self.redirect("/", cookie=p.make_session(user))

    def change_password(self, user, csrf: str, f: dict) -> None:
        p = self.panel
        if not p.db.check_password(user, f.get("obecne", "")):
            return self.send(400, strony.account_page(user, csrf, progress=p.stats.player(user["nick"]), error="Obecne hasło się nie zgadza."))
        if f.get("nowe", "") != f.get("powtorz", ""):
            return self.send(400, strony.account_page(user, csrf, progress=p.stats.player(user["nick"]), error="Nowe hasła się różnią."))
        try:
            p.db.set_password(user["id"], f.get("nowe", ""), user)
        except PanelError as err:
            return self.send(400, strony.account_page(user, csrf, progress=p.stats.player(user["nick"]), error=str(err)))
        fresh = p.db.user(user["id"])
        cookie = p.make_session(fresh)                       # stare sesje (inne urządzenia) wygasają
        self.send_response(HTTPStatus.OK)
        body = strony.account_page(fresh, p.csrf_token(cookie), info="Hasło zmienione.",
                                   progress=p.stats.player(fresh["nick"])).encode("utf-8")
        flags = "Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if p.secure_cookie else "")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", "%s=%s; %s; Max-Age=%d" % (COOKIE, cookie, flags, SESSION_HOURS * 3600))
        self.end_headers()
        self.wfile.write(body)

    def my_data(self, user) -> None:
        """RODO – dostęp do własnych danych: konto (bez skrótu hasła) i zdarzenia z serwerów gry."""
        account = {k: user[k] for k in ("email", "nick", "role", "utworzone", "ostatnie_logowanie")}
        data = {"konto": account, "zdarzenia_z_gry": player_events(self.panel.config["statystyki"], user["nick"]),
                "wyjasnienie": "Dane, które War of Steam ma o Tobie – zob. /prywatnosc"}
        body = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="war-of-steam-moje-dane.json"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def battles(self, user, csrf: str, info: str = "", error: str = "", code: int = 200) -> None:
        control = self.panel.control
        states = control.states()
        settings = {n: control.battle_settings(n) for n in states}
        return self.send(code, strony.battles_page(states, settings, control.maps(states), user, csrf, info, error))

    def admin(self, method: str, path: str, user, csrf: str, f: dict) -> None:
        db = self.panel.db
        parts = path.split("/")                              # ['', 'admin', 'gracze', '12', 'reset']
        if path == "/admin/gracze" and method == "GET":
            return self.send(200, strony.users_page(db, user, csrf))
        if path == "/admin/statystyki" and method == "GET":
            days = self.query.get("dni", "7")
            days = int(days) if days in ("0", "1", "7", "30") else 7
            return self.send(200, strony.stats_page(self.panel.stats.overview(days), user, csrf, show_ip=user["role"] == "owner"))
        if path == "/admin/statystyki/gracz" and method == "GET":
            nick = self.query.get("nick", "").strip()[:40]
            if not nick:
                return self.redirect("/admin/statystyki")
            target = db.by_login(nick)
            progress = self.panel.stats.player(target["nick"] if target else nick)
            return self.send(200, strony.player_stats_page(progress, target, user, csrf))
        if path == "/admin/bitwy" and method == "GET":
            return self.battles(user, csrf)
        if path == "/admin/bitwy/wyrzuc" and method == "POST":
            nick = f.get("gracz", "").strip()[:40]
            target = db.by_login(nick) if nick else None
            if not nick or (target is not None and target["id"] != user["id"] and not db.can_manage(user, target)):
                return self.battles(user, csrf, error="Nie możesz wyrzucić tego gracza.", code=403)
            battle = int(f.get("bitwa", "0")) if f.get("bitwa", "0").isdigit() else 0
            self.panel.control.add_kick(nick, battle, f.get("powod", ""))
            db.log(user["id"], "wyrzucenie", "%s z bitwy %s" % (nick, battle or "każdej"))
            return self.battles(user, csrf, info="%s zostanie odłączony w ciągu kilku sekund." % nick)
        if len(parts) == 4 and parts[2] == "bitwy" and parts[3].isdigit() and method == "POST":
            n = int(parts[3])
            try:
                saved = self.panel.control.save_battle(n, f, self.panel.control.maps())
            except SteerError as err:
                return self.battles(user, csrf, error=str(err), code=400)
            db.log(user["id"], "ustawienia bitwy", "bitwa %d: %s" % (n, json.dumps(saved, ensure_ascii=False)))
            return self.battles(user, csrf, info="Bitwa %d: zapisane – działa od następnej bitwy%s." % (
                n, "" if saved["wlaczona"] else " (wyłączenie – od razu)"))
        if path == "/admin/dziennik":
            return self.send(200, strony.log_page(db, user, csrf))
        if path == "/admin/gracze/nowy" and method == "POST":
            try:
                password = db.create_user(f.get("email", ""), f.get("nick", ""), f.get("rola", "player"), user)
            except PanelError as err:
                return self.send(400, strony.users_page(db, user, csrf, error=str(err), form=f))
            target = db.by_login(f.get("nick", "").strip())
            return self.send(200, strony.password_page(user, csrf, target, password, True))
        if len(parts) == 5 and parts[2] == "gracze" and parts[3].isdigit():
            target = db.user(int(parts[3]))
            if target is None:
                return self.send(404, strony.error_page(404, "Nie ma takiego konta.", user, csrf))
            action = parts[4]
            if action == "usun" and method == "GET":
                if not db.can_manage(user, target):
                    return self.send(403, strony.error_page(403, "Nie możesz usunąć tego konta.", user, csrf))
                return self.send(200, strony.confirm_delete_page(user, csrf, target))
            if method == "POST":
                if action == "reset":
                    password = db.reset_password(target["id"], user)
                    return self.send(200, strony.password_page(user, csrf, db.user(target["id"]), password, False))
                if action in ("wylacz", "wlacz"):
                    db.set_active(target["id"], action == "wlacz", user)
                    if action == "wylacz":
                        self.panel.control.add_kick(target["nick"], 0, "konto wyłączone")   # jeśli gra – od razu z bitwy
                    return self.send(200, strony.users_page(db, user, csrf, info="Konto %s %s." % (
                        target["nick"], "włączone" if action == "wlacz" else "wyłączone")))
                if action == "usun":
                    db.delete_user(target["id"], user)
                    return self.send(200, strony.users_page(db, user, csrf, info="Konto %s usunięte." % target["nick"]))
        return self.send(404, strony.error_page(404, "Nie ma takiej strony.", user, csrf))


def backup(config: dict) -> str:
    """Kopia do `kopie`: kopia-RRRR-MM-DD_HHMM.tar.gz (baza panelu – spójna kopia SQLite, sterowanie, statystyki).
    Zostaje `kopie_ile` najnowszych. Zwraca ścieżkę kopii."""
    out_dir = config["kopie"]
    os.makedirs(out_dir, mode=0o750, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    target = os.path.join(out_dir, "kopia-%s.tar.gz" % stamp)
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "panel.db")
        src = sqlite3.connect(config["baza"])
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        partial = target + ".tmp"
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(snap, "panel.db")
            if os.path.exists(config["sterowanie"]):
                tar.add(config["sterowanie"], "sterowanie.json")
            stats_dir = config["statystyki"]
            if os.path.isdir(stats_dir):
                for name in sorted(os.listdir(stats_dir)):
                    if name.startswith("zdarzenia-") and name.endswith(".jsonl"):
                        tar.add(os.path.join(stats_dir, name), "statystyki/" + name)
        os.chmod(partial, 0o640)
        os.replace(partial, target)
    keep = max(int(config.get("kopie_ile", "14") or 14), 1)
    old = sorted(n for n in os.listdir(out_dir) if n.startswith("kopia-") and n.endswith(".tar.gz"))
    for name in old[:-keep]:
        os.remove(os.path.join(out_dir, name))
    return target


def restore(config: dict, archive: str) -> None:
    """Baza panelu z kopii (spójnie, przez SQLite backup) i ponowny eksport kont dla gry."""
    with tarfile.open(archive, "r:gz") as tar, tempfile.TemporaryDirectory() as tmp:
        member = tar.getmember("panel.db")
        if not member.isfile():
            raise PanelError("W kopii nie ma bazy panelu.")
        with tar.extractfile(member) as f, open(os.path.join(tmp, "panel.db"), "wb") as out:
            out.write(f.read())
        src = sqlite3.connect(os.path.join(tmp, "panel.db"))
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            src.close()
            raise PanelError("Baza w kopii jest uszkodzona.")
        dst = sqlite3.connect(config["baza"])
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    Db(config["baza"], config["konta_gry"]).export_game_accounts()


def make_server(config: dict, port: int = None):
    panel = Panel(config)
    handler = type("PanelHandler", (Handler,), {"panel": panel})
    srv = ThreadingHTTPServer((config["adres"], int(port if port is not None else config["port"])), handler)
    srv.daemon_threads = True
    return srv, panel


def main(argv: list) -> int:
    cfg_path = "/etc/warofsteam/panel.cfg"
    args = []
    for a in argv:
        if a.startswith("--config="):
            cfg_path = a.split("=", 1)[1]
        else:
            args.append(a)
    if not args or args[0] in ("-h", "--help", "pomoc"):
        print(__doc__)
        return 0
    config = load_config(cfg_path)
    cmd = args[0]
    if cmd == "serwuj":
        srv, panel = make_server(config)
        panel.db.export_game_accounts()
        print("Panel War of Steam: http://%s:%s (konta gry: %s)" % (config["adres"], config["port"], config["konta_gry"]),
              flush=True)
        srv.serve_forever()
        return 0
    db = Db(config["baza"], config["konta_gry"])
    try:
        if cmd == "wlasciciel" and len(args) >= 3:
            password = db.make_owner(args[1], args[2])
            print("Właściciel: %s (%s)\nLogin: %s\nHasło: %s" % (args[2], args[1], args[1], password))
        elif cmd == "gracz" and len(args) >= 3:
            role = "admin" if len(args) > 3 and args[3] == "admin" else "player"
            password = db.create_user(args[1], args[2], role)
            print("Konto: %s (%s), rola: %s\nLogin: %s\nHasło: %s" % (args[2], args[1], role, args[1], password))
        elif cmd == "haslo" and len(args) >= 2:
            user = db.by_login(args[1])
            if user is None:
                print("Nie ma konta %s." % args[1])
                return 1
            print("Konto: %s\nNowe hasło: %s" % (user["nick"], db.reset_password(user["id"])))
        elif cmd == "import" and len(args) >= 2:
            print("Zaimportowano kont: %d" % db.import_game_accounts(args[1]))
        elif cmd == "kopia":
            print("Kopia: %s" % backup(config))
        elif cmd == "odtworz" and len(args) >= 2:
            restore(config, args[1])
            print("Baza panelu odtworzona z %s. Teraz: sudo systemctl restart warofsteam-panel" % args[1])
        elif cmd == "lista":
            for u in db.users():
                print("%-17s %-32s %-10s %s" % (u["nick"], u["email"] or "–", u["role"], "aktywne" if u["aktywne"] else "WYŁĄCZONE"))
        else:
            print(__doc__)
            return 2
    except PanelError as err:
        print(str(err))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

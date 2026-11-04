"""Baza panelu War of Steam (KAN-209): konta, role, dziennik działań; eksport kont dla serwera gry.

SQLite (jeden plik). Hasło nigdy nie jest zapisywane – tylko sól i klucz, liczone tak samo jak w grze
(core/accounts.gd → Accounts.derive_key: SHA-256 × 20000), więc ten sam klucz służy do logowania w grze i w panelu.

Role: owner (właściciel – jeden, nie da się go usunąć ani zmienić), admin (zarządza graczami i grą, nie rusza
właściciela ani innych adminów), player (swoje konto). Uprawnienia: can_manage().
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile

ITERATIONS = 20000
ROLES = ("owner", "admin", "player")
ROLE_NAMES = {"owner": "właściciel", "admin": "admin", "player": "gracz"}
NICK_RE = re.compile(r"^[A-Za-z0-9_\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{3,16}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")
# hasła bez znaków łatwych do pomylenia (l/1, O/0)
ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIN_PASSWORD = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE COLLATE NOCASE,
    nick TEXT NOT NULL UNIQUE COLLATE NOCASE,
    role TEXT NOT NULL DEFAULT 'player',
    sol TEXT NOT NULL,
    klucz TEXT NOT NULL,
    aktywne INTEGER NOT NULL DEFAULT 1,
    utworzone TEXT NOT NULL,
    utworzyl INTEGER,
    ostatnie_logowanie TEXT,
    wersja_sesji INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS dziennik (
    id INTEGER PRIMARY KEY,
    czas TEXT NOT NULL,
    kto INTEGER,
    akcja TEXT NOT NULL,
    szczegoly TEXT NOT NULL DEFAULT ''
);
"""


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def derive_key(salt: str, password: str) -> str:
    h = hashlib.sha256((salt + ":" + password).encode()).hexdigest()
    for _ in range(ITERATIONS):
        h = hashlib.sha256((h + salt).encode()).hexdigest()
    return h


def new_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(12))


class PanelError(Exception):
    """Błąd z komunikatem dla użytkownika panelu."""


class Db:
    def __init__(self, path: str, game_accounts: str = ""):
        self.path = path
        self.game_accounts = game_accounts
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    # --- odczyt ---------------------------------------------------------------------------------------------

    def user(self, user_id: int):
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def by_login(self, login: str):
        """Konto po e-mailu albo nicku (bez względu na wielkość liter)."""
        login = login.strip()
        return self.conn.execute("SELECT * FROM users WHERE email = ? OR nick = ?", (login, login)).fetchone()

    def users(self):
        return self.conn.execute(
            "SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, nick").fetchall()

    def owner(self):
        return self.conn.execute("SELECT * FROM users WHERE role = 'owner'").fetchone()

    def log_entries(self, limit: int = 200):
        return self.conn.execute(
            "SELECT d.*, u.nick AS kto_nick FROM dziennik d LEFT JOIN users u ON u.id = d.kto "
            "ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()

    # --- uprawnienia ----------------------------------------------------------------------------------------

    @staticmethod
    def can_manage(actor, target) -> bool:
        """Czy `actor` może zmieniać konto `target` (reset hasła, wyłączenie, usunięcie)."""
        if actor is None or target is None or actor["id"] == target["id"]:
            return False
        if target["role"] == "owner":
            return False                                   # właściciela nie rusza nikt
        if actor["role"] == "owner":
            return True
        return actor["role"] == "admin" and target["role"] == "player"

    @staticmethod
    def roles_for(actor):
        """Role, które `actor` może nadać nowemu kontu."""
        if actor["role"] == "owner":
            return ["player", "admin"]
        if actor["role"] == "admin":
            return ["player"]
        return []

    # --- zmiany ---------------------------------------------------------------------------------------------

    def log(self, actor_id, action: str, details: str = "") -> None:
        self.conn.execute("INSERT INTO dziennik (czas, kto, akcja, szczegoly) VALUES (?, ?, ?, ?)",
                          (now(), actor_id, action, details[:500]))

    def create_user(self, email: str, nick: str, role: str, actor=None, password: str = "") -> str:
        """Nowe konto; zwraca hasło (pokazywane raz). `actor` None – polecenie na serwerze."""
        email = (email or "").strip()
        nick = nick.strip()
        if role not in ROLES:
            raise PanelError("Nieznana rola.")
        if actor is not None and role not in self.roles_for(actor):
            raise PanelError("Nie możesz zakładać kont z tą rolą.")
        if role == "owner" and self.owner() is not None:
            raise PanelError("Właściciel już jest – może być tylko jeden.")
        if email and not EMAIL_RE.match(email):
            raise PanelError("Nieprawidłowy adres e-mail.")
        if not NICK_RE.match(nick):
            raise PanelError("Nick: 3–16 znaków – litery, cyfry, _ i -.")
        if email and self.by_login(email) is not None:
            raise PanelError("Konto z tym e-mailem już jest.")
        if self.by_login(nick) is not None or (email and self.conn.execute(
                "SELECT 1 FROM users WHERE nick = ? OR email = ?", (email, nick)).fetchone()):
            raise PanelError("Ten nick jest zajęty.")
        password = password or new_password()
        salt = secrets.token_hex(16)
        self.conn.execute(
            "INSERT INTO users (email, nick, role, sol, klucz, utworzone, utworzyl) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (email or None, nick, role, salt, derive_key(salt, password), now(), actor["id"] if actor else None))
        self.log(actor["id"] if actor else None, "nowe konto", "%s (%s), %s" % (nick, email or "bez e-maila", ROLE_NAMES[role]))
        self.export_game_accounts()
        return password

    def make_owner(self, email: str, nick: str) -> str:
        """Właściciel z istniejącego konta bez e-maila (np. zaimportowanego z gry) albo nowe konto; zwraca nowe hasło."""
        if self.owner() is not None:
            raise PanelError("Właściciel już jest – może być tylko jeden.")
        existing = self.by_login(nick)
        if existing is None:
            return self.create_user(email, nick, "owner")
        if existing["email"] and existing["email"].lower() != email.strip().lower():
            raise PanelError("Konto %s ma już inny e-mail." % existing["nick"])
        if not EMAIL_RE.match(email.strip()):
            raise PanelError("Nieprawidłowy adres e-mail.")
        if self.by_login(email) is not None and self.by_login(email)["id"] != existing["id"]:
            raise PanelError("Konto z tym e-mailem już jest.")
        self.conn.execute("UPDATE users SET email = ?, role = 'owner', aktywne = 1 WHERE id = ?", (email.strip(), existing["id"]))
        self.log(None, "właściciel", "%s (%s) – z istniejącego konta" % (existing["nick"], email.strip()))
        return self.reset_password(existing["id"])

    def check_password(self, user, password: str) -> bool:
        return hmac.compare_digest(derive_key(user["sol"], password), user["klucz"])

    def set_password(self, user_id: int, password: str, actor=None) -> None:
        target = self.user(user_id)
        if target is None:
            raise PanelError("Nie ma takiego konta.")
        if actor is not None and actor["id"] != user_id and not self.can_manage(actor, target):
            raise PanelError("Nie możesz zmieniać tego konta.")
        if len(password) < MIN_PASSWORD:
            raise PanelError("Hasło musi mieć co najmniej %d znaków." % MIN_PASSWORD)
        salt = secrets.token_hex(16)
        self.conn.execute("UPDATE users SET sol = ?, klucz = ?, wersja_sesji = wersja_sesji + 1 WHERE id = ?",
                          (salt, derive_key(salt, password), user_id))
        self.log(actor["id"] if actor else None,
                 "zmiana hasła" if actor is not None and actor["id"] == user_id else "reset hasła", target["nick"])
        self.export_game_accounts()

    def reset_password(self, user_id: int, actor=None) -> str:
        password = new_password()
        self.set_password(user_id, password, actor)
        return password

    def set_active(self, user_id: int, active: bool, actor) -> None:
        target = self.user(user_id)
        if not self.can_manage(actor, target):
            raise PanelError("Nie możesz zmieniać tego konta.")
        self.conn.execute("UPDATE users SET aktywne = ?, wersja_sesji = wersja_sesji + 1 WHERE id = ?",
                          (1 if active else 0, user_id))
        self.log(actor["id"], "włączenie konta" if active else "wyłączenie konta", target["nick"])
        self.export_game_accounts()

    def delete_user(self, user_id: int, actor) -> None:
        target = self.user(user_id)
        if not self.can_manage(actor, target):
            raise PanelError("Nie możesz usunąć tego konta.")
        self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.log(actor["id"], "usunięcie konta", "%s (%s)" % (target["nick"], target["email"] or "bez e-maila"))
        self.export_game_accounts()

    def touch_login(self, user_id: int) -> None:
        self.conn.execute("UPDATE users SET ostatnie_logowanie = ? WHERE id = ?", (now(), user_id))

    # --- plik kont gry ----------------------------------------------------------------------------------------

    def export_game_accounts(self) -> None:
        """Konta dla serwera gry (core/accounts.gd): każde pod nickiem i pod e-mailem (małymi literami), więc
        w grze można się logować jednym i drugim. Zapis atomowy – serwer czyta plik przy każdym logowaniu."""
        if not self.game_accounts:
            return
        out = {}
        for u in self.users():
            entry = {"nick": u["nick"], "sol": u["sol"], "klucz": u["klucz"], "aktywne": bool(u["aktywne"]),
                     "utworzone": u["utworzone"]}
            out[u["nick"].lower()] = entry
            if u["email"]:
                out[u["email"].lower()] = entry
        d = os.path.dirname(os.path.abspath(self.game_accounts))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".konta-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"konta": out}, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o640)
        os.replace(tmp, self.game_accounts)

    def import_game_accounts(self, path: str) -> int:
        """Konta ze starego pliku (warofsteam-konta) – bez e-maila, z tym samym hasłem (sól i klucz)."""
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        added = 0
        seen = set()
        for key, acc in data.get("konta", {}).items():
            nick = acc.get("nick", key)
            if nick.lower() in seen or self.by_login(nick) is not None or not NICK_RE.match(nick):
                continue
            seen.add(nick.lower())
            self.conn.execute(
                "INSERT INTO users (email, nick, role, sol, klucz, aktywne, utworzone) VALUES (NULL, ?, 'player', ?, ?, ?, ?)",
                (nick, acc["sol"], acc["klucz"], 1 if acc.get("aktywne", True) else 0, acc.get("utworzone", now())))
            added += 1
        if added:
            self.log(None, "import kont", "%d z %s" % (added, path))
            self.export_game_accounts()
        return added

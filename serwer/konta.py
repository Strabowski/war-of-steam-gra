#!/usr/bin/env python3
"""Konta graczy serwera War of Steam (KAN-183). Na serwerze: sudo warofsteam-konta <polecenie>

  dodaj NICK     – nowe konto; wypisuje hasło (tylko raz – przekaż je graczowi)
  haslo NICK     – nowe hasło dla konta (stare przestaje działać)
  wylacz NICK    – konto nie może się logować (dane i statystyki zostają)
  wlacz NICK     – z powrotem może
  lista          – wszystkie konta

Plik: /etc/warofsteam/konta.json (inny: --plik=ŚCIEŻKA). Serwer czyta go przy każdym logowaniu – bez restartu.
Hasło nie jest zapisywane: tylko sól i klucz – ten sam algorytm co core/accounts.gd (Accounts.derive_key).
"""
import datetime
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile

ITERATIONS = 20000
NICK_RE = re.compile(r"^[A-Za-z0-9_\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{3,16}$")
DEFAULT_FILE = "/etc/warofsteam/konta.json"
# hasła bez liter łatwych do pomylenia (l/1, O/0)
ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def derive_key(salt: str, password: str) -> str:
    h = hashlib.sha256((salt + ":" + password).encode()).hexdigest()
    for _ in range(ITERATIONS):
        h = hashlib.sha256((h + salt).encode()).hexdigest()
    return h


def new_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(10))


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {"konta": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".konta-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if os.path.exists(path):
        st = os.stat(path)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.chmod(tmp, st.st_mode & 0o777)
    else:
        os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def set_password(acc: dict, password: str) -> None:
    acc["sol"] = secrets.token_hex(16)
    acc["klucz"] = derive_key(acc["sol"], password)


def main(argv: list) -> int:
    path = DEFAULT_FILE
    args = []
    password = None
    for a in argv:
        if a.startswith("--plik="):
            path = a.split("=", 1)[1]
        elif a.startswith("--haslo="):          # tylko do testów – normalnie hasło losowe
            password = a.split("=", 1)[1]
        else:
            args.append(a)
    if not args or args[0] in ("-h", "--help", "pomoc"):
        print(__doc__)
        return 0
    cmd = args[0]
    data = load(path)
    accounts = data.setdefault("konta", {})
    if cmd == "lista":
        if not accounts:
            print("Brak kont.")
        for acc in sorted(accounts.values(), key=lambda a: a["nick"].lower()):
            print(f"{acc['nick']:<17} {'aktywne' if acc.get('aktywne', True) else 'WYŁĄCZONE':<10} od {acc.get('utworzone', '?')}")
        return 0
    if len(args) < 2:
        print("Podaj nick, np.: warofsteam-konta %s Ala" % cmd)
        return 2
    nick = args[1]
    key = nick.lower()
    if cmd == "dodaj":
        if not NICK_RE.match(nick):
            print("Nick: 3–16 znaków – litery, cyfry, _ i -.")
            return 2
        if key in accounts:
            print(f"Konto {accounts[key]['nick']} już jest (nowe hasło: warofsteam-konta haslo {nick}).")
            return 1
        password = password or new_password()
        acc = {"nick": nick, "aktywne": True,
               "utworzone": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        set_password(acc, password)
        accounts[key] = acc
        save(path, data)
        print(f"Konto: {nick}\nHasło: {password}")
        return 0
    if key not in accounts:
        print(f"Nie ma konta {nick}.")
        return 1
    acc = accounts[key]
    if cmd == "haslo":
        password = password or new_password()
        set_password(acc, password)
        save(path, data)
        print(f"Konto: {acc['nick']}\nNowe hasło: {password}")
    elif cmd in ("wylacz", "wlacz"):
        acc["aktywne"] = cmd == "wlacz"
        save(path, data)
        print(f"Konto {acc['nick']}: {'aktywne' if acc['aktywne'] else 'wyłączone'}.")
    else:
        print(f"Nieznane polecenie {cmd}.\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

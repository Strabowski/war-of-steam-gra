"""Zarządzanie bitwami z panelu (KAN-211).

Panel zapisuje plik sterowania (czyta go serwer gry – server/dedicated_server.gd, co 3 s):
  {"bitwy": {"1": {"wlaczona": true, "mapa": "losowo" | nazwa | "" (z serwer.cfg), "pora": …, "deszcz": …,
                   "druzyna": 1–10, "czas_bitwy_min": 3–30}},
   "wyrzuc": [{"id", "gracz", "bitwa": 0 (wszystkie) | N, "czas": unix, "powod"}]}
Serwer gry zapisuje stan na żywo: <statystyki>/stan-b<N>.json (gracze, faza, mapa, pora…).
Ustawienia bitwy działają od następnej bitwy; wyrzucenie i wyłączenie bitwy – od razu.
"""
import json
import os
import secrets
import tempfile
import threading
import time

BATTLES = (1, 2, 3, 4)
PORY = {"losowo": "losowo", "dzien": "dzień", "wieczor": "wieczór", "noc": "noc"}
DESZCZ = {"losowo": "losowo", "tak": "zawsze", "nie": "nigdy"}
TEAM_MIN, TEAM_MAX = 1, 10
TIME_MIN, TIME_MAX = 3, 30
STATE_FRESH_S = 30                 # stan starszy – bitwa nie działa (serwer wyłączony)
KICK_KEEP_S = 600                  # stare wyrzucenia znikają z pliku
DEFAULT_MAPS = ["Wielkie Miasto nad Rzeką"]


class SteerError(ValueError):
    pass


class Control:
    def __init__(self, path: str, state_dir: str):
        self.path = path
        self.state_dir = state_dir
        self.lock = threading.Lock()

    # ---------- plik sterowania ----------

    def read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("bitwy", {})
        data.setdefault("wyrzuc", [])
        return data

    def _write(self, data: dict) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".sterowanie-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o640)
        os.replace(tmp, self.path)

    def battle_settings(self, number: int) -> dict:
        return dict(self.read()["bitwy"].get(str(number), {}))

    def save_battle(self, number: int, form: dict, maps: list) -> dict:
        """Waliduje formularz i zapisuje ustawienia bitwy; zwraca zapisane ustawienia."""
        if number not in BATTLES:
            raise SteerError("Nie ma takiej bitwy.")
        mapa = (form.get("mapa") or "").strip()
        if mapa not in ("", "losowo") and mapa not in maps:
            raise SteerError("Nieznana mapa.")
        pora = form.get("pora", "losowo")
        deszcz = form.get("deszcz", "losowo")
        if pora not in PORY or deszcz not in DESZCZ:
            raise SteerError("Zła pora dnia albo pogoda.")
        try:
            team = int(form.get("druzyna", "10"))
            minutes = int(form.get("czas_bitwy_min", "10"))
        except ValueError:
            raise SteerError("Wielkość drużyny i czas bitwy to liczby.")
        if not TEAM_MIN <= team <= TEAM_MAX:
            raise SteerError("Drużyna: od %d do %d statków." % (TEAM_MIN, TEAM_MAX))
        if not TIME_MIN <= minutes <= TIME_MAX:
            raise SteerError("Czas bitwy: od %d do %d minut." % (TIME_MIN, TIME_MAX))
        settings = {"wlaczona": form.get("wlaczona") == "tak", "pora": pora, "deszcz": deszcz,
                    "druzyna": team, "czas_bitwy_min": minutes}
        if mapa:
            settings["mapa"] = mapa
        with self.lock:
            data = self.read()
            data["bitwy"][str(number)] = settings
            self._write(data)
        return settings

    def add_kick(self, nick: str, battle: int = 0, reason: str = "") -> None:
        now = int(time.time())
        with self.lock:
            data = self.read()
            data["wyrzuc"] = [k for k in data["wyrzuc"] if isinstance(k, dict) and now - int(k.get("czas", 0)) < KICK_KEEP_S]
            data["wyrzuc"].append({"id": secrets.token_hex(6), "gracz": nick, "bitwa": int(battle), "czas": now,
                                   "powod": reason.strip()[:200]})
            self._write(data)

    # ---------- stan bitew (z serwerów gry) ----------

    def states(self) -> dict:
        """numer → stan (z polem „dziala”: świeży plik) albo None (brak pliku)."""
        out = {}
        now = time.time()
        for n in BATTLES:
            path = os.path.join(self.state_dir, "stan-b%d.json" % n)
            try:
                with open(path, encoding="utf-8") as f:
                    st = json.load(f)
                st["dziala"] = now - os.path.getmtime(path) < STATE_FRESH_S
            except (OSError, ValueError):
                st = None
            out[n] = st if isinstance(st, dict) or st is None else None
        return out

    def maps(self, states: dict = None) -> list:
        for st in (states or self.states()).values():
            if st and isinstance(st.get("mapy"), list) and st["mapy"]:
                return [str(m) for m in st["mapy"]]
        return list(DEFAULT_MAPS)

    def online(self, states: dict = None) -> dict:
        """nick (małe litery) → numer bitwy, w której gra teraz."""
        out = {}
        for n, st in (states or self.states()).items():
            if st and st.get("dziala"):
                for nick in st.get("gracze", []):
                    out[str(nick).lower()] = n
        return out

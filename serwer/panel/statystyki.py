"""Statystyki gry w panelu (KAN-210): czyta pliki zdarzeń serwerów gry (server/stats_log.gd) – tylko do odczytu.

Pliki: <katalog>/zdarzenia-RRRR-MM-DD.jsonl (bitwa 1) i zdarzenia-RRRR-MM-DD-b<N>.jsonl (bitwy 2–4). Każda linia to
{"czas": "RRRR-MM-DD HH:MM:SS", "zd": "<rodzaj>", "serwer": N, …}. Pliki są wczytywane ponownie tylko po zmianie
(rozmiar / czas modyfikacji), więc odświeżanie strony jest tanie.
"""
import datetime
import hashlib
import glob
import json
import os
import re
import statistics
import threading

FILE_RE = re.compile(r"zdarzenia-(\d{4}-\d{2}-\d{2})(?:-b\d+)?\.jsonl$")
PORY = {"dzien": "dzień", "wieczor": "wieczór", "noc": "noc"}


def accuracy(hits, shots):
    return 100.0 * hits / shots if shots else None


def median(values):
    values = [v for v in values if isinstance(v, (int, float)) and v >= 0]
    return statistics.median(values) if values else None


def result_for(team, winner) -> str:
    if not winner:
        return "remis"
    return "wygrana" if team == winner else "przegrana"


class Stats:
    def __init__(self, directory: str):
        self.directory = directory
        self._cache = {}                     # ścieżka → (mtime, rozmiar, zdarzenia)
        self._lock = threading.Lock()

    # ---------- wczytywanie ----------

    def files(self, since: datetime.date = None) -> list:
        out = []
        for path in glob.glob(os.path.join(self.directory, "zdarzenia-*.jsonl")):
            m = FILE_RE.search(os.path.basename(path))
            if not m:
                continue
            if since is not None and datetime.date.fromisoformat(m.group(1)) < since:
                continue
            out.append(path)
        return sorted(out)

    def _read(self, path: str) -> list:
        try:
            st = os.stat(path)
        except OSError:
            return []
        hit = self._cache.get(path)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
        events = []
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue                   # niedokończona linia (serwer właśnie pisze)
                    if isinstance(ev, dict):
                        events.append(ev)
        except OSError:
            return []
        self._cache[path] = (st.st_mtime, st.st_size, events)
        return events

    def events(self, days: int = 0) -> list:
        """Zdarzenia z ostatnich `days` dni (z dzisiejszym); 0 – wszystkie."""
        since = datetime.date.today() - datetime.timedelta(days=days - 1) if days > 0 else None
        with self._lock:
            out = []
            for path in self.files(since):
                out.extend(self._read(path))
        out.sort(key=lambda e: str(e.get("czas", "")))
        return out

    # ---------- bitwy ----------

    @staticmethod
    def battles(events: list) -> list:
        """Zakończone bitwy z mapą, porą i deszczem z „bitwa_start” tego samego serwera."""
        started, out = {}, []
        for ev in events:
            kind, srv = ev.get("zd"), int(ev.get("serwer", 1) or 1)
            if kind == "bitwa_start":
                started[srv] = ev
            elif kind == "bitwa_koniec":
                st = started.get(srv)
                if st is not None and st.get("bitwa") != ev.get("bitwa"):
                    st = None
                st = st or {}
                out.append({
                    "czas": str(ev.get("czas", "")), "serwer": srv, "bitwa": ev.get("bitwa"),
                    "mapa": str(st.get("mapa", "?")), "pora": PORY.get(str(st.get("pora", "")), str(st.get("pora", "–"))),
                    "deszcz": bool(st.get("deszcz", False)), "czas_s": int(ev.get("czas_s", 0) or 0),
                    "zwyciezca": int(ev.get("zwyciezca", 0) or 0), "powod": str(ev.get("powod", "")),
                    "gracze": [g for g in ev.get("gracze", []) if isinstance(g, dict)],
                })
        return out

    # ---------- przegląd dla admina ----------

    def overview(self, days: int = 7) -> dict:
        events = self.events(days)
        players, per_day, servers = {}, {}, {}
        rejected = {"razem": 0, "powody": {}, "ip": set()}

        def pl(nick):
            return players.setdefault(nick, {
                "nick": nick, "sesje": 0, "czas_s": 0, "bitwy": 0, "wygrane": 0, "przegrane": 0, "remisy": 0,
                "zestrzelenia": 0, "obrazenia": 0, "trafienia": 0, "strzaly": 0, "przezyl": 0, "wyjscia": 0,
                "ostatnio": "", "ip": set(), "wersja": "", "fps": [], "ping": [], "karta": "", "jakosc": ""})

        def day(ev):
            return per_day.setdefault(str(ev.get("czas", ""))[:10], {
                "gracze": set(), "sesje": 0, "czas_s": 0, "bitwy": 0, "bitwy_z_graczami": 0, "odrzucone": 0})

        for ev in events:
            kind, nick = ev.get("zd"), str(ev.get("gracz", "") or "")
            when = str(ev.get("czas", ""))
            if kind == "logowanie" and nick:
                p = pl(nick)
                p["ip"].add(str(ev.get("ip", "")))
                p["wersja"] = str(ev.get("wersja", "") or p["wersja"])
                p["ostatnio"] = max(p["ostatnio"], when)
                day(ev)["gracze"].add(nick)
            elif kind == "rozlaczenie" and nick:
                p = pl(nick)
                p["sesje"] += 1
                p["czas_s"] += int(ev.get("sesja_s", 0) or 0)
                p["wyjscia"] += 1 if ev.get("w_trakcie_bitwy") else 0
                p["ostatnio"] = max(p["ostatnio"], when)
                d = day(ev)
                d["sesje"] += 1
                d["czas_s"] += int(ev.get("sesja_s", 0) or 0)
                d["gracze"].add(nick)
            elif kind == "logowanie_odrzucone":
                rejected["razem"] += 1
                reason = str(ev.get("powod", "?"))
                rejected["powody"][reason] = rejected["powody"].get(reason, 0) + 1
                rejected["ip"].add(str(ev.get("ip", "")))
                day(ev)["odrzucone"] += 1
            elif kind == "wydajnosc_gracza" and nick:
                p = pl(nick)
                p["fps"].append(ev.get("fps"))
                p["ping"].append(ev.get("ping"))
                p["karta"] = str(ev.get("karta", "") or p["karta"])
                p["jakosc"] = str(ev.get("jakosc", "") or p["jakosc"])
            elif kind == "serwer":
                s = servers.setdefault(int(ev.get("serwer", 1) or 1), {"pomiary": 0, "uspiony": 0, "cpu": [], "klatka": [],
                                                                       "graczy_maks": 0, "ram_maks": 0, "ostatni": ""})
                s["pomiary"] += 1
                s["ostatni"] = max(s["ostatni"], when)
                s["graczy_maks"] = max(s["graczy_maks"], int(ev.get("graczy", 0) or 0))
                s["ram_maks"] = max(s["ram_maks"], int(ev.get("ram_mb", 0) or 0))
                if ev.get("uspiony") or float(ev.get("fps", 0) or 0) < 1.0:
                    s["uspiony"] += 1
                else:
                    s["cpu"].append(ev.get("procesor_proc"))
                    s["klatka"].append(ev.get("klatka_ms"))

        battles = self.battles(events)
        for b in battles:
            d = per_day.setdefault(b["czas"][:10], {"gracze": set(), "sesje": 0, "czas_s": 0, "bitwy": 0,
                                                    "bitwy_z_graczami": 0, "odrzucone": 0})
            d["bitwy"] += 1
            if b["gracze"]:
                d["bitwy_z_graczami"] += 1
            for g in b["gracze"]:
                d["gracze"].add(str(g.get("gracz", "?")))
                p = pl(str(g.get("gracz", "?")))
                p["bitwy"] += 1
                r = result_for(g.get("druzyna"), b["zwyciezca"])
                p["wygrane" if r == "wygrana" else "przegrane" if r == "przegrana" else "remisy"] += 1
                p["zestrzelenia"] += int(g.get("zestrzelenia", 0) or 0)
                p["obrazenia"] += int(g.get("obrazenia", 0) or 0)
                p["trafienia"] += int(g.get("trafienia", 0) or 0)
                p["strzaly"] += int(g.get("strzaly", 0) or 0) + int(g.get("naboje", 0) or 0)
                p["przezyl"] += 1 if g.get("przezyl") else 0
                p["ostatnio"] = max(p["ostatnio"], b["czas"])

        for p in players.values():
            p["celnosc"] = accuracy(p["trafienia"], p["strzaly"])
            p["fps_med"] = median(p.pop("fps"))
            p["ping_med"] = median(p.pop("ping"))
            p["ip"] = sorted(i for i in p["ip"] if i)
        for s in servers.values():
            s["cpu_sr"] = statistics.mean([c for c in s["cpu"] if isinstance(c, (int, float)) and c >= 0] or [0]) if s["cpu"] else None
            s["cpu_maks"] = max([c for c in s["cpu"] if isinstance(c, (int, float))] or [0]) if s["cpu"] else None
            s["klatka_med"] = median(s.pop("klatka"))
            del s["cpu"]
        with_players = [b for b in battles if b["gracze"]]
        return {
            "dni": days,
            "zdarzen": len(events),
            "gracze": sorted(players.values(), key=lambda p: (-p["czas_s"], -p["bitwy"], p["nick"].lower())),
            "dni_lista": [dict(v, data=k, gracze=len(v["gracze"])) for k, v in sorted(per_day.items(), reverse=True) if k],
            "bitwy": list(reversed(with_players))[:30],
            "bitwy_razem": len(battles),
            "bitwy_z_graczami": len(with_players),
            "unikalni": len(players),
            "czas_s": sum(p["czas_s"] for p in players.values()),
            "serwery": dict(sorted(servers.items())),
            "odrzucone": dict(rejected, ip=sorted(i for i in rejected["ip"] if i)),
        }

    # ---------- postępy gracza ----------

    def player(self, nick: str) -> dict:
        """Postępy jednego gracza od początku: sumy, rekordy, tygodnie, ostatnie bitwy, wydajność."""
        key = nick.lower()
        events = self.events(0)
        rows, perf, sessions, play_s = [], [], 0, 0
        first = last = ""
        for b in self.battles(events):
            for g in b["gracze"]:
                if str(g.get("gracz", "")).lower() != key:
                    continue
                shots = int(g.get("strzaly", 0) or 0) + int(g.get("naboje", 0) or 0)
                rows.append({"czas": b["czas"], "mapa": b["mapa"], "pora": b["pora"], "deszcz": b["deszcz"],
                             "czas_s": b["czas_s"], "wynik": result_for(g.get("druzyna"), b["zwyciezca"]),
                             "zestrzelenia": int(g.get("zestrzelenia", 0) or 0), "obrazenia": int(g.get("obrazenia", 0) or 0),
                             "trafienia": int(g.get("trafienia", 0) or 0), "strzaly": shots,
                             "przezyl": bool(g.get("przezyl")), "graczy": len(b["gracze"])})
        for ev in events:
            if str(ev.get("gracz", "")).lower() != key:
                continue
            kind = ev.get("zd")
            if kind == "rozlaczenie":
                sessions += 1
                play_s += int(ev.get("sesja_s", 0) or 0)
            elif kind == "wydajnosc_gracza":
                perf.append(ev)
            if kind in ("logowanie", "rozlaczenie", "gracz_w_bitwie"):
                when = str(ev.get("czas", ""))
                first = min(first, when) if first else when
                last = max(last, when)
        for r in rows:
            first = min(first, r["czas"]) if first else r["czas"]
            last = max(last, r["czas"])
        n = len(rows)
        tot = {k: sum(r[k] for r in rows) for k in ("zestrzelenia", "obrazenia", "trafienia", "strzaly")}
        wins = sum(1 for r in rows if r["wynik"] == "wygrana")
        weeks = {}
        for r in rows:
            d = datetime.date.fromisoformat(r["czas"][:10])
            monday = d - datetime.timedelta(days=d.weekday())
            w = weeks.setdefault(monday.isoformat(), {"bitwy": 0, "wygrane": 0, "zestrzelenia": 0, "obrazenia": 0,
                                                       "trafienia": 0, "strzaly": 0})
            w["bitwy"] += 1
            w["wygrane"] += 1 if r["wynik"] == "wygrana" else 0
            for k in ("zestrzelenia", "obrazenia", "trafienia", "strzaly"):
                w[k] += r[k]
        week_list = []
        for k, w in sorted(weeks.items()):
            week_list.append(dict(w, tydzien=k, celnosc=accuracy(w["trafienia"], w["strzaly"]),
                                  obrazenia_na_bitwe=w["obrazenia"] / w["bitwy"], zestrz_na_bitwe=w["zestrzelenia"] / w["bitwy"],
                                  wygrane_proc=100.0 * w["wygrane"] / w["bitwy"]))
        best_kills = max(rows, key=lambda r: (r["zestrzelenia"], r["obrazenia"])) if rows else None
        best_damage = max(rows, key=lambda r: r["obrazenia"]) if rows else None
        last_perf = perf[-1] if perf else {}
        return {
            "nick": nick, "bitwy": n, "wygrane": wins,
            "przegrane": sum(1 for r in rows if r["wynik"] == "przegrana"),
            "wygrane_proc": 100.0 * wins / n if n else None,
            "przezyl_proc": 100.0 * sum(1 for r in rows if r["przezyl"]) / n if n else None,
            "celnosc": accuracy(tot["trafienia"], tot["strzaly"]),
            "sesje": sessions, "czas_s": play_s, "pierwszy_raz": first, "ostatnio": last,
            "rekord_zestrzelen": best_kills, "rekord_obrazen": best_damage,
            "tygodnie": week_list, "ostatnie": list(reversed(rows))[:20],
            "fps_med": median([p.get("fps") for p in perf[-10:]]), "ping_med": median([p.get("ping") for p in perf[-10:]]),
            "karta": str(last_perf.get("karta", "")), "jakosc": str(last_perf.get("jakosc", "")),
            **tot,
        }


# ---------- dane osobowe (KAN-212) ----------

def player_events(directory: str, nick: str) -> list:
    """Wszystkie zdarzenia z udziałem gracza (do pobrania przez niego samego: Moje konto → Moje dane)."""
    key = nick.lower()
    out = []
    for ev in Stats(directory).events(0):
        if str(ev.get("gracz", "")).lower() == key:
            out.append(ev)
        elif ev.get("zd") == "bitwa_koniec":
            mine = [g for g in ev.get("gracze", []) if isinstance(g, dict) and str(g.get("gracz", "")).lower() == key]
            if mine:
                out.append({"czas": ev.get("czas"), "zd": "bitwa_koniec", "serwer": ev.get("serwer"), "bitwa": ev.get("bitwa"),
                            "zwyciezca": ev.get("zwyciezca"), "czas_s": ev.get("czas_s"), "ja": mine[0]})
    return out


def _rewrite(path: str, change) -> int:
    """Przepisuje plik zdarzeń linia po linii (change(ev) → True, gdy zmienione); zwraca liczbę zmienionych linii."""
    changed, lines = 0, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.rstrip("\n")
            try:
                ev = json.loads(raw)
            except ValueError:
                lines.append(raw)
                continue
            if isinstance(ev, dict) and change(ev):
                changed += 1
                raw = json.dumps(ev, ensure_ascii=False)
            lines.append(raw)
    if changed:
        st = os.stat(path)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, path)
    return changed


def anonymize_old(directory: str, days: int, today: datetime.date = None) -> int:
    """Usuwa adresy IP ze zdarzeń starszych niż `days` dni (RODO: IP tylko tak długo, jak potrzeba)."""
    limit = (today or datetime.date.today()) - datetime.timedelta(days=days)
    total = 0

    def strip_ip(ev):
        if ev.get("ip"):
            ev["ip"] = ""
            return True
        return False
    for path in Stats(directory).files():
        m = FILE_RE.search(os.path.basename(path))
        if m and datetime.date.fromisoformat(m.group(1)) < limit:
            total += _rewrite(path, strip_ip)
    return total


def forget(directory: str, nick: str) -> int:
    """Prośba gracza o usunięcie danych: nick zastąpiony stałym pseudonimem, IP i dane komputera usunięte
    (wyniki bitew zostają w statystykach ogólnych, bez możliwości przypisania)."""
    key = nick.lower()
    alias = "usuniety-" + hashlib.sha256(key.encode()).hexdigest()[:6]
    machine = ("karta", "procesor", "system", "ekran", "ip")

    def change(ev):
        hit = False
        if str(ev.get("gracz", "")).lower() == key:
            ev["gracz"] = alias
            for k in machine:
                if k in ev:
                    ev[k] = ""
            hit = True
        for g in ev.get("gracze", []) if isinstance(ev.get("gracze"), list) else []:
            if isinstance(g, dict) and str(g.get("gracz", "")).lower() == key:
                g["gracz"] = alias
                hit = True
            elif isinstance(g, str) and g.lower() == key:
                hit = True
        if isinstance(ev.get("gracze"), list) and any(isinstance(g, str) for g in ev["gracze"]):
            ev["gracze"] = [alias if isinstance(g, str) and g.lower() == key else g for g in ev["gracze"]]
        return hit
    total = 0
    for path in Stats(directory).files():
        total += _rewrite(path, change)
    return total


if __name__ == "__main__":
    import sys
    # sudo -u warofsteam python3 statystyki.py anonimizuj 90 /var/lib/warofsteam/statystyki
    # sudo -u warofsteam python3 statystyki.py zapomnij NICK /var/lib/warofsteam/statystyki
    if len(sys.argv) >= 3 and sys.argv[1] == "anonimizuj":
        d = sys.argv[3] if len(sys.argv) > 3 else "/var/lib/warofsteam/statystyki"
        print("Usunięte IP ze zdarzeń starszych niż %s dni: %d" % (sys.argv[2], anonymize_old(d, int(sys.argv[2]))))
    elif len(sys.argv) >= 3 and sys.argv[1] == "zapomnij":
        d = sys.argv[3] if len(sys.argv) > 3 else "/var/lib/warofsteam/statystyki"
        print("Zdarzeń z graczem %s zmienionych: %d" % (sys.argv[2], forget(d, sys.argv[2])))
    else:
        print("użycie: statystyki.py anonimizuj DNI [KATALOG] | zapomnij NICK [KATALOG]")
        sys.exit(2)

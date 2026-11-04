#!/usr/bin/env python3
"""Raport ze statystyk serwera War of Steam (KAN-185). Na serwerze: warofsteam-raport [opcje]

  (bez opcji)          dzisiaj
  --dni=N              ostatnie N dni (z dzisiejszym)
  --data=RRRR-MM-DD    jeden dzień
  --csv=KATALOG        dodatkowo pliki CSV (gracze, bitwy_graczy, wydajnosc_graczy, serwer) – np. do Excela
  --katalog=ŚCIEŻKA    pliki zdarzeń (domyślnie /var/lib/warofsteam/statystyki)

Pliki: <katalog>/zdarzenia-RRRR-MM-DD.jsonl – zapisuje je serwer (server/stats_log.gd).
"""
import csv
import datetime
import glob
import json
import os
import statistics
import sys

DEFAULT_DIR = "/var/lib/warofsteam/statystyki"


def load(directory, days):
    events = []
    for day in days:
        # bitwa 1: zdarzenia-RRRR-MM-DD.jsonl, kolejne: zdarzenia-RRRR-MM-DD-b<N>.jsonl (KAN-206)
        for path in sorted(glob.glob(os.path.join(directory, "zdarzenia-%s*.jsonl" % day.isoformat()))):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    events.sort(key=lambda e: str(e.get("czas", "")))
    return events


def med(values, default=None):
    values = [v for v in values if isinstance(v, (int, float)) and v >= 0]
    return statistics.median(values) if values else default


def fmt(v, digits=0, dash="–"):
    if v is None:
        return dash
    return ("%." + str(digits) + "f") % v


def table(title, header, rows):
    print("\n" + title)
    if not rows:
        print("  (brak)")
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(header)]
    print("  " + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(header)))
    for r in rows:
        print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def build(events):
    players = {}
    def p(nick):
        return players.setdefault(nick, {"serwery": set(), "sesje": 0, "czas_s": 0, "bitwy": 0, "zestrzelenia": 0, "obrazenia": 0,
                                         "trafienia": 0, "strzaly": 0, "naboje": 0, "wyjscia": 0, "ip": set(),
                                         "wersje": set(), "przezyl": 0, "wydajnosc": []})
    battle_rows, perf_rows, server_rows, rejected, battles = [], [], [], [], []
    for e in events:
        kind, nick = e.get("zd"), str(e.get("gracz", "") or "")
        if nick and kind in ("logowanie", "gracz_w_bitwie", "rozlaczenie"):
            p(nick)["serwery"].add(int(e.get("serwer", 1)))
        if kind == "logowanie" and nick:
            pl = p(nick)
            pl["ip"].add(e.get("ip", ""))
            if e.get("wersja"):
                pl["wersje"].add(e["wersja"])
        elif kind == "gracz_w_bitwie" and nick and e.get("wersja"):
            p(nick)["wersje"].add(e["wersja"])
        elif kind == "logowanie_odrzucone":
            rejected.append(e)
        elif kind == "rozlaczenie" and nick:
            pl = p(nick)
            pl["sesje"] += 1
            pl["czas_s"] += int(e.get("sesja_s", 0))
            pl["ip"].add(e.get("ip", ""))
            if e.get("w_trakcie_bitwy"):
                pl["wyjscia"] += 1
        elif kind == "bitwa_koniec":
            battles.append(e)
            for g in e.get("gracze", []):
                pl = p(str(g.get("gracz", "?")))
                pl["bitwy"] += 1
                for k in ("zestrzelenia", "obrazenia", "trafienia", "strzaly", "naboje"):
                    pl[k] += int(g.get(k, 0))
                pl["przezyl"] += 1 if g.get("przezyl") else 0
                battle_rows.append([e.get("czas", ""), e.get("serwer", 1), e.get("bitwa"), g.get("gracz"), g.get("druzyna"),
                                    "wygrana" if g.get("druzyna") == e.get("zwyciezca") else
                                    ("remis" if e.get("zwyciezca") == 0 else "przegrana"),
                                    g.get("zestrzelenia", 0), g.get("obrazenia", 0), g.get("trafienia", 0),
                                    g.get("strzaly", 0), g.get("naboje", 0), "tak" if g.get("przezyl") else "nie"])
        elif kind == "wydajnosc_gracza" and nick:
            p(nick)["wydajnosc"].append(e)
            perf_rows.append([e.get("czas", ""), e.get("serwer", 1), nick, e.get("fps"), e.get("fps_1"), e.get("karta_ms"), e.get("ping"),
                              e.get("przyciecia"), e.get("karta", ""), e.get("jakosc", ""), e.get("skala", ""),
                              e.get("ekran", ""), e.get("system", ""), e.get("procesor", "")])
        elif kind == "serwer":
            server_rows.append(e)
    return players, battle_rows, perf_rows, server_rows, rejected, battles


def main(argv):
    directory, days_back, one_day, csv_dir = DEFAULT_DIR, 1, None, None
    for a in argv:
        if a in ("-h", "--help", "pomoc"):
            print(__doc__)
            return 0
        if a.startswith("--katalog="):
            directory = a.split("=", 1)[1]
        elif a.startswith("--dni="):
            days_back = max(1, int(a.split("=", 1)[1]))
        elif a.startswith("--data="):
            one_day = datetime.date.fromisoformat(a.split("=", 1)[1])
        elif a.startswith("--csv="):
            csv_dir = a.split("=", 1)[1]
    today = datetime.date.today()
    days = [one_day] if one_day else [today - datetime.timedelta(days=i) for i in range(days_back - 1, -1, -1)]
    events = load(directory, days)
    span = days[0].isoformat() if len(days) == 1 else "%s – %s" % (days[0].isoformat(), days[-1].isoformat())
    print("RAPORT War of Steam – %s (zdarzeń: %d, katalog %s)" % (span, len(events), directory))
    if not events:
        print("Brak danych za ten okres.")
        return 0
    players, battle_rows, perf_rows, server_rows, rejected, battles = build(events)

    rows = []
    for nick, pl in sorted(players.items(), key=lambda kv: -kv[1]["czas_s"]):
        shots = pl["strzaly"] + pl["naboje"]
        rows.append([nick, pl["sesje"], "%d" % round(pl["czas_s"] / 60), pl["bitwy"], pl["zestrzelenia"], pl["obrazenia"],
                     pl["trafienia"], pl["strzaly"], pl["naboje"],
                     fmt(100.0 * pl["trafienia"] / shots, 1) if shots else "–", pl["wyjscia"],
                     ", ".join(sorted(i for i in pl["ip"] if i)), ", ".join(sorted(pl["wersje"])),
                     ",".join(str(s) for s in sorted(pl["serwery"]))])
    gracze_header = ["Gracz", "Sesje", "Minut", "Bitwy", "Zestrz.", "Obraż.", "Traf.", "Strzały", "Naboje",
                     "Traf. %", "Wyszedł w bitwie", "IP", "Wersja", "Bitwy nr"]
    table("GRACZE", gracze_header, rows)

    perf = []
    for nick, pl in sorted(players.items()):
        w = pl["wydajnosc"]
        if not w:
            continue
        perf.append([nick, len(w), fmt(med([x.get("fps") for x in w])), fmt(min(x.get("fps_1", 0) for x in w)),
                     fmt(med([x.get("karta_ms") for x in w]), 1), fmt(med([x.get("ping") for x in w])),
                     sum(int(x.get("przyciecia", 0)) for x in w), w[-1].get("karta", ""), w[-1].get("jakosc", "")])
    table("WYDAJNOŚĆ GRACZY (mediana z bitew; FPS 1% – najgorsza bitwa)",
          ["Gracz", "Bitwy", "FPS", "FPS 1%", "Karta ms", "Ping", "Przycięcia", "Karta", "Jakość"], perf)

    if battles:
        lengths = [b.get("czas_s", 0) for b in battles]
        wins = {0: 0, 1: 0, 2: 0}
        for b in battles:
            wins[int(b.get("zwyciezca", 0))] = wins.get(int(b.get("zwyciezca", 0)), 0) + 1
        humans = [len(b.get("gracze", [])) for b in battles]
        print("\nBITWY: %d · średnio %d min · graczy na bitwę: śr. %.1f, maks. %d · wygrane: drużyna 1 – %d, "
              "drużyna 2 – %d, remis – %d" % (len(battles), round(statistics.mean(lengths) / 60), statistics.mean(humans),
                                             max(humans), wins.get(1, 0), wins.get(2, 0), wins.get(0, 0)))
    for num in sorted({int(r.get("serwer", 1)) for r in server_rows}):
        rows_n = [r for r in server_rows if int(r.get("serwer", 1)) == num]
        # uśpiony (pusty) serwer i pomiar z wczytywania przy starcie (FPS < 1) nie zniekształcają średnich
        busy = [r for r in rows_n if not r.get("uspiony") and float(r.get("fps", 0)) >= 1.0]
        cpu = [r.get("procesor_proc") for r in busy if isinstance(r.get("procesor_proc"), (int, float)) and r["procesor_proc"] >= 0]
        if not busy:
            print("SERWER %d: pomiarów %d · cały czas pusty (uśpiony)" % (num, len(rows_n)))
            continue
        print("SERWER %d: pomiarów %d (uśpiony %d) · klatka śr. %s ms (najgorszy pomiar %s ms, najdłuższa klatka %s ms) · FPS min. %s · "
              "procesor śr. %s%%, maks. %s%% · RAM maks. %s MB · graczy maks. %s" % (
                  num, len(rows_n), len(rows_n) - len(busy), fmt(med([r.get("klatka_ms") for r in busy]), 1),
                  fmt(max(r.get("klatka_ms", 0) for r in busy), 1),
                  fmt(max(r.get("klatka_max_ms", 0) for r in busy), 0),
                  fmt(min(r.get("fps", 0) for r in busy), 0),
                  fmt(statistics.mean(cpu), 0) if cpu else "–", fmt(max(cpu), 0) if cpu else "–",
                  max(r.get("ram_mb", 0) for r in rows_n), max(r.get("graczy", 0) for r in rows_n)))
    if rejected:
        reasons = {}
        for r in rejected:
            reasons[r.get("powod", "?")] = reasons.get(r.get("powod", "?"), 0) + 1
        print("ODRZUCONE LOGOWANIA: %d (%s) · IP: %s" % (len(rejected), ", ".join("%s %d" % kv for kv in reasons.items()),
                                                         ", ".join(sorted({r.get("ip", "") for r in rejected}))))

    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
        def write(name, header, data):
            with open(os.path.join(csv_dir, name), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(header)
                w.writerows(data)
        write("gracze.csv", gracze_header, rows)
        write("bitwy_graczy.csv", ["Czas", "Serwer", "Bitwa", "Gracz", "Drużyna", "Wynik", "Zestrz.", "Obraż.", "Traf.", "Strzały",
                                   "Naboje", "Przeżył"], battle_rows)
        write("wydajnosc_graczy.csv", ["Czas", "Serwer", "Gracz", "FPS", "FPS 1%", "Karta ms", "Ping", "Przycięcia", "Karta",
                                       "Jakość", "Skala 3D", "Ekran", "System", "Procesor"], perf_rows)
        keys = ["czas", "serwer", "uspiony", "klatka_ms", "klatka_max_ms", "fps", "skrypty_ms", "fizyka_ms", "procesor_proc", "ram_mb",
                "graczy", "statkow"]
        write("serwer.csv", keys, [[r.get(k, "") for k in keys] for r in server_rows])
        print("\nCSV: %s (gracze.csv, bitwy_graczy.csv, wydajnosc_graczy.csv, serwer.csv)" % csv_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

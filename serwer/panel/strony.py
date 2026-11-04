"""Strony panelu (KAN-209) – zwykły HTML z formularzami, bez JavaScriptu i zewnętrznych plików.

Każda funkcja zwraca gotowy dokument. Wszystkie dane od użytkowników przechodzą przez e() (html.escape).
"""
import html
import urllib.parse

from baza import ROLE_NAMES

e = html.escape

CSS = """
:root{--bg:#17130f;--panel:#221b15;--line:#4a3a28;--text:#eadfcc;--dim:#a8977c;--brass:#c9a35a;--brass2:#e6c27a;
--bad:#d9705a;--ok:#8fbf7a;--input:#14100c}
*{box-sizing:border-box}html{color-scheme:dark}html,body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--brass2)}header{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;padding:12px 18px;
border-bottom:1px solid var(--line);background:#1c1611}header .logo{font-weight:700;letter-spacing:.06em;color:var(--brass2);
margin-right:auto}header nav{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center}
header nav a{text-decoration:none}header nav a.on{text-decoration:underline}
main{max-width:1100px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:4px 0 16px;color:var(--brass2)}
h2{font-size:17px;margin:26px 0 10px;color:var(--brass)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 16px}
label{display:block;margin:10px 0 4px;color:var(--dim);font-size:13px}
input,select{width:100%;max-width:360px;padding:9px 10px;border-radius:7px;border:1px solid var(--line);
background:var(--input);color:var(--text);font-size:15px}
button,.btn{display:inline-block;padding:8px 14px;border-radius:7px;border:1px solid var(--brass);background:#3a2c1b;
color:var(--brass2);font-size:14px;cursor:pointer;text-decoration:none}button:hover{background:#4a3822}
button.bad{border-color:var(--bad);color:var(--bad);background:#2a1712}.row{display:flex;flex-wrap:wrap;gap:8px;
align-items:end}.row>div{flex:1 1 220px}form.inline{display:inline;margin:0}
.msg{padding:10px 14px;border-radius:8px;margin:0 0 16px;border:1px solid var(--line)}.msg.ok{border-color:var(--ok);
color:var(--ok)}.msg.bad{border-color:var(--bad);color:var(--bad)}
.secret{font:600 22px/1.2 ui-monospace,Consolas,monospace;letter-spacing:.06em;color:var(--brass2);padding:10px 14px;
background:var(--input);border:1px dashed var(--brass);border-radius:8px;display:inline-block;user-select:all}
.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;
padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:middle;white-space:nowrap}th{color:var(--dim);
font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}td.actions{white-space:normal}
.tag{font-size:12px;padding:2px 7px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
.tag.owner{border-color:var(--brass);color:var(--brass2)}.tag.admin{border-color:#8aa6c9;color:#a9c4e6}
.tag.off{border-color:var(--bad);color:var(--bad)}.tag.win{border-color:var(--ok);color:var(--ok)}
.tag.loss{border-color:var(--bad);color:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:0 0 16px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:24px;color:var(--brass2);font-variant-numeric:tabular-nums}.tile span{color:var(--dim);font-size:13px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}.bar{display:inline-block;height:9px;border-radius:3px;
background:var(--brass);vertical-align:middle;margin-right:6px}.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.battles{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.battles .card{margin:0}.battles h2{margin:0 0 6px}.battles select,.battles input{max-width:none}
.check{display:flex;gap:8px;align-items:center;margin:12px 0 0;color:var(--text);font-size:15px}
.check input{width:auto}.players{list-style:none;padding:0;margin:8px 0}.players li{display:flex;gap:8px;
align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--line)}
.tabs a{padding:5px 12px;border:1px solid var(--line);border-radius:999px;text-decoration:none}.tabs a.on{border-color:var(--brass);
background:#3a2c1b}.dim{color:var(--dim)}.login{max-width:420px;margin:60px auto}
@media (max-width:600px){header{padding:10px 12px}main{padding:16px 12px 50px}}
"""


def page(title: str, body: str, user=None, csrf: str = "", active: str = "") -> str:
    nav = ""
    if user is not None:
        links = [("/konto", "Moje konto")]
        if user["role"] in ("owner", "admin"):
            links = [("/admin/bitwy", "Bitwy"), ("/admin/statystyki", "Statystyki"), ("/admin/gracze", "Gracze"),
                     ("/admin/dziennik", "Dziennik")] + links
        items = "".join('<a href="%s"%s>%s</a>' % (href, ' class="on"' if href == active else "", e(label))
                        for href, label in links)
        nav = ('<nav>%s<span class="dim">%s</span><form class="inline" method="post" action="/wyloguj">'
               '<input type="hidden" name="csrf" value="%s"><button>Wyloguj</button></form></nav>'
               % (items, e(user["nick"]), e(csrf)))
    return ("<!doctype html><html lang=\"pl\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s – War of Steam</title><style>%s</style></head><body>"
            "<header><span class=\"logo\">WAR OF STEAM · panel</span>%s</header><main>%s</main></body></html>"
            % (e(title), CSS, nav, body))


def message(text: str, ok: bool = True) -> str:
    return '<div class="msg %s">%s</div>' % ("ok" if ok else "bad", e(text)) if text else ""


def login_page(error: str = "", login: str = "") -> str:
    body = ('<div class="login"><h1>Logowanie</h1>%s<div class="card"><form method="post" action="/logowanie">'
            '<label for="l">E-mail albo nick</label><input id="l" name="login" autocomplete="username" required value="%s">'
            '<label for="p">Hasło</label><input id="p" name="haslo" type="password" autocomplete="current-password" required>'
            '<p><button>Zaloguj</button></p></form></div>'
            '<p class="dim">Konto zakłada organizator testów. Zapomniane hasło – napisz do niego, ustawi nowe.</p>'
            '<p class="dim"><a href="/prywatnosc">Jakie dane zbieramy (prywatność)</a></p></div>'
            % (message(error, False), e(login)))
    return page("Logowanie", body)


def account_page(user, csrf: str, info: str = "", error: str = "", progress=None) -> str:
    body = ('<h1>Moje konto</h1>%s%s%s<h2>Dane konta</h2><div class="card"><table>'
            '<tr><th>Nick (w bitwie)</th><td>%s</td></tr><tr><th>E-mail (login)</th><td>%s</td></tr>'
            '<tr><th>Rola</th><td>%s</td></tr><tr><th>Konto od</th><td>%s</td></tr></table></div>'
            '<h2>Zmiana hasła</h2><div class="card"><form method="post" action="/konto/haslo">'
            '<input type="hidden" name="csrf" value="%s">'
            '<label for="a">Obecne hasło</label><input id="a" name="obecne" type="password" autocomplete="current-password" required>'
            '<label for="b">Nowe hasło (co najmniej 8 znaków)</label><input id="b" name="nowe" type="password" autocomplete="new-password" required minlength="8">'
            '<label for="c">Powtórz nowe hasło</label><input id="c" name="powtorz" type="password" autocomplete="new-password" required minlength="8">'
            '<p><button>Zmień hasło</button></p></form>'
            '<p class="dim">Po zmianie w grze wpisz nowe hasło w Ustawieniach → Konto.</p></div>'
            '<h2>Moje dane</h2><div class="card"><p><a class="btn" href="/konto/dane">Pobierz moje dane (JSON)</a></p>'
            '<p class="dim">Wszystko, co gra i panel zapisały o Tobie. <a href="/prywatnosc">Jakie dane zbieramy i po co</a>. '
            'Usunięcie konta i danych – poproś organizatora testów.</p></div>'
            % (message(info), message(error, False), progress_html(progress, own=True) if progress is not None else "",
               e(user["nick"]), e(user["email"] or "–"),
               e(ROLE_NAMES[user["role"]]), e(user["utworzone"][:10]), e(csrf)))
    return page("Moje konto", body, user, csrf, "/konto")


def _actions(db, actor, u, csrf: str) -> str:
    if not db.can_manage(actor, u):
        return '<span class="dim">–</span>'
    hidden = '<input type="hidden" name="csrf" value="%s">' % e(csrf)
    parts = ['<form class="inline" method="post" action="/admin/gracze/%d/reset">%s<button>Nowe hasło</button></form>'
             % (u["id"], hidden)]
    if u["aktywne"]:
        parts.append('<form class="inline" method="post" action="/admin/gracze/%d/wylacz">%s<button>Wyłącz</button></form>'
                     % (u["id"], hidden))
    else:
        parts.append('<form class="inline" method="post" action="/admin/gracze/%d/wlacz">%s<button>Włącz</button></form>'
                     % (u["id"], hidden))
    parts.append('<a class="btn" href="/admin/gracze/%d/usun">Usuń</a>' % u["id"])
    return " ".join(parts)


def users_page(db, actor, csrf: str, info: str = "", error: str = "", form=None) -> str:
    form = form or {}
    rows = []
    for u in db.users():
        tags = '<span class="tag %s">%s</span>' % (u["role"], e(ROLE_NAMES[u["role"]]))
        if not u["aktywne"]:
            tags += ' <span class="tag off">wyłączone</span>'
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class=\"actions\">%s</td></tr>" % (
            e(u["nick"]), e(u["email"] or "–"), tags, e(u["utworzone"][:10]), e((u["ostatnie_logowanie"] or "–")[:16]),
            _actions(db, actor, u, csrf)))
    roles = "".join('<option value="%s"%s>%s</option>' % (r, " selected" if form.get("rola") == r else "",
                    e(ROLE_NAMES[r])) for r in db.roles_for(actor))
    body = ('<h1>Gracze</h1>%s%s<h2>Nowe konto</h2><div class="card"><form method="post" action="/admin/gracze/nowy">'
            '<input type="hidden" name="csrf" value="%s"><div class="row">'
            '<div><label for="m">E-mail (login)</label><input id="m" name="email" type="email" required value="%s"></div>'
            '<div><label for="n">Nick w bitwie (3–16 znaków)</label><input id="n" name="nick" required minlength="3" maxlength="16" value="%s"></div>'
            '<div><label for="r">Rola</label><select id="r" name="rola">%s</select></div>'
            '<div><button>Załóż konto</button></div></div></form>'
            '<p class="dim">Hasło pokażę raz – przekaż je graczowi razem z e-mailem (login w grze: Ustawienia → Konto).</p></div>'
            '<h2>Konta (%d)</h2><div class="card tablewrap"><table><tr><th>Nick</th><th>E-mail</th><th>Rola</th>'
            '<th>Od</th><th>Ostatnio w panelu</th><th>Działania</th></tr>%s</table></div>'
            % (message(info), message(error, False), e(csrf), e(form.get("email", "")), e(form.get("nick", "")), roles,
               len(rows), "".join(rows)))
    return page("Gracze", body, actor, csrf, "/admin/gracze")


def password_page(actor, csrf: str, target, password: str, created: bool) -> str:
    body = ('<h1>%s</h1><div class="card"><p>%s <b>%s</b> (%s)</p><p>Hasło – <b>widać je tylko teraz</b>, przekaż je graczowi:</p>'
            '<p class="secret">%s</p><p class="dim">Login w grze i w panelu: %s. Gracz może zmienić hasło w panelu: Moje konto.</p>'
            '<p><a class="btn" href="/admin/gracze">Wróć do listy</a></p></div>'
            % ("Konto założone" if created else "Nowe hasło", "Konto" if created else "Nowe hasło dla",
               e(target["nick"]), e(target["email"] or "bez e-maila"), e(password), e(target["email"] or target["nick"])))
    return page("Hasło", body, actor, csrf, "/admin/gracze")


def confirm_delete_page(actor, csrf: str, target) -> str:
    body = ('<h1>Usunąć konto?</h1><div class="card"><p><b>%s</b> (%s) – konto zniknie z panelu i z gry. '
            'Statystyki z bitew zostają.</p><form class="inline" method="post" action="/admin/gracze/%d/usun">'
            '<input type="hidden" name="csrf" value="%s"><button class="bad">Usuń na zawsze</button></form> '
            '<a class="btn" href="/admin/gracze">Anuluj</a></div>'
            % (e(target["nick"]), e(target["email"] or "bez e-maila"), target["id"], e(csrf)))
    return page("Usuwanie", body, actor, csrf, "/admin/gracze")


def log_page(db, actor, csrf: str) -> str:
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td style=\"white-space:normal\">%s</td></tr>" % (
        e(r["czas"]), e(r["kto_nick"] or "serwer"), e(r["akcja"]), e(r["szczegoly"])) for r in db.log_entries())
    body = ('<h1>Dziennik działań</h1><div class="card tablewrap"><table><tr><th>Czas</th><th>Kto</th><th>Co</th>'
            '<th>Szczegóły</th></tr>%s</table></div>' % rows)
    return page("Dziennik", body, actor, csrf, "/admin/dziennik")


def error_page(code: int, text: str, user=None, csrf: str = "") -> str:
    return page("Błąd", '<h1>%d</h1>%s<p><a class="btn" href="/">Strona główna</a></p>'
                % (code, message(text, False)), user, csrf)


# ---------- statystyki (KAN-210) ----------

def num(v, digits: int = 0, suffix: str = "") -> str:
    if v is None:
        return "–"
    text = ("{:,.%df}" % digits).format(v).replace(",", "\u00a0").replace(".", ",")   # 5 900 · 36,7
    return text + suffix


def duration(seconds) -> str:
    seconds = int(seconds or 0)
    h, m = divmod(seconds // 60, 60)
    return "%d h %02d min" % (h, m) if h else "%d min" % m


def bar(value, top, width: int = 90) -> str:
    if not top or not value:
        return ""
    return '<span class="bar" style="width:%dpx"></span>' % max(2, round(width * value / top))


def tile(value: str, label: str) -> str:
    return '<div class="tile"><b>%s</b><span>%s</span></div>' % (e(value), e(label))


def result_tag(r: str) -> str:
    return '<span class="tag %s">%s</span>' % ({"wygrana": "win", "przegrana": "loss"}.get(r, ""), e(r))


def player_link(nick: str) -> str:
    return '<a href="/admin/statystyki/gracz?nick=%s">%s</a>' % (urllib.parse.quote(nick), e(nick))


def progress_html(pr: dict, own: bool) -> str:
    """Postępy gracza – na stronie Moje konto (own) i u admina."""
    if not pr or not pr["bitwy"]:
        return ('<h2>%s</h2><div class="card dim">Brak rozegranych bitew. Statystyki pojawią się po pierwszej bitwie '
                'na serwerze (Bitwa losowa).</div>' % ("Moje postępy" if own else "Postępy"))
    tiles = "".join([
        tile(num(pr["bitwy"]), "bitew"), tile(num(pr["wygrane_proc"], 0, "%"), "wygranych"),
        tile(num(pr["zestrzelenia"]), "zestrzeleń"), tile(num(pr["obrazenia"]), "zadanych obrażeń"),
        tile(num(pr["celnosc"], 1, "%"), "celność"), tile(num(pr["przezyl_proc"], 0, "%"), "bitew przeżytych"),
        tile(duration(pr["czas_s"]), "w grze (%d sesji)" % pr["sesje"]),
    ])
    rec = []
    if pr["rekord_zestrzelen"]:
        r = pr["rekord_zestrzelen"]
        rec.append("najwięcej zestrzeleń: <b>%d</b> (%s, %s)" % (r["zestrzelenia"], e(r["czas"][:10]), e(r["mapa"])))
    if pr["rekord_obrazen"]:
        r = pr["rekord_obrazen"]
        rec.append("najwięcej obrażeń: <b>%s</b> (%s, %s)" % (num(r["obrazenia"]), e(r["czas"][:10]), e(r["mapa"])))
    weeks = pr["tygodnie"]
    top_dmg = max((w["obrazenia_na_bitwe"] for w in weeks), default=0)
    week_rows = "".join(
        '<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td><td>%s%s</td>'
        '<td class="num">%s</td></tr>' % (e(w["tydzien"]), w["bitwy"], num(w["wygrane_proc"], 0, "%"),
                                          num(w["zestrz_na_bitwe"], 1), bar(w["obrazenia_na_bitwe"], top_dmg),
                                          num(w["obrazenia_na_bitwe"]), num(w["celnosc"], 1, "%"))
        for w in reversed(weeks))
    last_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s%s</td><td>%s</td><td class="num">%d</td><td class="num">%s</td>'
        '<td class="num">%s</td><td>%s</td></tr>' % (
            e(r["czas"][:16]), e(r["mapa"]), e(r["pora"]), ", deszcz" if r["deszcz"] else "", result_tag(r["wynik"]),
            r["zestrzelenia"], num(r["obrazenia"]), num(100.0 * r["trafienia"] / r["strzaly"], 0, "%") if r["strzaly"] else "–",
            "tak" if r["przezyl"] else "nie")
        for r in pr["ostatnie"])
    perf = ""
    if pr["fps_med"] is not None:
        perf = ('<p class="dim">Wydajność (ostatnie bitwy): %s FPS, ping %s ms · %s · jakość %s</p>'
                % (num(pr["fps_med"]), num(pr["ping_med"]), e(pr["karta"] or "?"), e(pr["jakosc"] or "?")))
    return ('<h2>%s</h2><div class="tiles">%s</div>%s'
            '<div class="card"><p class="dim">Od %s · ostatnio %s</p>%s</div>'
            '<h2>Tydzień po tygodniu</h2><div class="card tablewrap"><table><tr><th>Tydzień od</th><th class="num">Bitwy</th>'
            '<th class="num">Wygrane</th><th class="num">Zestrz. / bitwę</th><th>Obrażenia / bitwę</th><th class="num">Celność</th>'
            '</tr>%s</table></div>'
            '<h2>Ostatnie bitwy</h2><div class="card tablewrap"><table><tr><th>Kiedy</th><th>Mapa</th><th>Pora</th><th>Wynik</th>'
            '<th class="num">Zestrz.</th><th class="num">Obraż.</th><th class="num">Celność</th><th>Przeżył</th></tr>%s</table></div>'
            % ("Moje postępy" if own else "Postępy", tiles,
               "<p>%s</p>" % " · ".join(rec) if rec else "",
               e(pr["pierwszy_raz"][:10] or "–"), e(pr["ostatnio"][:16] or "–"), perf, week_rows, last_rows))


def stats_page(ov: dict, actor, csrf: str, show_ip: bool) -> str:
    tabs = "".join('<a href="/admin/statystyki?dni=%d"%s>%s</a>' % (d, ' class="on"' if ov["dni"] == d else "", label)
                   for d, label in ((1, "Dziś"), (7, "7 dni"), (30, "30 dni"), (0, "Wszystko")))
    tiles = "".join([
        tile(num(ov["unikalni"]), "graczy"), tile(duration(ov["czas_s"]), "łącznie w grze"),
        tile(num(ov["bitwy_z_graczami"]), "bitew z graczami"), tile(num(ov["bitwy_razem"]), "bitew razem (z botami)"),
        tile(num(ov["odrzucone"]["razem"]), "odrzuconych logowań"),
    ])
    days = ov["dni_lista"]
    top_players = max((d["gracze"] for d in days), default=0)
    day_rows = "".join(
        '<tr><td>%s</td><td>%s%d</td><td class="num">%d</td><td class="num">%s</td><td class="num">%d</td>'
        '<td class="num">%d</td><td class="num">%d</td></tr>' % (
            e(d["data"]), bar(d["gracze"], top_players), d["gracze"], d["sesje"], duration(d["czas_s"]),
            d["bitwy_z_graczami"], d["bitwy"], d["odrzucone"]) for d in days)
    ip_head = "<th>IP</th>" if show_ip else ""
    player_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num">%d</td><td class="num">%s</td>'
        '<td class="num">%d</td><td class="num">%s</td><td class="num">%s</td><td class="num">%d</td><td class="num">%s</td>'
        '<td>%s</td><td>%s</td>%s</tr>' % (
            player_link(p["nick"]), e(p["ostatnio"][:16] or "–"), p["sesje"], duration(p["czas_s"]), p["bitwy"],
            num(100.0 * p["wygrane"] / p["bitwy"], 0, "%") if p["bitwy"] else "–", p["zestrzelenia"], num(p["obrazenia"]),
            num(p["celnosc"], 1, "%"), p["wyjscia"], num(p["fps_med"]), e(p["karta"] or "–"), e(p["wersja"] or "–"),
            "<td>%s</td>" % e(", ".join(p["ip"]) or "–") if show_ip else "")
        for p in ov["gracze"])
    battle_rows = "".join(
        '<tr><td>%s</td><td class="num">%d</td><td>%s</td><td>%s%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>' % (
            e(b["czas"][:16]), b["serwer"], e(b["mapa"]), e(b["pora"]), ", deszcz" if b["deszcz"] else "",
            duration(b["czas_s"]), "remis" if not b["zwyciezca"] else "drużyna %d" % b["zwyciezca"],
            ", ".join("%s (%s, %d zestrz.)" % (player_link(str(g.get("gracz", "?"))),
                                              result_for_tag(g.get("druzyna"), b["zwyciezca"]), int(g.get("zestrzelenia", 0) or 0))
                      for g in b["gracze"]))
        for b in ov["bitwy"])
    server_rows = "".join(
        '<tr><td>Bitwa %d</td><td>%s</td><td class="num">%d</td><td class="num">%d</td><td class="num">%s</td>'
        '<td class="num">%s</td><td class="num">%s</td><td class="num">%d</td><td class="num">%d</td></tr>' % (
            n, e(s["ostatni"][:16]), s["pomiary"], s["uspiony"], num(s["klatka_med"], 1, " ms"), num(s["cpu_sr"], 0, "%"),
            num(s["cpu_maks"], 0, "%"), s["ram_maks"], s["graczy_maks"])
        for n, s in ov["serwery"].items())
    rej = ov["odrzucone"]
    rej_text = ""
    if rej["razem"]:
        rej_text = '<p class="dim">Odrzucone logowania: %s%s</p>' % (
            e(", ".join("%s – %d" % kv for kv in sorted(rej["powody"].items()))),
            (" · IP: " + e(", ".join(rej["ip"]))) if show_ip else "")
    empty = '<tr><td colspan="14" class="dim">Brak danych w tym okresie.</td></tr>'
    body = ('<h1>Statystyki gry</h1><div class="tabs">%s</div><div class="tiles">%s</div>'
            '<h2>Gracze</h2><div class="card tablewrap"><table><tr><th>Gracz</th><th>Ostatnio</th><th class="num">Sesje</th>'
            '<th class="num">W grze</th><th class="num">Bitwy</th><th class="num">Wygrane</th><th class="num">Zestrz.</th>'
            '<th class="num">Obraż.</th><th class="num">Celność</th><th class="num">Wyszedł w bitwie</th><th class="num">FPS</th>'
            '<th>Karta</th><th>Wersja</th>%s</tr>%s</table></div>'
            '<h2>Dzień po dniu</h2><div class="card tablewrap"><table><tr><th>Dzień</th><th>Graczy</th><th class="num">Sesje</th>'
            '<th class="num">W grze</th><th class="num">Bitwy z graczami</th><th class="num">Bitwy razem</th>'
            '<th class="num">Odrzucone</th></tr>%s</table></div>'
            '<h2>Ostatnie bitwy z graczami</h2><div class="card tablewrap"><table><tr><th>Koniec</th><th class="num">Bitwa</th>'
            '<th>Mapa</th><th>Pora</th><th class="num">Czas</th><th>Wygrała</th><th>Gracze</th></tr>%s</table></div>'
            '<h2>Serwery</h2><div class="card tablewrap"><table><tr><th>Serwer</th><th>Ostatni pomiar</th><th class="num">Pomiary</th>'
            '<th class="num">Uśpiony</th><th class="num">Klatka</th><th class="num">Procesor śr.</th><th class="num">Procesor maks.</th>'
            '<th class="num">RAM MB</th><th class="num">Graczy maks.</th></tr>%s</table>%s</div>'
            '<p class="dim">Źródło: pliki zdarzeń serwerów gry (zdarzeń w okresie: %d). Procesor – %% jednego rdzenia, '
            'bez czasu uśpienia.</p>'
            % (tabs, tiles, ip_head, player_rows or empty, day_rows or empty, battle_rows or empty, server_rows or empty,
               rej_text, ov["zdarzen"]))
    return page("Statystyki", body, actor, csrf, "/admin/statystyki")


def result_for_tag(team, winner) -> str:
    if not winner:
        return "remis"
    return "wygrana" if team == winner else "przegrana"


def player_stats_page(pr: dict, target, actor, csrf: str) -> str:
    who = ""
    if target is not None:
        who = '<p class="dim">Konto: %s · %s</p>' % (e(target["email"] or "bez e-maila"), e(ROLE_NAMES[target["role"]]))
    else:
        who = '<p class="dim">Nie ma takiego konta w panelu (np. usunięte) – statystyki z plików serwera.</p>'
    body = ('<p><a href="/admin/statystyki">← Statystyki</a></p><h1>%s</h1>%s%s'
            % (e(pr["nick"]), who, progress_html(pr, own=False)))
    return page(pr["nick"], body, actor, csrf, "/admin/statystyki")


# ---------- bitwy (KAN-211) ----------

def _options(values: dict, current: str) -> str:
    return "".join('<option value="%s"%s>%s</option>' % (e(k), " selected" if k == current else "", e(v))
                   for k, v in values.items())


def battles_page(states: dict, settings: dict, maps: list, actor, csrf: str, info: str = "", error: str = "") -> str:
    from sterowanie import PORY, DESZCZ, TEAM_MIN, TEAM_MAX, TIME_MIN, TIME_MAX
    hidden = '<input type="hidden" name="csrf" value="%s">' % e(csrf)
    cards = []
    for n in sorted(states):
        st, cfg = states[n], settings.get(n, {})
        if st is None:
            live = '<p class="dim">Nie działa (brak stanu z serwera). Uruchomisz ją na serwerze: sudo warofsteam-bitwy %d</p>' % max(n, 1)
        else:
            state_tag = ('<span class="tag win">działa</span>' if st.get("dziala") else '<span class="tag loss">nie odpowiada</span>')
            if st.get("dziala") and not st.get("wlaczona", True):
                state_tag += ' <span class="tag off">wyłączona w panelu</span>'
            phase = "uśpiona (pusta)" if st.get("uspiony") else str(st.get("faza", "?"))
            players = st.get("gracze", []) or []
            items = "".join(
                '<li><span>%s</span><form class="inline" method="post" action="/admin/bitwy/wyrzuc">%s'
                '<input type="hidden" name="gracz" value="%s"><input type="hidden" name="bitwa" value="%d">'
                '<button class="bad">Wyrzuć</button></form></li>' % (e(str(p)), hidden, e(str(p)), n) for p in players)
            live = ('<p>%s · %s · %s, %s%s · drużyna %s · %s min</p><p class="dim">Następna bitwa za ok. %s · wersja %s</p>'
                    '<p><b>Gracze (%d)</b></p><ul class="players">%s</ul>'
                    % (state_tag, e(phase), e(str(st.get("mapa") or "–")), e(PORY.get(str(st.get("pora")), "–")),
                       ", deszcz" if st.get("deszcz") else "", e(str(st.get("druzyna", "?"))),
                       e(str(st.get("czas_bitwy_min", "?"))), duration(st.get("nastepna_za_s", 0)),
                       e(str(st.get("wersja", "?"))), len(players), items or '<li class="dim">nikt</li>'))
        map_opts = {"": "jak w konfiguracji serwera", "losowo": "losowo (wszystkie)"}
        map_opts.update({m: m for m in maps})
        enabled = cfg.get("wlaczona", True)
        form = ('<form method="post" action="/admin/bitwy/%d">%s'
                '<label class="check"><input type="checkbox" name="wlaczona" value="tak"%s> Bitwa włączona '
                '(wyłączona: gra jej nie wybiera, nowi gracze nie wejdą)</label>'
                '<label>Mapa</label><select name="mapa">%s</select>'
                '<div class="row"><div><label>Pora dnia</label><select name="pora">%s</select></div>'
                '<div><label>Deszcz</label><select name="deszcz">%s</select></div></div>'
                '<div class="row"><div><label>Statków w drużynie (%d–%d, boty uzupełniają)</label>'
                '<input name="druzyna" type="number" min="%d" max="%d" value="%d"></div>'
                '<div><label>Czas bitwy, min (%d–%d)</label><input name="czas_bitwy_min" type="number" min="%d" max="%d" value="%d"></div></div>'
                '<p><button>Zapisz – od następnej bitwy</button></p></form>'
                % (n, hidden, " checked" if enabled else "", _options(map_opts, str(cfg.get("mapa", ""))),
                   _options(PORY, str(cfg.get("pora", "losowo"))), _options(DESZCZ, str(cfg.get("deszcz", "losowo"))),
                   TEAM_MIN, TEAM_MAX, TEAM_MIN, TEAM_MAX, int(cfg.get("druzyna", (st or {}).get("druzyna", 10))),
                   TIME_MIN, TIME_MAX, TIME_MIN, TIME_MAX, int(cfg.get("czas_bitwy_min", (st or {}).get("czas_bitwy_min", 10)))))
        cards.append('<div class="card"><h2>Bitwa %d</h2>%s<hr style="border:0;border-top:1px solid var(--line)">%s</div>'
                     % (n, live, form))
    body = ('<h1>Bitwy</h1>%s%s<p class="dim">Stan odświeża się co kilka sekund (odśwież stronę). Ustawienia działają od '
            'następnej bitwy; wyrzucenie i wyłączenie – od razu. Gracza na stałe zablokujesz w „Gracze → Wyłącz”.</p>'
            '<div class="battles">%s</div>' % (message(info), message(error, False), "".join(cards)))
    return page("Bitwy", body, actor, csrf, "/admin/bitwy")


# ---------- prywatność (KAN-212) ----------

IP_DAYS = 90


def privacy_page(contact: str, user=None, csrf: str = "") -> str:
    who = ("organizator testów, kontakt: <a href=\"mailto:%s\">%s</a>" % (e(contact), e(contact))) if contact \
        else "organizator testów (kontakt – ten sam, od którego masz zaproszenie)"
    body = ('<h1>Prywatność – jakie dane zbieramy</h1><div class="card">'
            '<p>War of Steam jest w fazie zamkniętych testów. Dane zbieramy tylko po to, żeby testy działały: logowanie, '
            'wyniki bitew, wykrywanie problemów z wydajnością i połączeniem oraz ochrona przed nadużyciami.</p>'
            '<p><b>Kto:</b> %s.</p></div>'
            '<h2>Co zapisujemy</h2><div class="card tablewrap"><table>'
            '<tr><th>Dane</th><th>Po co</th><th>Jak długo</th></tr>'
            '<tr><td style="white-space:normal">E-mail, nick, rola konta; hasło tylko jako skrót (nie da się go odczytać)</td>'
            '<td style="white-space:normal">logowanie w grze i w panelu</td><td style="white-space:normal">do usunięcia konta</td></tr>'
            '<tr><td style="white-space:normal">Adres IP przy połączeniu z serwerem gry</td>'
            '<td style="white-space:normal">diagnoza połączeń, ochrona przed zgadywaniem haseł</td><td>%d dni</td></tr>'
            '<tr><td style="white-space:normal">Wyniki bitew: zestrzelenia, obrażenia, trafienia, czas gry, wejścia i wyjścia</td>'
            '<td style="white-space:normal">statystyki, Twoje postępy, balans gry</td><td style="white-space:normal">do końca testów albo do usunięcia konta</td></tr>'
            '<tr><td style="white-space:normal">Dane komputera: karta graficzna, procesor, system, rozdzielczość, ustawienia grafiki, FPS, ping</td>'
            '<td style="white-space:normal">poprawa wydajności gry na różnych komputerach</td><td style="white-space:normal">do końca testów albo do usunięcia konta</td></tr>'
            '</table></div>'
            '<h2>Twoje prawa</h2><div class="card"><ul>'
            '<li>Wgląd: po zalogowaniu „Moje konto → Pobierz moje dane”.</li>'
            '<li>Poprawienie, usunięcie konta i danych: napisz do organizatora testów. Po usunięciu wyniki bitew zostają tylko '
            'w statystykach ogólnych, bez nicku, IP i danych komputera.</li>'
            '<li>Dane nie są sprzedawane ani przekazywane innym firmom; są na serwerze organizatora testów. '
            'Panel nie używa ciasteczek reklamowych ani śledzących – tylko ciasteczko sesji po zalogowaniu.</li>'
            '</ul></div>' % (who, IP_DAYS))
    return page("Prywatność", body, user, csrf)

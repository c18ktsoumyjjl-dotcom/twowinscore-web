from datetime import datetime, timedelta
from flask import Flask, render_template, request, abort, jsonify, redirect
import data

app = Flask(__name__)
WD = "월화수목금토일"
EMO = {"baseball": "⚾", "basketball": "🏀", "volleyball": "🏐"}
SHORT = {"V리그 남자": "V리그 남", "V리그 여자": "V리그 여"}
TABS = [("kbo", "KBO"), ("mlb", "MLB"), ("npb", "NPB"), ("kbl", "KBL"), ("wkbl", "WKBL"),
        ("vm", "V리그 남"), ("vw", "V리그 여"), ("nba", "NBA")]


def today():
    return datetime.now(data.SEOUL).date()


def parse_day(s):
    try:
        d = datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError:
        return today()
    t = today()
    return d if t - timedelta(days=14) <= d <= t + timedelta(days=7) else t


def day_label(d):
    return f"{d.month}월 {d.day}일 ({WD[d.weekday()]})"


def view(g):
    left_home = g["kind"] != "baseball"   # 야구: 원정 왼쪽 / 홈 오른쪽
    h = {"name": g["home"], "score": g.get("home_score"), "tag": "홈", "logo": g.get("home_logo"), "id": g.get("home_id")}
    a = {"name": g["away"], "score": g.get("away_score"), "tag": "원정", "logo": g.get("away_logo"), "id": g.get("away_id")}
    L, R = (h, a) if left_home else (a, h)
    st = g["state"]
    show = st in ("live", "final") and L["score"] is not None and R["score"] is not None
    if not show:
        L["score"] = R["score"] = None
    L["win"] = R["win"] = False
    if show and st == "final":
        L["win"], R["win"] = L["score"] > R["score"], R["score"] > L["score"]
    badge = {"live": g.get("period") or "진행 중", "final": "종료", "cancelled": "취소",
             "postponed": "연기", "scheduled": g["start"].strftime("%H:%M")}.get(st, "")
    lines = [(lab, hs, as_) if left_home else (lab, as_, hs) for lab, hs, as_ in g.get("lines") or []]
    sub = []
    if g.get("label") and "·" in g["label"]:
        sub.append(g["label"].split("·", 1)[1].strip())
    if g.get("if_necessary"):
        sub.append("필요 시 개최")
    return {"key": str(g["key"]), "kind": g["kind"], "league": SHORT.get(g["site_league"], g["site_league"]),
            "lorder": g["site_order"], "emoji": EMO[g["kind"]], "state": st, "badge": badge,
            "time": g["start"].strftime("%H:%M"), "ts": g["start"].timestamp(), "L": L, "R": R,
            "lines": lines, "sub": " · ".join(sub), "left_home": left_home}


@app.route("/api/games")
def api_games():
    d = parse_day(request.args.get("d"))
    games, failed = data.games_for(d)
    if d == today() and datetime.now(data.SEOUL).hour < 6:   # 자정 넘어 이어지는 전날 경기
        prev, f2 = data.games_for(d - timedelta(days=1))
        games = [g for g in prev if g["state"] == "live"] + games
        failed = sorted(set(failed + f2))
    lk = sorted({g["kind"] for g in games if g["state"] == "live"})
    upstream = min([data.live_ttl(k) for k in lk], default=None)
    return jsonify({"upstream": upstream, "date": d.isoformat(), "label": day_label(d), "failed": failed,
                    "updated": datetime.now(data.SEOUL).strftime("%H:%M:%S"),
                    "games": [view(g) for g in games]})


@app.route("/")
def index():
    d = parse_day(request.args.get("d"))
    t = today()
    return render_template("index.html", page="home", d=d.isoformat(), label=day_label(d),
                           yday=(t - timedelta(days=1)).isoformat(), today=t.isoformat(),
                           tmr=(t + timedelta(days=1)).isoformat(),
                           dmin=(t - timedelta(days=14)).isoformat(), dmax=(t + timedelta(days=7)).isoformat(),
                           f=request.args.get("f", "all"))


@app.route("/live")
def live():
    return redirect("/?f=live")


@app.route("/results")
def results():
    return redirect("/?d=" + (today() - timedelta(days=1)).isoformat())


@app.route("/game/<path:key>")
def game(key):
    d = parse_day(request.args.get("d"))
    g = data.find_game(key, d)
    if not g and d == today():
        g = data.find_game(key, d - timedelta(days=1))
    if not g:
        abort(404)
    v = view(g)
    det = data.detail(g)
    inn = None
    if g["kind"] == "baseball" and g.get("innings") and v["state"] in ("live", "final"):
        raw = g["innings"]
        n = max([9] + [int(k) for s in ("home", "away") for k in raw[s]["inn"] if str(k).isdigit()])
        order = [("away", g["away"]), ("home", g["home"])]
        inn = {"n": list(range(1, n + 1)), "rows": [
            {"name": nm, "inn": [raw[s]["inn"].get(str(i)) for i in range(1, n + 1)],
             "R": g.get(s + "_score"), "H": raw[s].get("H"), "E": raw[s].get("E")} for s, nm in order]}
    # 최근 5경기: 화면 왼쪽 팀부터
    forms = [(v["L"]["name"], det["form_home"] if v["left_home"] else det["form_away"]),
             (v["R"]["name"], det["form_away"] if v["left_home"] else det["form_home"])]
    st = det.get("starters")
    return render_template("game.html", page="game", g=v, d=d.isoformat(), label=day_label(d), inn=inn,
                           forms=[f for f in forms if f[1]], h2h=det["h2h"], starters=st,
                           injuries=det["injuries"], stand=det["standings"], kind=g["kind"],
                           names={g["home"], g["away"]})


@app.route("/standings")
def standings():
    slug = request.args.get("league", "kbo")
    if slug not in data.STANDING_SLUGS:
        abort(404)
    groups, season, ok = data.standings(slug)
    return render_template("standings.html", page="standings", tabs=TABS, slug=slug, lname=dict(TABS)[slug],
                           groups=groups, season=season, ok=ok, kind=data.STANDING_SLUGS[slug][0])


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8088)), threaded=True, debug=False)

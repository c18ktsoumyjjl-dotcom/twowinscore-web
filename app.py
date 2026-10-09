from datetime import datetime, timedelta
from flask import Flask, render_template, request, abort, jsonify, redirect
import data
import chat
import plays

app = Flask(__name__)
app.register_blueprint(chat.bp)
WD = "월화수목금토일"
EMO = {"baseball": "⚾", "basketball": "🏀", "volleyball": "🏐", "football": "⚽", "hockey": "🏒"}
SPORT_KO = {"football": "축구", "baseball": "야구", "basketball": "농구", "volleyball": "배구", "hockey": "아이스하키"}
SHORT = {"V리그 남자": "V리그 남", "V리그 여자": "V리그 여"}
TABS = [("kbo", "KBO"), ("mlb", "MLB"), ("npb", "NPB"), ("kbl", "KBL"), ("wkbl", "WKBL"),
        ("vm", "V리그 남"), ("vw", "V리그 여"), ("nba", "NBA"),
        ("kl1", "K리그1"), ("epl", "EPL"), ("laliga", "라리가"), ("seriea", "세리에A"), ("bundes", "분데스리가"),
        ("ligue1", "리그1"), ("ucl", "챔피언스리그"), ("nhl", "NHL"), ("khl", "KHL")]


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
    left_home = False   # 전 종목 공통: 원정 왼쪽 / 홈 오른쪽
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
            "lines": lines, "sub": " · ".join(sub), "left_home": left_home, "sport": SPORT_KO[g["kind"]],
            "table": period_table(g)}


def period_table(g):
    """구간별 점수표. 원정 위 / 홈 아래. 실제 데이터 없으면 None."""
    if g["state"] not in ("live", "final"):
        return None
    if g["kind"] == "baseball":
        raw = g.get("innings")
        if not raw:
            return None
        n = max([9] + [int(k) for s in ("home", "away") for k in raw[s]["inn"] if str(k).isdigit()])
        cols = [str(i) for i in range(1, n + 1)]
        ext = [c for c in ("H", "E") if any(raw[s].get(c) is not None for s in ("home", "away"))]
        rows = [{"name": g[s], "vals": [raw[s]["inn"].get(c) for c in cols], "T": g.get(s + "_score"),
                 "ext": [raw[s].get(c) for c in ext]} for s in ("away", "home")]
        hv = rows[1]["vals"]
        if g["state"] == "final" and hv and hv[-1] is None and (rows[1]["T"] or 0) > (rows[0]["T"] or 0):
            hv[-1] = "X"
        return {"cols": cols, "tlab": "R", "ext": ext, "rows": rows}
    lines = g.get("lines") or []
    if not lines:
        return None
    lab = {"basketball": lambda x: x if not str(x).isdigit() else f"{x}Q", "volleyball": lambda x: f"{x}세트" if str(x).isdigit() else x}
    f = lab.get(g["kind"], lambda x: x)
    cols = [f(l[0]) for l in lines]
    tl = "세트" if g["kind"] == "volleyball" else "T"
    rows = [{"name": g["away"], "vals": [l[2] for l in lines], "T": g.get("away_score"), "ext": []},
            {"name": g["home"], "vals": [l[1] for l in lines], "T": g.get("home_score"), "ext": []}]
    return {"cols": cols, "tlab": tl, "ext": [], "rows": rows}


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
    forms = [(v["L"]["name"], det["form_away"]), (v["R"]["name"], det["form_home"])]
    st = det.get("starters")
    return render_template("game.html", page="game", g=v, d=d.isoformat(), label=day_label(d), table=v["table"], com=plays.commentary(g),
                           forms=[f for f in forms if f[1]], h2h=det["h2h"], starters=st,
                           injuries=det["injuries"], stand=det["standings"], kind=g["kind"],
                           names={g["home"], g["away"]})


def _find(key):
    d = parse_day(request.args.get("d"))
    g = data.find_game(key, d)
    if not g and d == today():
        g = data.find_game(key, d - timedelta(days=1))
    return g, d


@app.route("/api/preview/<path:key>")
def api_preview(key):
    g, d = _find(key)
    if not g:
        return jsonify({"error": "not found"}), 404
    v = view(g)
    det = data.detail(g)
    forms = [{"name": v["L"]["name"], "rows": det["form_away"]}, {"name": v["R"]["name"], "rows": det["form_home"]}]
    h2h = det.get("h2h") or []
    hsum = None
    if h2h:
        a_w = sum(1 for x in h2h if (x["home"] == g["away"] and x["hs"] > x["as"]) or (x["away"] == g["away"] and x["as"] > x["hs"]))
        h_w = sum(1 for x in h2h if (x["home"] == g["home"] and x["hs"] > x["as"]) or (x["away"] == g["home"] and x["as"] > x["hs"]))
        hsum = {"n": len(h2h), "L": a_w, "R": h_w, "last": h2h[0]}
    pos = None
    st = det.get("standings")
    if st:
        def find(n):
            return next(({"rank": r.get("rank"), "win": r.get("win"), "lose": r.get("lose"), "draw": r.get("draw"), "pts": r.get("pts")}
                         for r in st["rows"] if r["team"] == n), None)
        pos = {"section": st["section"], "L": find(g["away"]), "R": find(g["home"])}
    starters = det.get("starters")
    com = plays.commentary(g)
    return jsonify({"key": v["key"], "kind": g["kind"], "table": v["table"], "L": v["L"]["name"], "R": v["R"]["name"],
                    "starters": starters, "forms": [f for f in forms if f["rows"]], "h2h": hsum, "pos": pos,
                    "plays": {"source": com["source"], "items": com["items"][:3]} if com and com.get("items") else None,
                    "url": f"/game/{v['key']}?d={d.isoformat()}"})


@app.route("/standings")
def standings():
    slug = request.args.get("league", "kbo")
    if slug not in data.STANDING_SLUGS:
        abort(404)
    groups, season, ok = data.standings(slug)
    kind = data.STANDING_SLUGS[slug][0]
    sports = []
    for k in ("football", "baseball", "basketball", "volleyball", "hockey"):
        first = next(t for t, _ in TABS if data.STANDING_SLUGS[t][0] == k)
        sports.append((first, SPORT_KO[k], k == kind))
    tabs = [(t, n) for t, n in TABS if data.STANDING_SLUGS[t][0] == kind]
    return render_template("standings.html", page="standings", tabs=tabs, sports=sports, all_tabs=TABS, slug=slug, lname=dict(TABS)[slug],
                           groups=groups, season=season, ok=ok, kind=data.STANDING_SLUGS[slug][0])


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8088)), threaded=True, debug=False)

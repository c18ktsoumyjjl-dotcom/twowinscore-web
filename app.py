from datetime import datetime, timedelta
from flask import Flask, render_template, request, abort, jsonify, redirect
import data
import chat
import plays
import insights

import threading, time
from collections import deque

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024      # 요청 본문 16KB 까지
app.register_blueprint(chat.bp)

# ---------- 회원 / 관리자 ----------
import os, secrets, logging
import members
_sk = os.environ.get("SECRET_KEY", "").strip()
if not _sk:
    logging.getLogger("app").warning("SECRET_KEY 없음: 임시 키 사용 (재시작 시 로그인 풀림)")
    _sk = secrets.token_hex(32)
app.config.update(SECRET_KEY=_sk, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("INSECURE_COOKIES") != "1",
                  SESSION_COOKIE_NAME="tw_s", PERMANENT_SESSION_LIFETIME=timedelta(days=14))
app.register_blueprint(members.bp)
try:
    members.init_db()
except Exception:
    logging.getLogger("app").exception("member DB init failed")

# ---------- 보안: IP별 요청 제한 ----------
# (경로 접두어, 1분 최대). 캐시에서 나가는 폴링은 같은 와이파이·통신사 공유 IP 를 고려해 넉넉히.
RATE = [("/admin", 120), ("/api/preview/", 20), ("/api/vote", 60), ("/api/chat", 300), ("/api/games", 300), ("/api/", 120), ("/game/", 60)]
_rl, _rl_lock = {}, threading.Lock()


@app.before_request
def _ratelimit():
    p = request.path
    for pre, lim in RATE:
        if p.startswith(pre):
            break
    else:
        return None
    if pre == "/api/chat" and request.method == "POST":
        pre, lim = "chatpost", 30
    now, key = time.time(), pre + "|" + chat._ip()
    with _rl_lock:
        if len(_rl) > 50000:
            for k in [k for k, d in _rl.items() if not d or now - d[-1] > 60]:
                del _rl[k]
        dq = _rl.setdefault(key, deque())
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= lim:
            r = jsonify({"ok": False, "error": "요청이 너무 많아요. 잠시 뒤에 다시 시도해 주세요."})
            r.status_code, r.headers["Retry-After"] = 429, "30"
            return r
        dq.append(now)
    return None


CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://t.me")


@app.after_request
def _sec_headers(r):
    h = r.headers
    h.setdefault("Content-Security-Policy", CSP)
    h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    return r


@app.errorhandler(413)
def _too_big(e):
    return jsonify({"ok": False, "error": "요청이 너무 커요."}), 413
WD = "월화수목금토일"
EMO = {"baseball": "⚾", "basketball": "🏀", "volleyball": "🏐", "football": "⚽", "hockey": "🏒"}
SPORT_KO = {"football": "축구", "baseball": "야구", "basketball": "농구", "volleyball": "배구", "hockey": "아이스하키"}
SHORT = {"V리그 남자": "V리그 남", "V리그 여자": "V리그 여", "튀르키예 여자 술탄라르": "튀르키예 여자"}
TABS = [("kbo", "KBO"), ("mlb", "MLB"), ("npb", "NPB"), ("kbl", "KBL"), ("wkbl", "WKBL"),
        ("vm", "V리그 남"), ("vw", "V리그 여"), ("nba", "NBA"),
        ("kl1", "K리그1"), ("epl", "EPL"), ("laliga", "라리가"), ("seriea", "세리에A"), ("bundes", "분데스리가"),
        ("ligue1", "리그1"), ("ucl", "챔피언스리그"), ("nhl", "NHL"), ("khl", "KHL"),
        ("cpbl", "CPBL"), ("bleague", "B리그"), ("cba", "CBA"), ("easl", "EASL"), ("euroleague", "유로리그"),
        ("svl", "SV리그"), ("ita_w", "이탈리아 여자 A1"), ("tur_w", "튀르키예 여자"),
        ("kl2", "K리그2"), ("wk", "WK리그(여자)"), ("j1", "J1리그"), ("j2", "J2리그"), ("saudi", "사우디"),
        ("champ", "챔피언십"), ("uel", "유로파리그"), ("uecl", "컨퍼런스리그"), ("mls", "MLS"), ("unl", "네이션스리그"),
        ("asia_hk", "아시아리그"), ("liiga", "핀란드 리가"), ("shl", "SHL"), ("ahl", "AHL")]


from decimal import Decimal, ROUND_HALF_UP


@app.template_filter("wpct")
def wpct(r):
    """승률: 승/(승+패) (무승부 제외, KBO 방식), 소수 셋째 자리 반올림, 앞 0 생략 (.625 / 1.000). 경기 없으면 -."""
    w, l = r.get("win"), r.get("lose")
    if w is None or l is None:
        p = r.get("pct")
        if p is None:
            return ""
        v = Decimal(str(p))
    elif w + l == 0:
        return "-"
    else:
        v = Decimal(w) / Decimal(w + l)
    s = str(v.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    return s[1:] if s.startswith("0") else s


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
    left_home = g["kind"] != "baseball"   # 야구: 원정 왼쪽/홈 오른쪽, 그 외: 홈 왼쪽
    h = {"name": g["home"], "en": g.get("home_en"), "score": g.get("home_score"), "tag": "홈", "logo": g.get("home_logo"), "id": g.get("home_id")}
    a = {"name": g["away"], "en": g.get("away_en"), "score": g.get("away_score"), "tag": "원정", "logo": g.get("away_logo"), "id": g.get("away_id")}
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
                 "ext": [raw[s].get(c) for c in ext], "home": s == "home"} for s in ("away", "home")]
        hv = rows[1]["vals"]
        if g["state"] == "final" and hv and hv[-1] is None and (rows[1]["T"] or 0) > (rows[0]["T"] or 0):
            hv[-1] = "X"
        cur = None
        stc = str(g.get("status") or "")
        if g["state"] == "live" and stc.startswith("IN") and stc[2:].isdigit() and int(stc[2:]) <= n:
            cur = int(stc[2:]) - 1
        return {"cols": cols, "tlab": "R", "ext": ext, "rows": rows, "cur": cur}
    lines = g.get("lines") or []
    k = g["kind"]
    REG = {"basketball": ["1Q", "2Q", "3Q", "4Q"], "volleyball": ["1세트", "2세트", "3세트", "4세트", "5세트"],
           "football": ["전반", "후반"], "hockey": ["1P", "2P", "3P"]}.get(k, [])
    norm = {"basketball": lambda x: f"{x}Q" if str(x).isdigit() else x,
            "volleyball": lambda x: f"{x}세트" if str(x).isdigit() else x}.get(k, lambda x: x)
    got = {norm(l[0]): (l[1], l[2]) for l in lines}
    cols = REG + [c for c in got if c not in REG]          # 정규 구간은 항상, 연장 등은 실제 있을 때만
    if not cols:
        return None
    cur = None
    if g["state"] == "live":
        stc = str(g.get("status") or "")
        live_map = {"Q1": "1Q", "Q2": "2Q", "Q3": "3Q", "Q4": "4Q", "OT": "OT", "S1": "1세트", "S2": "2세트", "S3": "3세트",
                    "S4": "4세트", "S5": "5세트", "1H": "전반", "2H": "후반", "ET": "연장", "P": "승부차기",
                    "P1": "1P", "P2": "2P", "P3": "3P", "PT": "SO"}
        c = live_map.get(stc)
        if c and c not in cols:
            cols.append(c)
        cur = cols.index(c) if c else None
    tl = "세트" if k == "volleyball" else "T"
    rows = [{"name": g["home"], "vals": [got.get(c, (None, None))[0] for c in cols], "T": g.get("home_score"), "ext": [], "home": True},
            {"name": g["away"], "vals": [got.get(c, (None, None))[1] for c in cols], "T": g.get("away_score"), "ext": [], "home": False}]
    return {"cols": cols, "tlab": tl, "ext": [], "rows": rows, "cur": cur}


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
    lh = v["left_home"]
    forms = [(v["L"]["name"], det["form_home"] if lh else det["form_away"]), (v["R"]["name"], det["form_away"] if lh else det["form_home"])]
    st = det.get("starters")
    return render_template("game.html", page="game", g=v, d=d.isoformat(), label=day_label(d), table=v["table"], com=plays.commentary(g), gl=plays.goals(g),
                           forms=[f for f in forms if f[1]], h2h=det["h2h"], starters=st,
                           injuries=det["injuries"], stand=det["standings"], kind=g["kind"],
                           names={g["home"], g["away"]}, points=insights.points(g, det), vote=_vinfo(g, v))


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
    lh = v["left_home"]
    forms = [{"name": v["L"]["name"], "rows": det["form_home"] if lh else det["form_away"]},
             {"name": v["R"]["name"], "rows": det["form_away"] if lh else det["form_home"]}]
    h2h = det.get("h2h") or []
    hsum = None
    if h2h:
        a_w = sum(1 for x in h2h if (x["home"] == g["away"] and x["hs"] > x["as"]) or (x["away"] == g["away"] and x["as"] > x["hs"]))
        h_w = sum(1 for x in h2h if (x["home"] == g["home"] and x["hs"] > x["as"]) or (x["away"] == g["home"] and x["as"] > x["hs"]))
        hsum = {"n": len(h2h), "L": h_w if lh else a_w, "R": a_w if lh else h_w, "last": h2h[0]}
    pos = None
    st = det.get("standings")
    if st:
        def find(n):
            return next(({"rank": r.get("rank"), "win": r.get("win"), "lose": r.get("lose"), "draw": r.get("draw"), "pts": r.get("pts")}
                         for r in st["rows"] if r["team"] == n), None)
        pos = {"section": st["section"], "L": find(v["L"]["name"]), "R": find(v["R"]["name"])}
    starters = det.get("starters")
    com = plays.commentary(g)
    return jsonify({"points": insights.points(g, det), "vote": _vinfo(g, v),"key": v["key"], "kind": g["kind"], "table": v["table"], "L": v["L"]["name"], "R": v["R"]["name"],
                    "starters": starters, "goals": plays.goals(g), "forms": [f for f in forms if f["rows"]], "h2h": hsum, "pos": pos,
                    "plays": {"source": com["source"], "items": com["items"][:3]} if com and com.get("items") else None,
                    "url": f"/game/{v['key']}?d={d.isoformat()}"})


def _vinfo(g, v):
    return {"k": v["key"], "draw": g["kind"] == "football", "open": g["state"] == "scheduled" and datetime.now(data.SEOUL) < g["start"]}


@app.route("/api/featured")
def api_featured():
    d = parse_day(request.args.get("d"))
    games, _f = data.games_for(d)
    views = [view(g) for g in games]
    out, pending = insights.featured(games, views, d)
    out = [dict(x) for x in out]
    for x in out:
        x.pop("table", None); x.pop("lines", None)
        x["draw"] = x["kind"] == "football"
        x["vopen"] = x["state"] == "scheduled" and time.time() < x["ts"]
    return jsonify({"date": d.isoformat(), "today": d == today(), "pending": pending, "games": out})


@app.route("/api/votes")
def api_votes():
    return jsonify(insights.counts((request.args.get("k") or "").split(",")))


_voted, _vlock = {}, threading.Lock()


@app.route("/api/vote", methods=["POST"])
def api_vote():
    b = request.get_json(silent=True) or {}
    key, side = str(b.get("k") or "")[:80], b.get("s")
    g, d = _find(key) if key else (None, None)
    if not g or side not in ("L", "R", "D") or (side == "D" and g["kind"] != "football"):
        return jsonify({"ok": False, "error": "잘못된 요청이에요."}), 400
    if not _vinfo(g, view(g))["open"]:
        return jsonify({"ok": False, "error": "경기가 시작돼 응원 투표가 마감됐어요."}), 400
    ik = chat._ip() + "|" + key
    now = time.time()
    with _vlock:
        if len(_voted) > 100000:
            for k in [k for k, t in _voted.items() if now - t > 86400]:
                del _voted[k]
        if ik in _voted:
            return jsonify({"ok": False, "dup": True, "counts": insights.counts([key])[key]})
        _voted[ik] = now
    insights.add(key, side)
    return jsonify({"ok": True, "counts": insights.counts([key])[key]})


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


MANIFEST = {"name": "투윈스코어 TWOWIN", "short_name": "투윈스코어 TWOWIN", "id": "/", "start_url": "/?src=pwa", "scope": "/",
            "display": "standalone", "orientation": "portrait", "background_color": "#0b1630", "theme_color": "#0b1630", "lang": "ko",
            "description": "국내·해외 축구·야구·농구·배구·아이스하키 실시간 스코어",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/static/icons/maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
                      {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}

SW_JS = """// 투윈스코어 서비스워커: /static/ 정적 파일만 캐시. API·페이지는 절대 캐시하지 않음(항상 네트워크).
const C='tw-static-v1';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);
 if(e.request.method!=='GET'||u.origin!==location.origin||!u.pathname.startsWith('/static/')||u.pathname.endsWith('.mp3'))return;
 e.respondWith(caches.open(C).then(c=>c.match(e.request).then(r=>r||fetch(e.request).then(n=>{if(n.ok)c.put(e.request,n.clone());return n}))));});
"""


@app.route("/manifest.webmanifest")
def manifest():
    import json
    r = app.response_class(json.dumps(MANIFEST, ensure_ascii=False), mimetype="application/manifest+json")
    r.headers["Cache-Control"] = "public, max-age=3600"
    return r


@app.route("/sw.js")
def sw():
    r = app.response_class(SW_JS, mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    r.headers["Service-Worker-Allowed"] = "/"
    return r


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8088)), threaded=True, debug=False)

from datetime import datetime, timedelta
from flask import get_template_attribute, Flask, render_template, request, abort, jsonify, redirect
import data
import curation
import chat
import plays
import insights

import threading, time
from collections import deque

app = Flask(__name__)
import adminpath
adminpath.install(app)
app.config["MAX_CONTENT_LENGTH"] = 52 * 1024 * 1024  # 이미지 업로드(관리자)만 6MB, 나머지는 아래 _body_limit 에서 16KB
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
import admin_ext
app.register_blueprint(admin_ext.bp)
import vip
app.register_blueprint(vip.bp)
import activity
app.register_blueprint(activity.bp)
import adminstats
app.register_blueprint(adminstats.bp)
import deposit
app.register_blueprint(deposit.bp)
import logos
app.register_blueprint(logos.bp)
import news
app.register_blueprint(news.bp)
import music
app.register_blueprint(music.bp)
import admin_accts
app.register_blueprint(admin_accts.bp)
import social
app.register_blueprint(social.bp)
import feed
app.register_blueprint(feed.bp)
import plus
app.register_blueprint(plus.bp)
try:
    members.init_db()
    admin_ext.init_db()
    import levels; levels.init()
    vip.init_db()
    activity.init_db()
    music.init_db()
    deposit.init_db()
    social.init_db()
    feed.init_db()
    with app.app_context():
        try:
            admin_ext.rebuild_today()
        except Exception:
            logging.getLogger('app').exception('visit rebuild')
except Exception:
    logging.getLogger("app").exception("member DB init failed")

# ---------- 보안: IP별 요청 제한 ----------
# (경로 접두어, 1분 최대). 캐시에서 나가는 폴링은 같은 와이파이·통신사 공유 IP 를 고려해 넉넉히.
RATE = [("/admin/feed/img", 1200), ("/admin", 120), ("/api/preview/", 20), ("/api/vote", 60), ("/api/chat", 300), ("/api/games", 300), ("/api/top/", 300), ("/api/", 120), ("/game/", 60)]
_rl, _rl_lock = {}, threading.Lock()


@app.before_request
def _body_limit():
    n = request.content_length or 0
    lim = {"/admin/settings/hero": 6 * 1024 * 1024, "/admin/music/upload": 9 * 1024 * 1024, "/api/feed/post": 51 * 1024 * 1024}.get(request.path, 16 * 1024)
    if n > lim:
        abort(413)


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


# ---------- 에러 응답: 내부 정보(프레임워크·언어·파싱 위치·스택) 절대 노출 금지 ----------
from werkzeug.exceptions import HTTPException
_errlog = logging.getLogger("app.error")
_ERR_MSG = {400: "잘못된 요청입니다", 404: "페이지를 찾을 수 없어요", 405: "잘못된 요청입니다",
            413: "요청이 너무 커요", 415: "잘못된 요청입니다", 429: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요"}
_ERR_PAGE = ("<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width'>"
             "<title>투윈스코어</title><body style='font-family:sans-serif;text-align:center;padding:60px 16px'>"
             "<h2>{msg}</h2><p><a href='/'>홈으로</a></p></body></html>")


def _err_resp(code):
    msg = _ERR_MSG.get(code, "잘못된 요청입니다" if code < 500 else "일시적인 오류가 발생했어요")
    if request.path.startswith("/api/") or request.is_json or request.accept_mimetypes.best == "application/json":
        r = jsonify({"ok": False, "error": msg})
    else:
        r = app.response_class(_ERR_PAGE.format(msg=msg), mimetype="text/html")
    r.status_code = code
    if code == 405:
        r.headers.pop("Allow", None)
    return r


@app.errorhandler(HTTPException)
def _http_err(e):
    if e.code is None or e.code < 400:
        return e
    if e.code >= 500 or e.code in (400, 413, 415):
        _errlog.warning("%s %s %s: %s", e.code, request.method, request.path, e.description)
    return _err_resp(e.code)


@app.errorhandler(Exception)
def _any_err(e):
    _errlog.exception("unhandled %s %s", request.method, request.path)
    return _err_resp(500)
WD = "월화수목금토일"
EMO = {"baseball": "⚾", "basketball": "🏀", "volleyball": "🏐", "football": "⚽", "hockey": "🏒"}
SPORT_KO = {"football": "축구", "baseball": "야구", "basketball": "농구", "volleyball": "배구", "hockey": "아이스하키"}
# 홈 '전체' 리그 순서(한국 인기순). 여기만 바꾸면 PC·모바일 모두 반영. 목록에 없는 리그는 원래 순서대로 뒤에.
LEAGUE_POP = ["KBO", "EPL", "MLB", "NBA", "K리그1", "챔피언스리그", "라리가", "KBL", "V리그 남자", "V리그 여자", "NPB", "분데스리가",
              "세리에A", "리그1", "K리그2", "WKBL", "유로파리그", "컨퍼런스리그", "J1리그", "NHL", "챔피언십", "MLS", "사우디 리그"]
_POP_ALIAS = {"컴퍼런스리그": "컨퍼런스리그", "UEFA 컨퍼런스리그": "컨퍼런스리그", "UEFA 챔피언스리그": "챔피언스리그", "UEFA 유로파리그": "유로파리그",
              "V리그남자": "V리그 남자", "V리그여자": "V리그 여자", "사우디": "사우디 리그", "사우디 프로리그": "사우디 리그"}
_POP = {n: i for i, n in enumerate(LEAGUE_POP)}


def league_order(name, site_order):
    i = _POP.get(_POP_ALIAS.get(name, name))
    return i if i is not None else 1000 + (site_order or 0)


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


HALT_KO = {"INT": "경기 중단", "INTR": "경기 중단", "SUSP": "일시 중단", "PST": "연기", "POST": "연기",
           "ABD": "경기 취소(중도)", "CANC": "취소", "AWD": "몰수 판정", "WO": "부전승"}
_GENERIC_LONG = {"match interrupted", "interrupted", "match suspended", "suspended", "match postponed", "postponed",
                 "match abandoned", "abandoned", "match cancelled", "cancelled", "canceled", "technical loss",
                 "walkover", "awarded", "walk over"}


def halt_info(g):
    """중단/연기/취소 상태면 (한글 상태, 사유). 사유는 데이터에 실제로 있을 때만."""
    st = str(g.get("status") or "")
    reason = (g.get("halt_reason") or "").strip()
    label = HALT_KO.get(st)
    if not label and reason:
        label = "경기 중단" if "중단" in reason or "서스펜디드" in reason else ("취소" if "취소" in reason or "노게임" in reason else
                ("콜드게임" if "콜드" in reason else None))
    if not label:
        return None, None
    lg = (g.get("status_long") or "").strip()
    if not reason and lg and lg.lower() not in _GENERIC_LONG and lg.upper() != st:
        reason = lg[:40]
    if reason and reason.replace(" ", "") == label.replace(" ", ""):
        reason = ""
    return label, reason or None


def view(g):
    left_home = g["kind"] != "baseball"   # 야구: 원정 왼쪽/홈 오른쪽, 그 외: 홈 왼쪽
    h = {"name": g["home"], "en": g.get("home_en"), "score": g.get("home_score"), "tag": "홈", "logo": g.get("home_logo") if g.get("other") else logos.url(g.get("home_logo")), "id": g.get("home_id"), "kind": g["kind"]}
    a = {"name": g["away"], "en": g.get("away_en"), "score": g.get("away_score"), "tag": "원정", "logo": g.get("away_logo") if g.get("other") else logos.url(g.get("away_logo")), "id": g.get("away_id"), "kind": g["kind"]}
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
    halt, reason = halt_info(g)
    if halt:
        badge = halt + (f" · {reason}" if reason else "")
        if st != "live" and halt in ("경기 중단", "일시 중단"):
            halt = f"{halt} · {g['start'].strftime('%H:%M')} 경기"   # 오래 멈춘 경기: 시작 시각 표시
    lines = [(lab, hs, as_) if left_home else (lab, as_, hs) for lab, hs, as_ in g.get("lines") or []]
    sub = []
    if g.get("label") and "·" in g["label"]:
        sub.append(g["label"].split("·", 1)[1].strip())
    if g.get("if_necessary"):
        sub.append("필요 시 개최")
    return {"key": str(g["key"]), "kind": g["kind"], "league": SHORT.get(g["site_league"], g["site_league"]),
            "lorder": league_order(g["site_league"], g["site_order"]), "emoji": EMO[g["kind"]], "state": st, "badge": badge,
            "time": g["start"].strftime("%H:%M"), "ts": g["start"].timestamp(), "L": L, "R": R,
            "lines": lines, "sub": " · ".join(sub), "left_home": left_home, "sport": SPORT_KO[g["kind"]],
            "table": period_table(g), "halt": halt, "reason": reason}


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
    return jsonify(_games_payload(parse_day(request.args.get("d"))))


def _games_payload(d):
    games, failed = data.games_for(d)
    if d == today() and datetime.now(data.SEOUL).hour < 6:   # 자정 넘어 이어지는 전날 경기
        prev, f2 = data.games_for(d - timedelta(days=1))
        games = [g for g in prev if g["state"] == "live"] + games
        failed = sorted(set(failed + f2))
    games = games + _nx_main(d)
    lk = sorted({g["kind"] for g in games if g["state"] == "live"})
    upstream = min([data.live_ttl(k) for k in lk], default=None)
    return {"upstream": upstream, "date": d.isoformat(), "label": day_label(d), "failed": failed,
            "updated": datetime.now(data.SEOUL).strftime("%H:%M:%S"),
            "games": _cur([view(g) for g in games], games, d), "other_n": _other_n(d)}


def _nx_main(d):
    """오늘 화면: 내일 날짜지만 24시간 안에 시작하는 축구도 같이 (라이브스코어 기준)."""
    if d != today():
        return []
    try:
        gs, _ = data.games_for(d + timedelta(days=1))
        return curation.next_day_football(gs, datetime.now(data.SEOUL))
    except Exception:
        return []


def _nx_other(d):
    if d != today():
        return []
    try:
        return curation.next_day_football(data.others_for(d + timedelta(days=1), refresh=False), datetime.now(data.SEOUL))
    except Exception:
        return []


def _cur(views, games, d):
    """큐레이션: 숨길 경기에 hide=True (검색·즐겨찾기로는 보여요). 내일 경기는 시각에 '내일' 표시."""
    now, it = datetime.now(data.SEOUL), d == today()
    for v, g in zip(views, games):
        if curation.hidden(g, now, it):
            v["hide"] = True
        if g["start"].date() != d and g["start"].date() > d and v["state"] == "scheduled":
            v["badge"] = "내일 " + v["badge"]
    return views


def _other_n(d):
    try:
        os_ = data.others_for(d, refresh=False)
        if d == today() and datetime.now(data.SEOUL).hour < 6:
            os_ = [g for g in data.others_for(d - timedelta(days=1), refresh=False) if g["state"] == "live"] + os_
        os_ = os_ + _nx_other(d)
        now, it = datetime.now(data.SEOUL), d == today()
        n = {}
        for g in os_:
            if curation.hidden(g, now, it):
                continue
            n[g["kind"]] = n.get(g["kind"], 0) + 1
        return n
    except Exception:
        return {}


@app.route("/api/games/other")
def api_games_other():
    """기타 리그 — 펼칠 때만 불러요."""
    d = parse_day(request.args.get("d"))
    gs = data.others_for(d)
    if d == today() and datetime.now(data.SEOUL).hour < 6:
        gs = [g for g in data.others_for(d - timedelta(days=1), refresh=False) if g["state"] == "live"] + gs
    gs = gs + _nx_other(d)
    out = []
    for g in gs:
        try:
            out.append(_cur([view(g)], [g], d)[0])
        except Exception:
            pass
    r = jsonify({"games": out})
    r.headers["Cache-Control"] = "no-store"
    return r


@app.route("/")
def index():
    d = parse_day(request.args.get("d"))
    t = today()
    return render_template("index.html", page="home", d=d.isoformat(), label=day_label(d),
                           yday=(t - timedelta(days=1)).isoformat(), today=t.isoformat(),
                           tmr=(t + timedelta(days=1)).isoformat(),
                           dmin=(t - timedelta(days=14)).isoformat(), dmax=(t + timedelta(days=7)).isoformat(),
                           f=request.args.get("f", "all"), g0=_g0(d))


def _g0(d):
    """첫 화면용 경기 목록을 HTML 안에 넣어 API 왕복 없이 바로 그려요."""
    import concurrent.futures as cf
    global _g0pool
    if _g0pool is None:
        _g0pool = cf.ThreadPoolExecutor(2)
    fut = _g0pool.submit(_games_payload, d)
    try:
        return fut.result(timeout=float(os.environ.get("G0_TIMEOUT", "0.8")))   # 캐시가 비어 오래 걸리면 HTML 은 먼저 보내고 화면이 API 로 받아요
    except Exception:
        return None


_g0pool = None

import warmer
warmer.start(league_order)
import chatbot
chatbot.start(_POP_ALIAS)
chatbot.install(app)


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
    lh = v["left_home"]
    import concurrent.futures as cf
    global _gpool
    try:
        _gpool
    except NameError:
        _gpool = cf.ThreadPoolExecutor(8)
    fd, fs, fw, fc = _gpool.submit(data.detail, g), _gpool.submit(plus.summary, g), _gpool.submit(plus.winprob, g, lh), _gpool.submit(plays.commentary, g)   # 외부 조회를 동시에(첫 조회만 느림, 이후 캐시)
    det = fd.result()
    forms = [(v["L"]["name"], det["form_home"] if lh else det["form_away"]), (v["R"]["name"], det["form_away"] if lh else det["form_home"])]
    st = det.get("starters")
    bat = det.get("batters")
    return render_template("game.html", page="game", g=v, d=d.isoformat(), label=day_label(d), table=v["table"], com=(com := fc.result()), gl=plays.goals(g),
                           forms=[f for f in forms if f[1]], h2h=det["h2h"], starters=st, batters=bat,
                           injuries=det["injuries"], stand=det["standings"], kind=g["kind"],
                           names={g["home"], g["away"]}, gnews=news.related(g["kind"], [v["L"]["name"], v["R"]["name"], g["home"], g["away"]]), points=insights.points(g, det, dedupe=True), vote=_vinfo(g, v), seo=_game_seo(g, v), an=_analysis(g, v, det, forms),
                           wp=fw.result(), summ=fs.result(), top=_top(g, v, det, com))


def _top(g, v, det, com=None):
    try:
        import toppv
        t = toppv.build(g, v, det)
        t["pl"] = [x.get("t") for x in ((com or {}).get("items") or [])[:6] if x.get("t")]
        return t
    except Exception:
        app.logger.exception("toppv")
        return None


@app.route("/api/top/<path:key>")
def api_top(key):
    d = parse_day(request.args.get("d"))
    g = data.find_game(key, d) or (data.find_game(key, d - timedelta(days=1)) if d == today() else None)
    if not g:
        return jsonify({}), 404
    v = view(g)
    import toppv
    t = toppv.live(g, v) if g["state"] == "live" else {}
    try:
        cm = plays.commentary(g) or {}
    except Exception:
        cm = {}
    its = [x for x in (cm.get("items") or []) if x.get("t")]
    return jsonify({"ev": t.get("ev"), "period": t.get("period"), "L": v["L"]["score"], "R": v["R"]["score"], "pl": [x["t"] for x in its[:6]],
                    "pla": [{"t": x["t"], "h": 1 if x.get("hot") else 0} for x in its[:80]], "src": cm.get("source") or "",
                    "vs": get_template_attribute("_top.html", "vsets")(v["lines"], g["state"] == "live", v["L"]["name"], v["R"]["name"]) if g["kind"] == "volleyball" else None})


def _analysis(g, v, det, forms):
    """경기정보 분석 섹션용 요약(실제 데이터만, 없으면 None). 기본 승패 배당은 응원 블록에만 표시."""
    lh = v["left_home"]
    out = {"odds": None, "snap": None, "h2h": None}
    try:
        import teamodds
        o = teamodds.odds(g)
    except Exception:
        o = None
    if o:
        L, R = (o["H"], o["A"]) if lh else (o["A"], o["H"])
        ps = [1 / L, 1 / o["D"] if o.get("D") else 0, 1 / R]
        t = sum(ps)
        pct = [round(p / t * 100) for p in ps]
        x = o.get("x") or {}
        hc = None
        if x.get("hc"):
            h = x["hc"]; ln = h["ln"]
            hc = {"l": ln if lh else -ln, "lo": h["a"] if lh else h["b"], "ro": h["b"] if lh else h["a"]}
        out["odds"] = {"book": o.get("book"), "final": o.get("final"), "pct": pct, "draw": bool(o.get("D")), "hc": hc, "ou": x.get("ou")}
    st = det.get("standings") or {}
    rows = {r.get("team"): r for r in (st.get("rows") or [])}
    fm = dict(forms)
    def side(t, raw):
        r = rows.get(raw) or {}
        f = fm.get(t["name"]) or []
        d = {}
        if r.get("rank") is not None:
            d["rank"] = r["rank"]
        if r.get("win") is not None and r.get("lose") is not None:
            d["rec"] = f"{r['win']}승" + (f" {r['draw']}무" if g["kind"] == "football" and r.get("draw") is not None else "") + f" {r['lose']}패"
        if r.get("pts") is not None and g["kind"] in ("volleyball", "football", "hockey"):
            d["pts"] = int(r["pts"])
        if f:
            d["gf"] = round(sum(x["me"] for x in f) / len(f), 1)
            d["ga"] = round(sum(x["op"] for x in f) / len(f), 1)
        return d
    rawL, rawR = (g["home"], g["away"]) if lh else (g["away"], g["home"])
    a, b = side(v["L"], rawL), side(v["R"], rawR)
    if a or b:
        out["snap"] = {"L": a, "R": b, "slug": st.get("slug"), "venue": g.get("venue")}
    hh = det.get("h2h") or []
    if hh:
        w = [0, 0, 0]
        for x in hh:
            try:
                hs, as_ = int(x["hs"]), int(x["as"])
            except (TypeError, ValueError, KeyError):
                continue
            hw = x.get("home") in (rawL, v["L"]["name"], v["L"].get("en"))
            if hs == as_:
                w[1] += 1
            elif (hs > as_) == hw:
                w[0] += 1
            else:
                w[2] += 1
        if sum(w):
            out["h2h"] = w
    return out


SPORT_KO = {"football": "축구", "baseball": "야구", "basketball": "농구", "volleyball": "배구", "hockey": "아이스하키"}
JL_SPORT = {"football": "Soccer", "baseball": "Baseball", "basketball": "Basketball", "volleyball": "Volleyball", "hockey": "Ice Hockey"}


def _game_seo(g, v):
    """경기 상세 SEO: 제목·설명·JSON-LD(SportsEvent). 사실만(점수·시간·리그)."""
    L, R = v["L"]["name"], v["R"]["name"]
    home, away = g["home"], g["away"]
    lg = g.get("site_league") or ""
    st = g.get("state")
    day = g["start"].strftime("%Y년 %-m월 %-d일 %H:%M")
    sc = f"{v['L']['score']}:{v['R']['score']}" if v["L"].get("score") is not None and v["R"].get("score") is not None else ""
    if st == "live":
        title = f"{L} vs {R} 실시간 스코어 {sc} ({lg}) | 투윈스코어"
    elif st == "final":
        title = f"{L} vs {R} 경기 결과 {sc} ({lg}) | 투윈스코어"
    else:
        title = f"{L} vs {R} 실시간 스코어 · {lg} {g['start'].strftime('%-m월 %-d일')} | 투윈스코어"
    desc = (f"{day} {lg} {L} vs {R} 경기 " + ("실시간 스코어 " + sc if st == "live" else ("최종 결과 " + sc if st == "final" else "실시간 스코어와 중계 정보")) +
            f". 최근 전적, 맞대결, 순위와 팬 응원 투표를 투윈스코어에서 확인하세요.")
    url = "https://twowinscore.com/game/" + str(g["key"])
    status = {"live": "https://schema.org/EventScheduled", "final": "https://schema.org/EventScheduled",
              "postponed": "https://schema.org/EventPostponed", "cancelled": "https://schema.org/EventCancelled"}.get(st, "https://schema.org/EventScheduled")
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{home} vs {away}", "url": url,
          "startDate": g["start"].isoformat(), "eventStatus": status, "sport": JL_SPORT.get(g["kind"], ""),
          "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
          "homeTeam": {"@type": "SportsTeam", "name": home}, "awayTeam": {"@type": "SportsTeam", "name": away},
          "competitor": [{"@type": "SportsTeam", "name": home}, {"@type": "SportsTeam", "name": away}],
          "superEvent": {"@type": "SportsEvent", "name": lg},
          "location": {"@type": "Place", "name": g.get("venue") or lg, "address": g.get("venue") or lg},
          "organizer": {"@type": "Organization", "name": lg}, "image": "https://twowinscore.com/static/og.jpg",
          "description": desc}
    bc = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "투윈스코어", "item": "https://twowinscore.com/"},
        {"@type": "ListItem", "position": 2, "name": f"{L} vs {R}", "item": url}]}
    return {"title": title, "desc": desc, "url": url, "ld": [ld, bc]}


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
                    "halt": v["halt"], "reason": v["reason"], "plays": {"source": com["source"], "items": com["items"][:3]} if com and com.get("items") else None,
                    "url": f"/game/{v['key']}?d={d.isoformat()}"})


def _vinfo(g, v):
    return {"k": v["key"], "lh": v["left_home"], "draw": g["kind"] == "football", "open": g["state"] == "scheduled" and datetime.now(data.SEOUL) < g["start"]}


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


@app.route("/api/odds")
def api_odds():
    import teamodds
    d = parse_day(request.args.get("d"))
    out, lite = {}, request.args.get("lite") == "1"
    from concurrent.futures import ThreadPoolExecutor

    def one(k):
        try:
            g = data.find_game(k, d) or (data.find_game(k, d - timedelta(days=1)) if d == today() else None)
            o = teamodds.odds(g, lite) if g else None
            if o and g:
                # 화면 좌·우(L/R)에 맞춘 배당. 야구=원정L/홈R, 그 외=홈L/원정R. 투표 L/R과 동일.
                lh = g["kind"] != "baseball"
                o = dict(o)
                o["L"], o["R"] = (o["H"], o["A"]) if lh else (o["A"], o["H"])
                mv = o.get("mv") or {}
                o["mv"] = {**mv, "L": mv.get("H") if lh else mv.get("A"), "R": mv.get("A") if lh else mv.get("H")}
                o["lh"] = lh
            return k, o
        except Exception:
            return k, None
    ks = [x[:80] for x in (request.args.get("k") or "").split(",") if x][:20]
    with ThreadPoolExecutor(6) as ex:   # 처음 조회만 API, 이후 캐시
        out = dict(ex.map(one, ks))
    r = jsonify(out)
    r.headers["Cache-Control"] = "public, max-age=60"
    return r


@app.route("/team/<kind>/<int:tid>")
def team_page(kind, tid):
    import teamodds
    if kind not in SPORT_KO:
        abort(404)
    t = teamodds.team(kind, tid)
    if not t:
        abort(404)
    sk = SPORT_KO[kind]
    lg = (t["next"] or t["past"] or [{}])[0].get("league") or ""
    seo = {"title": f"{t['name']} 경기 일정·결과·선수 명단 ({sk}) | 투윈스코어",
           "desc": f"{t['name']}{(' (' + t['en'] + ')') if t.get('en') else ''} {sk} {lg} 최근 경기 결과, 다가오는 경기 일정, 선수 명단(로스터)을 투윈스코어에서 확인하세요.",
           "url": f"https://twowinscore.com/team/{kind}/{tid}"}
    ld = {"@context": "https://schema.org", "@type": "SportsTeam", "name": t["name"], "sport": JL_SPORT.get(kind, ""), "url": seo["url"],
          **({"logo": t["logo"]} if t.get("logo") else {}), **({"alternateName": t["en"]} if t.get("en") else {})}
    import roster
    try:
        ro = roster.get(t)
    except Exception:
        ro = {"groups": [], "src": ""}
    seo["title"] = f"{t['name']} 선수 명단·시즌 기록 ({sk}) | 투윈스코어"
    seo["desc"] = f"{t['name']}{(' (' + t['en'] + ')') if t.get('en') else ''} {sk} {lg} 선수 명단(로스터)과 선수별 시즌 기록을 투윈스코어에서 확인하세요."
    thin = not ro["groups"]
    return render_template("team.html", page="team", t=t, ro=ro, sk=sk, seo=seo, ld=ld, thin=thin, emo=EMO.get(kind, ""))


@app.route("/api/lineup/<path:key>")
def api_lineup(key):
    import lineup
    d = parse_day(request.args.get("d"))
    g = data.find_game(key, d) or (data.find_game(key, d - timedelta(days=1)) if d == today() else None)
    if not g or g["kind"] not in ("baseball", "basketball"):
        return jsonify({"ok": False})
    st = data.state(g)
    lu = lineup.get(g) if g["kind"] == "baseball" else lineup.basketball(g)
    r = jsonify({"ok": bool(lu), "state": st, **(lu or {})})
    r.headers["Cache-Control"] = "public, max-age=20" if st == "live" else "public, max-age=120"
    return r


@app.route("/api/field/<path:key>")
def api_field(key):
    import lineup
    d = parse_day(request.args.get("d"))
    g = data.find_game(key, d) or (data.find_game(key, d - timedelta(days=1)) if d == today() else None)
    f = lineup.field(g) if g else None
    r = jsonify({"ok": bool(f), **(f or {})})
    r.headers["Cache-Control"] = "public, max-age=8" if f and f.get("live") else "public, max-age=300"
    return r


@app.route("/api/bso")
def api_bso():
    import lineup
    from concurrent.futures import ThreadPoolExecutor
    d = parse_day(request.args.get("d"))
    ks = [x[:80] for x in (request.args.get("k") or "").split(",") if x.startswith("baseball:")][:20]

    def one(k):
        try:
            g = data.find_game(k, d) or (data.find_game(k, d - timedelta(days=1)) if d == today() else None)
            return k, (lineup.bso_mini(g, lineup.bso(g)) if g else None)
        except Exception:
            return k, None
    with ThreadPoolExecutor(5) as ex:
        out = dict(ex.map(one, ks))
    r = jsonify(out)
    r.headers["Cache-Control"] = "public, max-age=10"
    return r


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
    res = {"ok": True, "counts": insights.counts([key])[key]}
    try:
        import levels
        mem = members.current()
        if mem:
            pr = levels.award(mem["id"], "cheer", "v:" + key[:60])
            if pr is not None:
                levels.mark_seen(mem["id"], pr); res["promo"] = levels.TIERS[pr][0]
    except Exception:
        pass
    return jsonify(res)


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
const C='tw-static-v13';
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
chat._cheer_db_init()

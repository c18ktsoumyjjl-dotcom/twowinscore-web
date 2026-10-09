"""투윈스코어 웹 데이터 계층. score-bot 코드를 읽기 전용으로 import 하고, 결과는 파일 캐시에 저장해 API 호출을 아낀다."""
import os, sys, json, time, threading
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import common as _common    # noqa: E402
_common.LOG_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "twowinscore-web.log")
import score_bot as sb      # noqa: E402  (읽기 전용 사용)
import features             # noqa: E402
import mlb_official         # noqa: E402

SEOUL = ZoneInfo("Asia/Seoul")
CACHE = os.environ.get("CACHE_DIR", "/tmp/twowinscore-cache")
os.makedirs(CACHE, exist_ok=True)
_lock = threading.Lock()

# 사이트에 보여줄 리그 (kind, league id, 표시 이름) - 순서 = 화면 순서
SITE_LEAGUES = [
    ("baseball", 5, "KBO"), ("baseball", 1, "MLB"), ("baseball", 2, "NPB"),
    ("basketball", 91, "KBL"), ("basketball", 92, "WKBL"),
    ("volleyball", 151, "V리그 남자"), ("volleyball", 152, "V리그 여자"),
    ("basketball", 12, "NBA"),
    ("football", 292, "K리그1"), ("football", 39, "EPL"), ("football", 140, "라리가"), ("football", 135, "세리에A"),
    ("football", 78, "분데스리가"), ("football", 61, "리그1"), ("football", 2, "챔피언스리그"),
    ("hockey", 57, "NHL"), ("hockey", 35, "KHL"),
]
import sports2
NEW_KINDS = ("football", "hockey")


def _islive(kind, st):
    return sports2.is_live(kind, st) if kind in NEW_KINDS else sb.LIVE[kind](st)

SITE_KEYS = {(k, l): (i, n) for i, (k, l, n) in enumerate(SITE_LEAGUES)}
STANDING_SLUGS = {"kbo": ("baseball", 5), "mlb": ("baseball", 1), "npb": ("baseball", 2),
                  "kbl": ("basketball", 91), "wkbl": ("basketball", 92),
                  "vm": ("volleyball", 151), "vw": ("volleyball", 152), "nba": ("basketball", 12),
                  "kl1": ("football", 292), "epl": ("football", 39), "laliga": ("football", 140), "seriea": ("football", 135),
                  "bundes": ("football", 78), "ligue1": ("football", 61), "ucl": ("football", 2),
                  "nhl": ("hockey", 57), "khl": ("hockey", 35)}

TTL_LIVE = 180       # 진행 중 경기가 있는 날: 3분
TTL_IDLE = 600       # 오늘이지만 진행 중 없음: 10분
TTL_PAST = 3 * 3600  # 지난 날짜
TTL_STAND = 30 * 60
TTL_FAIL = 120       # 실패 후 재시도 대기


def _rd(name):
    try:
        with open(os.path.join(CACHE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _wr(name, obj):
    p = os.path.join(CACHE, name)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str)
    os.replace(p + ".tmp", p)


def _ser(g):
    d = {k: v for k, v in g.items() if k in (
        "key", "id", "kind", "league", "start", "status", "home", "away", "home_score", "away_score",
        "period", "lines", "label", "home_logo", "away_logo", "if_necessary", "series_ko",
        "home_id", "away_id", "innings", "venue")}
    d["start"] = g["start"].isoformat()
    d["lines"] = [list(x) for x in g.get("lines") or []]
    return d


def _de(d):
    d = dict(d)
    d["start"] = datetime.fromisoformat(d["start"]).astimezone(SEOUL)
    return d


def _sport_day(kind, day, today):
    name = f"games_{kind}_{day.isoformat()}.json"
    c = _rd(name)
    now = time.time()
    if c:
        games = c.get("games") or []
        live = any(_islive(kind, g["status"]) for g in games)
        if not c.get("ok"):
            ttl = TTL_FAIL
        elif live:
            ttl = live_ttl(kind)
        elif day > today:
            ttl = 1800
        elif day < today - timedelta(days=1) or (day < today and all(g["status"] not in ("NS", "TBD") for g in games)):
            ttl = TTL_PAST
        elif _near(games):
            ttl = 60
        else:
            ttl = TTL_IDLE
        if now - c["ts"] < ttl:
            return [_de(g) for g in games], c.get("ok", False)
    try:
        games = _fetch_raw(kind, day)
        _wr(name, {"ts": now, "ok": True, "games": games})
        return [_de(g) for g in games], True
    except Exception:
        old = (c or {}).get("games") or []
        _wr(name, {"ts": now, "ok": False, "games": old})
        return [_de(g) for g in old], False


def _fetch_raw(kind, day):
    if kind in NEW_KINDS:
        return sports2.fetch_day(kind, day)
    """API-Sports 1회 호출. 봇의 parse_game 을 그대로 쓰고, 야구 이닝/안타/실책만 원본에서 덧붙인다."""
    raws = sb.api_get(sb.HOSTS[kind], {"date": day.isoformat(), "timezone": "Asia/Seoul"})
    out = []
    for raw in raws:
        lid = (raw.get("league") or {}).get("id")
        meta = sb.LEAGUE_BY_KEY.get((kind, lid))
        if not meta or (kind, lid) not in SITE_KEYS:
            continue
        g = sb.parse_game(raw, meta)
        if not g:
            continue
        if kind == "baseball":
            sc = raw.get("scores") or {}
            inn = {}
            for side in ("home", "away"):
                node = sc.get(side) or {}
                inn[side] = {"inn": {k: v for k, v in (node.get("innings") or {}).items() if v is not None},
                             "H": node.get("hits"), "E": node.get("errors")}
            g["innings"] = inn
        out.append(_ser(g))
    return out


def find_game(key, day):
    games, _ = games_for(day)
    for g in games:
        if str(g["key"]) == key:
            return g
    return None


def detail(g):
    """상세 자료(최근 5경기, 맞대결, 순위, 선발, 결장). 경기마다 파일 캐시. 확인된 것만."""
    name = "detail_" + str(g["key"]).replace(":", "_") + ".json"
    c = _rd(name)
    ttl = 30 * 60 if g["state"] != "scheduled" else 15 * 60
    if c and time.time() - c["ts"] < ttl:
        return c["d"]
    import starters, injuries
    from concurrent.futures import ThreadPoolExecutor
    kind, league = g["kind"], g["league"]
    now = datetime.now(SEOUL)
    out = {}
    def form(tid):
        if tid is None:
            return []
        gs = [x for x in features.team_league_games(kind, league, tid) if sb.is_finished(x) and x["start"] < g["start"]]
        gs.sort(key=lambda x: x["start"], reverse=True)
        rows = []
        for x in gs[:5]:
            if x.get("home_score") is None or x.get("away_score") is None:
                continue
            home = x.get("home_id") == tid
            me, op = (x["home_score"], x["away_score"]) if home else (x["away_score"], x["home_score"])
            rows.append({"date": x["start"].strftime("%m/%d"), "opp": x["away"] if home else x["home"],
                         "ha": "홈" if home else "원정", "me": me, "op": op,
                         "r": "W" if me > op else ("L" if me < op else "D")})
        return rows
    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None
    if kind in NEW_KINDS:
        out.update(form_home=[], form_away=[], h2h=[], starters=None, injuries=[])
    else:
      with ThreadPoolExecutor(max_workers=6) as ex:
        fh = ex.submit(safe, form, g.get("home_id"))
        fa = ex.submit(safe, form, g.get("away_id"))
        fh2 = ex.submit(safe, features.head_to_head, kind, g.get("home_id"), g.get("away_id"), g["start"])
        fst = ex.submit(safe, starters.game_starters, g) if kind == "baseball" else None
        fin = ex.submit(safe, injuries.game_unavailable, g) if (kind, league) in (("baseball", 1), ("basketball", 12)) else None
        out["form_home"], out["form_away"] = fh.result() or [], fa.result() or []
        out["h2h"] = [{"date": x["date"].strftime("%Y.%m.%d"), "home": x["home"], "away": x["away"], "hs": x["hs"], "as": x["aws"]}
                      for x in (fh2.result() or [])]
        out["starters"] = fst.result() if fst else None
        out["injuries"] = (fin.result() or []) if fin else []
    slug = next((s for s, v in STANDING_SLUGS.items() if v == (kind, league)), None)
    out["standings"] = None
    if slug:
        groups, season, ok = standings(slug)
        for sec, rows in groups:
            names = {g["home"], g["away"]}
            if any(r["team"] in names for r in rows):
                out["standings"] = {"slug": slug, "section": sec, "season": season, "rows": rows}
                break
    _wr(name, {"ts": time.time(), "d": out})
    return out


LIVE_FAST, LIVE_SLOW = 15, 60
_quota = {}


def quota(kind):
    """/status 는 할당량에 포함되지 않는다. 10분마다 확인. (사용량, 하루 한도)"""
    hit = _quota.get(kind)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    val = None
    try:
        import urllib.request
        req = urllib.request.Request((sports2.HOSTS.get(kind) or sb.HOSTS[kind]) + "/status", headers={"x-apisports-key": os.environ.get("API_SPORTS_KEY", "")})
        with urllib.request.urlopen(req, timeout=15) as r:
            rq = (json.loads(r.read().decode()).get("response") or {}).get("requests") or {}
        val = (int(rq.get("current") or 0), int(rq.get("limit_day") or 0))
    except Exception:
        val = None
    _quota[kind] = (time.time(), val)
    return val


def live_ttl(kind):
    """진행 중 경기: 기본 15초(종목당 하루 최대 5,760회). 사용량이 하루 한도의 60%를 넘거나 확인이 안 되면 60초."""
    q = quota(kind)
    if not q or not q[1] or q[0] > 0.6 * q[1]:
        return LIVE_SLOW
    return LIVE_FAST


def _near(games):
    n = datetime.now(SEOUL)
    for g in games:
        st = datetime.fromisoformat(g["start"])
        if g["status"] in ("NS", "TBD") and timedelta(minutes=-20) < st - n < timedelta(minutes=15):
            return True
    return False


def games_for(day):
    """해당 날짜(KST) 경기. (games, failed_kinds)"""
    today = datetime.now(SEOUL).date()
    out, failed = [], []
    with _lock:
        for kind in ("baseball", "basketball", "volleyball", "football", "hockey"):
            gs, ok = _sport_day(kind, day, today)
            if not ok:
                failed.append(kind)
            out.extend(g for g in gs if g["start"].date() == day)
    # MLB 공식 일정: 시리즈 이름 보강 + API-Sports 에 아직 없는 확정 예정 경기 추가
    if day >= today:
        try:
            now = datetime.now(SEOUL)
            horizon = datetime.combine(day + timedelta(days=1), datetime.min.time(), SEOUL)
            off = mlb_official.upcoming_games(now, horizon)
            out = [mlb_official.enrich(g, now, horizon) if g["kind"] == "baseball" and g["league"] == 1 else g for g in out]
            for o in off:
                if o["start"].date() == day and not any(g["kind"] == "baseball" and g["league"] == 1 and mlb_official.same_game(g, o) for g in out):
                    out.append(o)
        except Exception:
            pass
    for g in out:
        g["site_order"], g["site_league"] = SITE_KEYS[(g["kind"], g["league"])]
        g["state"] = state(g)
    out.sort(key=lambda g: (g["site_order"], g["start"], str(g["key"])))
    return out, failed


def state(g):
    if g["kind"] in NEW_KINDS:
        return sports2.state(g["kind"], g["status"])
    if sb.is_live(g):
        return "live"
    if sb.is_finished(g):
        return "final"
    if sb.is_cancelled(g):
        return "cancelled"
    if sb.is_postponed(g):
        return "postponed"
    if g["status"] in ("NS", "TBD"):
        return "scheduled"
    return "other"


def standings(slug):
    kind, league = STANDING_SLUGS[slug]
    name = f"stand_{slug}.json"
    c = _rd(name)
    now = time.time()
    if c and now - c["ts"] < (TTL_STAND if c.get("ok") else TTL_FAIL):
        return c["groups"], c.get("season", ""), c.get("ok")
    try:
        if kind in NEW_KINDS:
            data, label = sports2.standings(kind, league)
        else:
            with _lock:
                season, label = features.current_season(kind, league)
                groups = features.fetch_standings(kind, league, season)
            groups = features._played_groups(groups)
            data = [[sec, [{k: r.get(k) for k in ("rank", "team", "win", "lose", "pct", "pts", "played", "extra")} for r in rows]] for sec, rows in groups]
        _wr(name, {"ts": now, "ok": True, "groups": data, "season": label})
        return data, label, True
    except Exception:
        old = (c or {})
        _wr(name, {"ts": now, "ok": False, "groups": old.get("groups") or [], "season": old.get("season", "")})
        return old.get("groups") or [], old.get("season", ""), False

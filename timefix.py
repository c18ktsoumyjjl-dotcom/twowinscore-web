"""시작 시간 자동 보정 (모든 종목).

규칙: API-Sports 시작 시간이 네이버·ESPN과 30분 이상 다르고, 네이버와 ESPN이 같은 경기(양 팀 이름+날짜)로
맞춰져 서로 같은 시간(5분 이내)을 가리킬 때만 그 시간으로 바꾼다. 한 출처만 있으면 절대 바꾸지 않는다.
경기 목록을 새로 받을 때(배경)만 실행, 출처별 날짜 단위 30분 캐시·4초 타임아웃 → 요청/모바일 부담 없음.
"""
import difflib, json, re, threading, time, unicodedata, urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from common import log
except Exception:  # pragma: no cover
    def log(m):
        print(m)

SEOUL = ZoneInfo("Asia/Seoul")
TTL, FAIL_TTL, TIMEOUT = 1800, 300, 4
MIN_DIFF, AGREE = 30 * 60, 5 * 60
NH = {"User-Agent": "Mozilla/5.0 (twowinscore)", "Referer": "https://m.sports.naver.com/"}
NAVER_UP = {"football": ("wfootball", "kfootball"), "basketball": ("basketball", "kbasketball"),
            "baseball": ("kbaseball", "wbaseball"), "volleyball": ("volleyball", "kvolleyball"), "hockey": ()}
ESPN = {"football": ("soccer/all",), "basketball": ("basketball/nba", "basketball/wnba"),
        "baseball": ("baseball/mlb",), "hockey": ("hockey/nhl",), "volleyball": ()}
LOG = deque(maxlen=50)
_c, _lk = {}, threading.Lock()


def _j(url, h=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=h or {"User-Agent": "Mozilla/5.0"}), timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _cached(key, fn):
    with _lk:
        hit = _c.get(key)
        if hit and time.time() < hit[0]:
            return hit[1]
    try:
        v, exp = fn(), time.time() + TTL
    except Exception as e:
        log(f"timefix {key} 실패: {str(e)[:100]}"); v, exp = None, time.time() + FAIL_TTL
    with _lk:
        if len(_c) > 200:
            _c.clear()
        _c[key] = (exp, v)
    return v


def _naver(up, day):
    return _cached(("n", up, day), lambda: (_j(
        f"https://api-gw.sports.naver.com/schedule/games?fields=basic&upperCategoryId={up}&fromDate={day}&toDate={day}&size=500",
        NH).get("result") or {}).get("games") or [])


def _espn(slug, ymd):
    return _cached(("e", slug, ymd), lambda: _j(
        f"https://site.api.espn.com/apis/site/v2/sports/{slug}/scoreboard?dates={ymd}&limit=500").get("events") or [])


def _en(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|afc|club|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _ko(s):
    return re.sub(r"[\s·.\-]", "", str(s or "")).lower()


def _en_eq(a, names):
    a = _en(a)
    if len(a) < 3:
        return False
    for b in names:
        b = _en(b)
        if len(b) >= 3 and (a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a))
                            or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85):
            return True
    return False


def _tnames(c):
    t = c.get("team") or {}
    return [t.get(k) for k in ("displayName", "shortDisplayName", "name", "location", "abbreviation") if t.get(k)]


def _espn_time(kind, g, st):
    hits = set()
    he = g.get("home_en") or g.get("tf_he") or g.get("home")
    ae = g.get("away_en") or g.get("tf_ae") or g.get("away")
    u = st.astimezone(timezone.utc)
    for slug in ESPN.get(kind, ()):
        for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in (-12, 0, 12)}:
            for e in _espn(slug, d) or []:
                try:
                    cs = e["competitions"][0]["competitors"]
                    h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                    t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if abs((t - st).total_seconds()) > 12 * 3600:
                    continue
                hn, an = _tnames(h), _tnames(a)
                if (_en_eq(he, hn) and _en_eq(ae, an)) or (_en_eq(he, an) and _en_eq(ae, hn)):
                    hits.add((e.get("id"), t))
    return next(iter(hits))[1] if len(hits) == 1 else None


def _naver_time(kind, g, st):
    hk, ak, hits = _ko(g.get("home")), _ko(g.get("away")), set()
    for up in NAVER_UP.get(kind, ()):
        for day in {(st + timedelta(hours=dh)).astimezone(SEOUL).strftime("%Y-%m-%d") for dh in (-12, 0, 12)}:
            for x in _naver(up, day) or []:
                nh, na = _ko(x.get("homeTeamName")), _ko(x.get("awayTeamName"))
                if not nh or not na or not ({nh, na} & {hk, ak}):
                    continue      # 한 팀은 한글명이 정확히 같아야 함(같은 팀은 ±12시간에 한 경기뿐 → 아래 유일성으로 확정)
                try:
                    t = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
                except Exception:
                    continue
                if abs((t - st).total_seconds()) <= 12 * 3600:
                    hits.add((x.get("gameId"), t, {nh, na} == {hk, ak}))
    full = {h for h in hits if h[2]}
    hits = full or hits
    return next(iter(hits))[1] if len(hits) == 1 else None


def _fix_one(kind, g):
    s = g.get("start")
    st = datetime.fromisoformat(s) if isinstance(s, str) else s
    if st is None or st.tzinfo is None:
        return False
    et = _espn_time(kind, g, st)
    if not et or abs((et - st).total_seconds()) < MIN_DIFF:
        return False
    nt = _naver_time(kind, g, st)
    if not nt or abs((nt - et).total_seconds()) > AGREE:
        return False
    new = nt.astimezone(SEOUL)
    g["start"] = new.isoformat() if isinstance(s, str) else new
    g["start_api"] = st.isoformat()
    LOG.append((time.time(), g.get("key"), st.astimezone(SEOUL).strftime("%m-%d %H:%M"), new.strftime("%m-%d %H:%M")))
    log(f"timefix {g.get('key')} {st.astimezone(SEOUL):%H:%M} → {new:%H:%M} (네이버·ESPN 일치)")
    return True


def apply(kind, games):
    """games(직렬화 dict 또는 datetime start) 제자리 보정. 어떤 실패도 원본을 망가뜨리지 않음."""
    if not ESPN.get(kind) or not NAVER_UP.get(kind):
        return games
    for g in games:
        try:
            _fix_one(kind, g)
        except Exception as e:
            log(f"timefix {g.get('key')} 오류: {str(e)[:100]}")
    return games


def status():
    return {"fixed": [{"t": t, "key": k, "api": a, "fixed": b} for t, k, a, b in LOG]}

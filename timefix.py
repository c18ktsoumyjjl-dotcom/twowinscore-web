"""시작 시간 자동 보정 (모든 종목).

규칙: API-Sports 시작 시간이 네이버·ESPN과 30분 이상 다르고, 네이버와 ESPN이 같은 경기(양 팀 이름+날짜)로
맞춰져 서로 같은 시간(5분 이내)을 가리킬 때만 그 시간으로 바꾼다. 한 출처만 있으면 바꾸지 않는다.
예외(늦은 NS): API-Sports 시작 시각이 1시간 넘게 지났는데도 아직 NS/TBD(=그 시각에 안 열림)이고,
네이버에 있으면 ESPN과 같은 시각이며, ESPN이 같은 두 팀 경기를 ±36시간 안에 딱 하나 '예정'(STATUS_SCHEDULED)으로, 아직 안 온 시각에 갖고 있을
때만 ESPN 시각으로 바꾼다(ESPN 범위가 ±12시간이라 하루 밀린 경기는 기존 규칙으로 못 잡음) — 10/23 사우디 알아흘리–알칼리즈(API 10/23 03:00, ESPN·네이버 10/24 03:00)가 지난 시각
'예정'으로 남던 문제.
경기 목록을 새로 받을 때(배경)만 실행, 출처별 날짜 단위 30분 캐시·4초 타임아웃 → 요청/모바일 부담 없음.
"""
import difflib, functools, json, re, threading, time, unicodedata, urllib.request
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


_busy = set()


def _cached(key, fn):
    with _lk:
        hit = _c.get(key)
        if hit and time.time() < hit[0]:
            return hit[1]
        if hit:      # 만료(또는 직전 실패): 기존 값 즉시 반환 + 뒤에서 한 번만 갱신 (네이버·ESPN 타임아웃 때 요청이 기다리지 않게)
            if key not in _busy:
                _busy.add(key)
                def _r():
                    try:
                        _fetch(key, fn)
                    finally:
                        with _lk:
                            _busy.discard(key)
                threading.Thread(target=_r, daemon=True).start()
            return hit[1]
    return _fetch(key, fn)


def _fetch(key, fn):
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
    return _en_c(str(s or ""))


@functools.lru_cache(maxsize=50000)
def _en_c(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|afc|club|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _ko(s):
    return re.sub(r"[\s·.\-]", "", str(s or "")).lower()


@functools.lru_cache(maxsize=60000)
def _pair_eq(a, b):
    """정규화된 두 영문 이름이 같은 팀인지(결과 캐시 — 매 요청 ESPN 전 경기와 difflib 비교하던 CPU 부담 제거)."""
    if len(b) < 3:
        return False
    if a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a)):
        return True
    if 2.0 * min(len(a), len(b)) / (len(a) + len(b)) < 0.85:   # 길이 차이만으로 0.85 불가능(같은 결과, 빠르게)
        return False
    m = difflib.SequenceMatcher(None, a, b)
    return m.real_quick_ratio() >= 0.85 and m.quick_ratio() >= 0.85 and m.ratio() >= 0.85


def _en_eq(a, names):
    a = _en(a)
    if len(a) < 3:
        return False
    for b in names:
        if _pair_eq(a, _en(b)):
            return True
    return False


def _tnames(c):
    t = c.get("team") or {}
    return [t.get(k) for k in ("displayName", "shortDisplayName", "name", "location", "abbreviation") if t.get(k)]


def _espn_time(kind, g, st, win=12, sched_only=False):
    hits = set()
    he = g.get("home_en") or g.get("tf_he") or g.get("home")
    ae = g.get("away_en") or g.get("tf_ae") or g.get("away")
    u = st.astimezone(timezone.utc)
    for slug in ESPN.get(kind, ()):
        for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in range(-win, win + 1, 12)}:
            for e in _espn(slug, d) or []:
                try:
                    if sched_only and ((e.get("status") or {}).get("type") or {}).get("name") != "STATUS_SCHEDULED":
                        continue
                    cs = e["competitions"][0]["competitors"]
                    h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                    t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if abs((t - st).total_seconds()) > win * 3600:
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
    if _fix_late_ns(kind, g, s, st):
        return True
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


def _fix_late_ns(kind, g, s, st):
    now = datetime.now(timezone.utc)
    if g.get("status") not in ("NS", "TBD") or now - st < timedelta(hours=1):
        return False
    et = _espn_time(kind, g, st, win=36, sched_only=True)
    if not et or et <= now or abs((et - st).total_seconds()) < MIN_DIFF:
        return False
    n0, n1 = _naver_time(kind, g, st), _naver_time(kind, g, et)
    if (n0 and abs((n0 - et).total_seconds()) > AGREE) or (n1 and abs((n1 - et).total_seconds()) > AGREE):
        return False      # 네이버에 있으면 ESPN과 같은 시각일 때만
    new = et.astimezone(SEOUL)
    g["start"] = new.isoformat() if isinstance(s, str) else new
    g["start_api"] = st.isoformat()
    LOG.append((time.time(), g.get("key"), st.astimezone(SEOUL).strftime("%m-%d %H:%M"), new.strftime("%m-%d %H:%M")))
    log(f"timefix {g.get('key')} {st.astimezone(SEOUL):%m-%d %H:%M} → {new:%m-%d %H:%M} (API 시작 지난 NS·ESPN 예정)")
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

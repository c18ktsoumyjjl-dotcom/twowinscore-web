#!/usr/bin/env python3
"""KBO·NPB 실시간 점수: 네이버 스포츠를 먼저, API-Sports 는 보조.

API-Sports 는 KBO/NPB 점수를 몇 분~10분 넘게 늦게 올린다. parse_game 이 만든 경기(g)에
네이버 값(점수, 이닝 초/말, 이닝별 점수, R/H/E, 진행/종료/취소)을 덮어쓴다.
- 맞추기: 같은 날짜(KST) + 홈/원정 한글 팀명 + 시작 시간 ±6시간(가까운 경기).
- 캐시: 날짜 목록 12초, 진행 중 경기 상세 12초, 종료 경기 상세 1시간, 실패 30초(프로세스 공유).
- 네이버가 실패하거나 경기를 못 찾으면 g 를 그대로 둔다(API-Sports 값 유지).
"""
import json, re, threading, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from common import log
except Exception:                      # pragma: no cover
    def log(m):
        print(m)

SEOUL = ZoneInfo("Asia/Seoul")
H = {"User-Agent": "Mozilla/5.0 (twowinscore)", "Referer": "https://m.sports.naver.com/"}
LIVE_TTL, FINAL_TTL, FAIL_TTL = 12, 3600, 30
BASE = "https://api-gw.sports.naver.com/schedule/games"
CAT = {5: ("kbaseball", "kbo"), 2: ("wbaseball", "npb")}   # API-Sports league id -> 네이버

# API-Sports team id -> 네이버 팀명 후보
NAMES = {
    # KBO
    88: {"두산"}, 89: {"한화"}, 90: {"KIA"}, 91: {"KT"}, 92: {"키움"}, 93: {"LG"}, 94: {"롯데"},
    95: {"NC"}, 97: {"삼성"}, 647: {"SSG"},
    # NPB
    66: {"요미우리"}, 58: {"한신"}, 65: {"요코하마", "DeNA"}, 56: {"주니치"}, 59: {"히로시마"},
    64: {"야쿠르트"}, 57: {"소프트뱅크"}, 60: {"닛폰햄", "니혼햄"}, 61: {"오릭스"}, 62: {"라쿠텐"},
    63: {"세이부"}, 55: {"지바롯데", "치바롯데", "롯데"},
}

_cache, _lock = {}, threading.Lock()


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=8) as r:
        d = json.loads(r.read().decode())
    if not d.get("success", True) or "result" not in d:
        raise RuntimeError("naver fail")
    return d["result"]


def _cached(key, ttl_fn, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() < hit[0]:
            return hit[1]
        lk = _cache.setdefault("lk:" + key, (0, threading.Lock()))[1]
    with lk:
        with _lock:
            hit = _cache.get(key)
            if hit and time.time() < hit[0]:
                return hit[1]
        try:
            val = fn()
            exp = time.time() + ttl_fn(val)
        except Exception as e:
            log(f"naver {key} {str(e)[:120]}")
            val, exp = None, time.time() + FAIL_TTL
        with _lock:
            if len(_cache) > 1000:
                _cache.clear()
            _cache[key] = (exp, val)
        return val


def _day(league, day):
    up, cat = CAT[league]
    return _cached(f"day:{cat}:{day}", lambda v: LIVE_TTL, lambda: _get(
        f"{BASE}?fields=basic,schedule,baseball&upperCategoryId={up}&categoryId={cat}"
        f"&fromDate={day}&toDate={day}&size=50")["games"])


def _detail(gid, final):
    return _cached(f"g:{gid}", lambda v: FINAL_TTL if final else LIVE_TTL,
                   lambda: _get(f"{BASE}/{gid}")["game"])


def _find(g):
    league = g.get("league")
    hn, an = NAMES.get(g.get("home_id")), NAMES.get(g.get("away_id"))
    if g.get("kind") != "baseball" or league not in CAT or not hn or not an:
        return None, False
    st = g["start"].astimezone(SEOUL)
    games = _day(league, st.strftime("%Y-%m-%d")) or []
    best = None
    for x in games:
        h, a = x.get("homeTeamName"), x.get("awayTeamName")
        if h in hn and a in an:
            swap = False
        elif h in an and a in hn:
            swap = True
        else:
            continue
        try:
            t = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
        except (KeyError, ValueError):
            continue
        d = abs((t - st).total_seconds())
        if d <= 6 * 3600 and (best is None or d < best[0]):
            best = (d, x, swap)
    return (best[1], best[2]) if best else (None, False)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def apply(g):
    """g 를 네이버 값으로 덮어쓴다. 바꿨으면 True. 어떤 실패도 g 를 건드리지 않는다."""
    try:
        return _apply(g)
    except Exception as e:
        log(f"naver apply {g.get('key')} {str(e)[:120]}")
        return False


def _apply(g):
    x, swap = _find(g)
    if not x:
        return False
    code = x.get("statusCode")
    if x.get("cancel"):
        g.update(status="POST", period="취소", src="naver")
        return True
    if code not in ("STARTED", "RESULT"):
        return False                     # 경기 전·중단 등은 API-Sports 그대로
    final = code == "RESULT"
    d = _detail(x["gameId"], final) or x
    hs, as_ = _int(d.get("homeTeamScore")), _int(d.get("awayTeamScore"))
    if hs is None or as_ is None:
        return False
    hinn, ainn = d.get("homeTeamScoreByInning") or [], d.get("awayTeamScoreByInning") or []
    hr, ar = d.get("homeTeamRheb") or [], d.get("awayTeamRheb") or []
    if swap:
        hs, as_, hinn, ainn, hr, ar = as_, hs, ainn, hinn, ar, hr
    info = (d.get("currentInning") or d.get("statusInfo") or "").strip()
    if final:
        status, period = "FT", "종료"
    else:
        m = re.match(r"(\d+)회(초|말)?", info)
        if not m:
            return False
        status, period = f"IN{m.group(1)}", f"{m.group(1)}회{m.group(2) or ''}"
        if swap and m.group(2):          # 홈/원정이 뒤집힌 경우 초/말도 뒤집는다
            period = f"{m.group(1)}회{'말' if m.group(2) == '초' else '초'}"

    def side(inn, rheb):
        out = {str(i + 1): _int(v) for i, v in enumerate(inn) if _int(v) is not None}
        return {"inn": out, "H": _int(rheb[1]) if len(rheb) > 1 else None,
                "E": _int(rheb[2]) if len(rheb) > 2 else None}

    g.update(status=status, period=period, home_score=hs, away_score=as_, src="naver",
             innings={"home": side(hinn, hr), "away": side(ainn, ar)})
    return True

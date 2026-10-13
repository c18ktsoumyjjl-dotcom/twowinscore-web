"""국내 농구(KBL)·배구(V리그·KOVO컵) 실시간: 네이버 스포츠를 API-Sports 와 합친다.

안전장치
- 맞추기: 홈·원정 한글 팀명(사이트 검증된 ko_name)이 둘 다 같고 시작 시간 3시간 이내인 경기가 정확히 1개일 때만.
- 점수는 절대 뒤로 가지 않는다: 두 출처 중 더 진행된 상태(쿼터/세트 → 점수 합)를 쓰고, 이전에 보여준 것보다 뒤면 이전 값 유지.
- 종료: 두 출처가 모두 종료이거나, 네이버가 종료이고 양 팀 점수가 API-Sports 이상일 때만.
- 네이버 실패·형식 변경 → API-Sports 그대로 + 로그. 진행 중(또는 시작 시각이 지난 경기 전) 국내 경기만, 5초 캐시·4초 타임아웃.
"""
import json, re, threading, time, urllib.request
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from common import log
except Exception:  # pragma: no cover
    def log(m):
        print(m)

SEOUL = ZoneInfo("Asia/Seoul")
H = {"User-Agent": "Mozilla/5.0 (twowinscore)", "Referer": "https://m.sports.naver.com/"}
BASE = "https://api-gw.sports.naver.com/schedule/games"
TTL, FAIL_TTL, TIMEOUT = 5, 20, 4
LEAGUES = {("basketball", 91): "kbasketball", ("volleyball", 151): "kvolleyball",
           ("volleyball", 152): "kvolleyball", ("volleyball", 153): "kvolleyball"}
CATS = {("basketball", 91): {"kbl"}, ("volleyball", 151): {"kovo"}, ("volleyball", 152): {"wkovo"}}  # 153(컵): 이름+시간으로만
BB_ST = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}

_cache, _lock = {}, threading.Lock()
_shown = {}          # key -> (rank, snapshot) 이미 보여준 가장 진행된 상태
STATS = {"ok": 0, "fail": 0, "last_ok": None, "last_fail": None, "applied": 0, "kept_api": 0}
MISMATCH = deque(maxlen=50)
_last_mm = {}


def _nm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode())
    if not d.get("success", True) or "result" not in d:
        raise RuntimeError("naver fail")
    return d["result"]


def _cached(key, fn):
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
            val, exp = fn(), time.time() + TTL
            STATS["ok"] += 1; STATS["last_ok"] = time.time()
        except Exception as e:
            log(f"naver_kr {key} 실패 → API-Sports 사용: {str(e)[:120]}")
            STATS["fail"] += 1; STATS["last_fail"] = (time.time(), str(e)[:120])
            val, exp = None, time.time() + FAIL_TTL
        with _lock:
            if len(_cache) > 500:
                _cache.clear()
            _cache[key] = (exp, val)
        return val


def _day(up, day):
    r = _cached(f"d:{up}:{day}", lambda: _get(f"{BASE}?fields=basic,schedule,basketball,volleyball&upperCategoryId={up}"
                                               f"&fromDate={day}&toDate={day}&size=50"))
    return (r or {}).get("games") or []


def _find(g):
    up = LEAGUES.get((g.get("kind"), g.get("league")))
    if not up:
        return None, False
    st = g["start"].astimezone(SEOUL)
    h, a, hits = _nm(g.get("home")), _nm(g.get("away")), []
    cats = CATS.get((g["kind"], g["league"]))
    for x in _day(up, st.strftime("%Y-%m-%d")):
        if cats and x.get("categoryId") not in cats:
            continue
        nh, na = _nm(x.get("homeTeamName")), _nm(x.get("awayTeamName"))
        if (nh, na) == (h, a):
            swap = False
        elif (nh, na) == (a, h):
            swap = True
        else:
            continue
        try:
            t = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
        except (KeyError, ValueError, TypeError):
            continue
        if abs((t - st).total_seconds()) <= 3 * 3600:
            hits.append((x, swap))
    return hits[0] if len(hits) == 1 else (None, False)   # 불확실하면 네이버 무시


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse(g, x, swap):
    """네이버 경기 → 사이트 형식 dict. 모르는 형식이면 None."""
    code = x.get("statusCode")
    if code not in ("STARTED", "RESULT"):
        return None
    d = (_cached(f"g:{x['gameId']}", lambda: _get(f"{BASE}/{x['gameId']}")) or {}).get("game")
    if not d or d.get("statusCode") not in ("STARTED", "RESULT"):
        raise ValueError("detail unavailable")
    x, code = d, d.get("statusCode")
    fin = code == "RESULT"
    hs, as_ = _i(x.get("homeTeamScore")), _i(x.get("awayTeamScore"))
    if hs is None or as_ is None:
        raise ValueError("score format")
    if g["kind"] == "basketball":
        hq = [_i(v) for v in x.get("homeTeamScoreByQuarter") or []]
        aq = [_i(v) for v in x.get("awayTeamScoreByQuarter") or []]
        labs = ["1Q", "2Q", "3Q", "4Q", "OT"]
        if swap:
            hq, aq = aq, hq
        lines = [[labs[i], hq[i], aq[i]] for i in range(min(len(hq), len(aq), 5)) if hq[i] is not None and aq[i] is not None]
        info = str(x.get("currentQuarter") or x.get("statusInfo") or "")
        if fin:
            status, period, ph = "FT", "종료", 9
        elif "하프" in info:
            status, period, ph = "HT", "하프타임", 2.5
        elif "연장" in info or "OT" in info.upper():
            status, period, ph = "OT", "연장", 5
        else:
            m = re.search(r"([1-4])\s*(쿼터|Q)", info, re.I)
            if not m:
                raise ValueError(f"quarter format {info[:20]!r}")
            n = int(m.group(1))
            status, period, ph = BB_ST[n], f"{n}Q", n
        if sum(l[1] for l in lines) != (as_ if swap else hs) and lines:
            pass   # 쿼터 합 불일치는 표만 그대로(점수는 총점 기준)
        tot = (as_, hs) if swap else (hs, as_)
        return {"status": status, "period": period, "home_score": tot[0], "away_score": tot[1], "lines": lines,
                "rank": (1 if fin else 0, ph, tot[0] + tot[1])}
    # 배구: 점수 = 세트 승수
    cur = _i(x.get("currentSet")) or 0
    sets = []
    for s in x.get("currentScoreBySet") or []:
        n, sh, sa = _i(s.get("set")), _i(s.get("homeScore")), _i(s.get("awayScore"))
        if n is None or sh is None or sa is None:
            raise ValueError("set format")
        if n <= cur and (sh or sa or n == cur):
            sets.append([f"{n}세트", sa if swap else sh, sh if swap else sa])
    if not fin and cur < 1:
        raise ValueError("currentSet format")
    tot = (as_, hs) if swap else (hs, as_)
    return {"status": "FT" if fin else f"S{cur}", "period": "종료" if fin else f"{cur}세트",
            "home_score": tot[0], "away_score": tot[1], "lines": sets,
            "rank": (1 if fin else 0, cur, sum(l[1] + l[2] for l in sets))}


def _api_rank(g, fin_set):
    st, lines = g.get("status") or "", g.get("lines") or []
    fin = 1 if st in fin_set else 0
    if g["kind"] == "basketball":
        ph = {"Q1": 1, "BT": 1.5, "Q2": 2, "HT": 2.5, "Q3": 3, "Q4": 4, "OT": 5}.get(st, 9 if fin else 0)
        pts = (g.get("home_score") or 0) + (g.get("away_score") or 0)
    else:
        m = re.fullmatch(r"S(\d)", st)
        ph = int(m.group(1)) if m else (9 if fin else 0)
        pts = sum((l[1] or 0) + (l[2] or 0) for l in lines)
    return (fin, ph, pts)


FIELDS = ("status", "period", "home_score", "away_score", "lines")


def merge(g, fin_set=frozenset({"FT", "AOT", "AWD", "WO", "AW"})):
    """g(API-Sports)에 네이버를 합친다. 어떤 실패도 g 를 망가뜨리지 않는다."""
    try:
        return _merge(g, fin_set)
    except Exception as e:
        log(f"naver_kr merge {g.get('key')} 형식 오류 → API-Sports 사용: {str(e)[:120]}")
        STATS["kept_api"] += 1
        return False


def _due(g, fin_set):
    if (g.get("kind"), g.get("league")) not in LEAGUES or g.get("status") in fin_set | {"CANC", "POST", "PST", "ABD"}:
        return False
    age = (datetime.now(SEOUL) - g["start"].astimezone(SEOUL)).total_seconds()
    return -120 <= age <= 4 * 3600      # 진행 중이거나 시작 시각이 지난 경기만


def _merge(g, fin_set):
    key = g.get("key")
    if not _due(g, fin_set):
        prev = _shown.get(key)          # 이미 네이버로 종료까지 보여줬다면 되돌리지 않음
        if prev and prev[0] > _api_rank(g, fin_set):
            g.update(prev[1]); return True
        return False
    x, swap = _find(g)
    api = {k: g.get(k) for k in FIELDS}
    ar = _api_rank(g, fin_set)
    best, br, src = api, ar, None
    if x:
        n = _parse(g, x, swap)
        if n:
            nr = n.pop("rank")
            if n["status"] == "FT" and ar[0] == 0:
                ah, aa = g.get("home_score") or 0, g.get("away_score") or 0
                if not (n["home_score"] >= ah and n["away_score"] >= aa):
                    n = None                 # 네이버 종료인데 점수가 API보다 적음 → 무시
                    MISMATCH.append((time.time(), key, "naver_final_lower", api, None))
            if n and nr >= ar:
                best, br, src = n, nr, "naver"
            if n and ar[0] == 0 and nr[0] == 0 and (n["home_score"], n["away_score"]) != (api["home_score"], api["away_score"]) \
                    and api["home_score"] is not None:
                dd = {"api": [api["home_score"], api["away_score"], api["status"]],
                      "naver": [n["home_score"], n["away_score"], n["status"]], "ahead": "naver" if nr > ar else "api"}
                if _last_mm.get(key) != dd:      # 같은 불일치는 한 번만
                    _last_mm[key] = dd
                    MISMATCH.append((time.time(), key, "score_diff", dd, None))
    prev = _shown.get(key)
    if prev and prev[0] > br:
        best, br = prev[1], prev[0]      # 뒤로 가지 않게
    _shown[key] = (br, dict(best))
    if len(_shown) > 300:
        for k in list(_shown)[:100]:
            _shown.pop(k, None)
    if best is api:
        return False
    g.update(best)
    if src:
        g["src"] = "naver"; STATS["applied"] += 1
    return True


def status():
    now = time.time()
    return {"stats": {**STATS, "last_ok_ago": round(now - STATS["last_ok"]) if STATS["last_ok"] else None},
            "mismatch": [{"ago": round(now - t), "key": k, "type": ty, "data": d} for t, k, ty, d, _ in list(MISMATCH)[-20:]]}

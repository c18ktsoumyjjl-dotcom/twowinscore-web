"""국내 농구(KBL)·배구(V리그·KOVO컵) 실시간: 네이버 스포츠를 API-Sports 와 합친다.

안전장치
- 맞추기: 홈·원정 한글 팀명(사이트 검증된 ko_name)이 둘 다 같고 시작 시간 3시간 이내인 경기가 정확히 1개일 때만.
- 점수는 절대 뒤로 가지 않는다: 두 출처 중 더 진행된 상태(쿼터/세트 → 점수 합)를 쓰고, 이전에 보여준 것보다 뒤면 이전 값 유지.
- 종료: 두 출처가 모두 종료이거나, 네이버가 종료이고 양 팀 점수가 API-Sports 이상일 때만.
- 네이버 실패·형식 변경 → API-Sports 그대로 + 로그. 진행 중(또는 시작 시각이 지난 경기 전) 국내 경기만, 5초 캐시·4초 타임아웃.
"""
import json, re, threading, time, urllib.request
from collections import deque
from datetime import datetime, timedelta
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
           ("volleyball", 152): "kvolleyball", ("volleyball", 153): "kvolleyball", ("volleyball", 154): "kvolleyball"}
CATS = {("basketball", 91): {"kbl"}, ("volleyball", 151): {"kovo"}, ("volleyball", 152): {"wkovo"}, ("volleyball", 154): {"kovo"}}  # 153(컵)·154(남자컵 kovo): 이름+시간으로만
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


STALE_MAX = 60      # 만료 후 이 시간(초) 안의 값은 바로 주고 뒤에서 갱신(요청이 네이버 응답을 기다리지 않게)
_busy = set()


def _store(key, fn):
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


def _cached(key, fn):
    with _lock:
        hit = _cache.get(key)
        now = time.time()
        if hit and now < hit[0]:
            return hit[1]
        if hit and (hit[1] is None or now - hit[0] < STALE_MAX):
            # 만료된 값(또는 직전 실패=None → API-Sports 사용): 즉시 반환 + 뒤에서 한 번만 새로 받기
            # (네이버가 타임아웃일 때 요청마다 4초씩 기다리던 문제 방지)
            if key not in _busy:
                _busy.add(key)
                def _r():
                    try:
                        _store(key, fn)
                    finally:
                        with _lock:
                            _busy.discard(key)
                threading.Thread(target=_r, daemon=True).start()
            return hit[1]
        lk = _cache.setdefault("lk:" + key, (0, threading.Lock()))[1]
    with lk:
        with _lock:
            hit = _cache.get(key)
            if hit and time.time() < hit[0]:
                return hit[1]
        return _store(key, fn)


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


# ── 네이버에만 있는 경기 추가(API-Sports 미등록 경기) ─────────────────────────────
# 같은 날짜·같은 두 팀 경기가 API-Sports 에 있으면 추가하지 않는다(API-Sports 우선).
# 팀이 아직 정해지지 않은 경기("준결승 A승")는 띄우지 않는다. 점수·상태는 네이버 실제 값만.
_PLACEHOLDER = re.compile(r"(준결승|결승|[A-Z]\s*[승패]|미정|TBD|\d위)")
_UP_KIND = {"kbasketball": "basketball", "kvolleyball": "volleyball"}
_LOGO = {"basketball": "basketball", "volleyball": "volley"}
EXTRA = {"added": 0, "last": []}


def _naver_league(kind, x):
    cat, rnd = x.get("categoryId"), str(x.get("roundCode") or "")
    cup = rnd.startswith("kovo_cup")
    if kind == "volleyball":
        return {"wkovo": 153 if cup else 152, "kovo": 154 if cup else 151}.get(cat)
    if kind == "basketball":
        return {"kbl": 91, "wkbl": 92}.get(cat)
    return None


def _team_id(kind, name, ko_map):
    ids = [i for i, n in (ko_map or {}).items() if _nm(n) == _nm(name)]
    return ids[0] if len(ids) == 1 else None


def _same(x, y):
    return bool(x and y) and (x == y or x in y or y in x)


def _seen(have, h, a):
    h, a = _nm(h), _nm(a)
    for p in have:
        p1, p2 = (list(p) * 2)[:2]
        if (_same(h, p1) and _same(a, p2)) or (_same(h, p2) and _same(a, p1)):
            return True
    return False


_SEMI_SLOT = re.compile(r"^준결승\s*([AB])\s*승$")


def _resolve_final(x, day):
    """컵 결승 "준결승 A승/B승" → 실제 준결승 승리팀. 네이버 같은 카테고리 컵 준결승(kovo_cup_sf)이
    최근 3일 안에 정확히 2경기, 둘 다 종료·승자 확정일 때만(시작 순서대로 A, B). 아니면 None(띄우지 않음)."""
    if not str(x.get("roundCode") or "").endswith("_fi"):
        return None
    h, a = str(x.get("homeTeamName") or "").strip(), str(x.get("awayTeamName") or "").strip()
    mh, ma = _SEMI_SLOT.match(h), _SEMI_SLOT.match(a)
    if not mh or not ma or {mh.group(1), ma.group(1)} != {"A", "B"}:
        return None
    pre = str(x.get("roundCode"))[:-3] + "_sf"
    sf = {}
    for back in (0, 1, 2, 3):
        d = (day - timedelta(days=back)).isoformat()
        for y in _day(x.get("upperCategoryId") or "kvolleyball", d):
            if y.get("categoryId") == x.get("categoryId") and y.get("roundCode") == pre:
                sf[y.get("gameId")] = y
    if len(sf) != 2:
        return None
    won = {}
    for slot, y in zip("AB", sorted(sf.values(), key=lambda y: (str(y.get("gameDateTime")), str(y.get("gameId"))))):
        if y.get("statusCode") != "RESULT" or y.get("winner") not in ("HOME", "AWAY"):
            return None
        w = str(y.get("homeTeamName" if y["winner"] == "HOME" else "awayTeamName") or "").strip()
        if not w or _PLACEHOLDER.search(w):
            return None
        won[slot] = w
    return won[mh.group(1)], won[ma.group(1)]


def extra_games(kind, day, games, ko_map=None, enabled=None):
    """네이버 일정에만 있는 국내 경기 → 사이트 형식 dict 목록. 실패하면 []."""
    try:
        return _extra(kind, day, games, ko_map, enabled)
    except Exception as e:
        log(f"naver_kr extra {kind} {day} 실패: {str(e)[:120]}")
        return []


def _extra(kind, day, games, ko_map, enabled):
    ups = [u for u, k in _UP_KIND.items() if k == kind]
    if not ups:
        return []
    have = set()
    for g in games:
        try:
            if g["start"].astimezone(SEOUL).date() == day:
                have.add(frozenset((_nm(g.get("home")), _nm(g.get("away")))))
        except Exception:
            pass
    out = []
    for up in ups:
        for x in _day(up, day.isoformat()):
            lg = _naver_league(kind, x)
            if lg is None or (enabled is not None and (kind, lg) not in enabled):
                continue
            h, a = str(x.get("homeTeamName") or "").strip(), str(x.get("awayTeamName") or "").strip()
            rf = _resolve_final(x, day) if (_PLACEHOLDER.search(h) or _PLACEHOLDER.search(a)) else None
            if rf:
                h, a = rf
            if not h or not a or _PLACEHOLDER.search(h) or _PLACEHOLDER.search(a):
                continue
            if _seen(have, h, a):
                continue                      # API-Sports 에 이미 있음 → API-Sports 사용
            try:
                st = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
            except (KeyError, ValueError, TypeError):
                continue
            if st.date() != day:
                continue
            code = x.get("statusCode")
            g = {"key": f"{kind}:{lg}:nv{x['gameId']}", "id": None, "kind": kind, "league": lg, "start": st,
                 "home": h, "away": a, "home_score": None, "away_score": None, "lines": [], "src": "naver",
                 "venue": x.get("stadium") or None}
            for sd, nm in (("home", h), ("away", a)):
                tid = _team_id(kind, nm, ko_map)
                g[sd + "_id"] = tid
                g[sd + "_logo"] = f"https://media.api-sports.io/{_LOGO[kind]}/teams/{tid}.png" if tid else None
            if x.get("cancel") or code in ("CANCEL", "CANCELED"):
                g.update(status="CANC", period="취소", status_long="Cancelled")
            elif code == "BEFORE":
                g.update(status="NS", period="Not Started", status_long="Not Started")
            elif code in ("STARTED", "RESULT"):
                try:
                    n = _parse(g, x, False)
                except Exception:
                    n = None
                if not n:
                    continue
                n.pop("rank", None)
                g.update(n)
                g["status_long"] = "Finished" if n["status"] == "FT" else "In Progress"
            else:
                continue                      # 모르는 상태는 띄우지 않음
            have.add(frozenset((_nm(h), _nm(a))))
            out.append(g)
    if out:
        EXTRA["added"] = len(out); EXTRA["last"] = [g["key"] for g in out][-10:]
    return out

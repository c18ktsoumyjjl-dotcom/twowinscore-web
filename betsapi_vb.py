"""BetsAPI 배구 보조 배당: API-Sports 에 배당이 없는 KOVO 경기만 채워요(표시 전용).

- 토큰: 환경변수 BETSAPI_TOKEN (로그·예외에 절대 안 넣음). 없으면 무동작.
- 호출: 빈 KOVO 경기가 36시간 안에 있을 때만 /v1/events/upcoming?sport_id=91&cc=kr 1회(20분 간격),
  맞는 이벤트마다 /v2/event/odds/summary 1회(같은 경기 20분 간격). 하루 DAILY_CAP 넘으면 중단.
- 팀 이름: API-Sports 팀 id → BetsAPI 이름 고정표(TEAM)만 사용. 표에 없거나, 홈/원정이 다르거나,
  시작 ±3시간 안에 맞는 이벤트가 없으면 건너뜀(틀린 배당보다 비워 둠).
- 같은 경기가 BetsAPI 에 중복 등록된 경우: 모든 중복 이벤트의 배당을 보고 북 우선순위로 하나만 골라요.
- 저장: teamodds 디스크 스냅샷(CACHE_DIR/odds)과 같은 형식 → 첫 화면 인라인 그대로.
"""
import os, json, time, threading, logging, urllib.request, urllib.parse
from datetime import datetime, timezone

import teamodds

log = logging.getLogger("betsapi_vb")
HOST = "https://api.betsapi.com"
LEAGUES = {151, 152, 153, 154}               # V리그 남·여, KOVO컵 여자·남자
TEAM = {   # API-Sports volleyball team id → BetsAPI 이름(정확히 일치할 때만)
    1178: "Gimcheon Hi-Pass (W)", 1179: "GS Caltex Seoul (W)", 1180: "Heungkuk Pink Spiders (W)",
    1181: "Hyundai Hillstate (W)", 1182: "IBK Altos (W)", 2162: "SOOP SOOPers VC (W)",
    3820: "Daejeon JungKwanJang (W)",
}
BOOK_PREF = ["1XBet", "Bet365", "Betsson", "Pinnacle"]
_e = lambda k, d: type(d)(os.environ.get(k, d))
DAILY_CAP = _e("BETSAPI_DAILY_CAP", 300)
GAP = _e("BETSAPI_GAP", 1200)
STATE = os.path.join(os.path.dirname(teamodds.SNAP_DIR), "betsapi_state.json")
SRC = "betsapi"
_lk = threading.Lock()


def _key():
    return os.environ.get("BETSAPI_TOKEN", "").strip()


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(s):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(s, f)
        os.replace(STATE + ".tmp", STATE)
    except Exception:
        pass


def _ok(s):
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if s.get("day") != d:
        s.update(day=d, used=0)
    return s["used"] < DAILY_CAP


def _get(s, path, **q):
    s["used"] = s.get("used", 0) + 1
    q["token"] = _key()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{HOST}{path}?{urllib.parse.urlencode(q)}",
                                    headers={"User-Agent": "twowinscore"}), timeout=12) as r:
            b = json.loads(r.read().decode())
        return b if b.get("success") == 1 else None
    except Exception as e:
        log.warning("betsapi %s 실패: %s", path, type(e).__name__)
        return None


def _f(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def _from_book(name, bk):
    od = (bk.get("odds") or {}).get("end") or {}
    m = od.get("91_1") or {}
    h, a = _f(m.get("home_od")), _f(m.get("away_od"))
    if not (h and a):
        return None
    x = {}
    try:
        hc = od.get("91_2") or {}
        if _f(hc.get("home_od")) and _f(hc.get("away_od")) and hc.get("handicap") not in (None, ""):
            x["hc"] = {"ln": float(hc["handicap"]), "a": _f(hc["home_od"]), "b": _f(hc["away_od"])}
        ou = od.get("91_3") or {}
        if _f(ou.get("over_od")) and _f(ou.get("under_od")) and ou.get("handicap") not in (None, ""):
            x["ou"] = {"ln": float(ou["handicap"]), "a": _f(ou["over_od"]), "b": _f(ou["under_od"])}
    except (TypeError, ValueError):
        pass
    upd = (bk.get("odds_update") or {}).get("91_1")
    return {"o": {"H": h, "A": a}, "bk": name.lower(), "name": name,
            "upd": datetime.fromtimestamp(int(upd), timezone.utc).isoformat() if upd else None,
            "x": x, "mv": {}, "at": datetime.now(teamodds.SEOUL).strftime("%H:%M"), "src": SRC}


def fill(games):
    if not _key():
        return 0
    with _lk:
        s = _load()
        if not _ok(s):
            return 0
        now = datetime.now(timezone.utc)
        gaps = []
        for g in games:
            if g.get("kind") != "volleyball" or g.get("league") not in LEAGUES or g.get("state") != "scheduled":
                continue
            if not g.get("id") or not g.get("start"):
                continue
            sv = teamodds.snap_get("volleyball", g["id"])
            if sv and sv.get("src") != SRC:          # API-Sports 배당 있으면 손대지 않음
                continue
            if not (0 < (g["start"].astimezone(timezone.utc) - now).total_seconds() < 36 * 3600):
                continue
            h, a = TEAM.get(g.get("home_id")), TEAM.get(g.get("away_id"))
            if h and a and h != a:
                gaps.append((g, h, a))
        if not gaps or time.time() - s.get("last_list", 0) < GAP:
            _save(s)
            return 0
        s["last_list"] = time.time()
        evs = []
        for page in (1, 2):
            b = _get(s, "/v1/events/upcoming", sport_id=91, cc="kr", page=page)
            if not b:
                break
            evs += b.get("results") or []
            pg = b.get("pager") or {}
            if page * int(pg.get("per_page") or 50) >= int(pg.get("total") or 0):
                break
        done = 0
        tried = s.setdefault("tried", {})
        for g, h, a in gaps:
            st = g["start"].astimezone(timezone.utc).timestamp()
            ms = [e for e in evs if (e.get("home") or {}).get("name") == h and (e.get("away") or {}).get("name") == a
                  and abs(int(e.get("time") or 0) - st) <= 3 * 3600]
            # 같은 상대가 반대 홈/원정으로 따로 등록돼 있으면 모호 → 건너뜀
            if not ms or any((e.get("home") or {}).get("name") == a and (e.get("away") or {}).get("name") == h
                             and abs(int(e.get("time") or 0) - st) <= 3 * 3600 for e in evs):
                continue
            best = None
            for e in ms:                              # 중복 이벤트 전부 보고 하나만
                if time.time() - tried.get(e["id"], 0) < GAP or not _ok(s):
                    continue
                tried[e["id"]] = time.time()
                b = _get(s, "/v2/event/odds/summary", event_id=e["id"])
                for name, bk in ((b or {}).get("results") or {}).items():
                    if (bk or {}).get("matching_dir") not in (1, None):
                        continue
                    r = _from_book(name, bk)
                    if r:
                        rk = BOOK_PREF.index(name) if name in BOOK_PREF else 99
                        sc = (rk, -len(r["x"]))
                        if best is None or sc < best[0]:
                            best = (sc, r)
            if not best:
                continue
            r = best[1]
            sv = teamodds.snap_get("volleyball", g["id"])
            if sv and sv.get("src") != SRC:
                continue
            if sv and sv.get("bk") == r["bk"]:
                mv = dict(sv.get("mv") or {})
                for k, v in r["o"].items():
                    pv = (sv.get("o") or {}).get(k)
                    if pv and abs(v - pv) >= 0.005:
                        mv[k] = 1 if v > pv else -1
                r["mv"] = mv
            teamodds._snap_put("volleyball", g["id"], r)
            done += 1
        cut = time.time() - 3 * 86400
        s["tried"] = {k: v for k, v in tried.items() if v > cut}
        _save(s)
        return done

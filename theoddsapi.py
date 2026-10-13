"""The Odds API(the-odds-api.com) 보조 배당: API-Sports 에 배당이 없는 KBO·NPB·MLB·NBA 경기만 채워요.

- 키: 환경변수 THE_ODDS_API_KEY (로그·예외 메시지에 절대 넣지 않음). 없으면 아무것도 안 함.
- 무료 500 크레딧/월 안에서: /events(무료)로 빈 경기가 실제로 있는지 먼저 보고, 있을 때만
  /odds(h2h 1개 × eu 1개 지역 = 1크레딧, 한 번에 그 리그 전 경기)를 불러요.
  하루 최대 DAILY_CAP, 리그별 최소 간격 MIN_GAP, 월 사용량 MONTH_CAP 넘으면 중단.
  응답 헤더 x-requests-remaining 이 RESERVE 이하이면 그 달은 더 안 불러요.
- 저장: teamodds 의 디스크 스냅샷(data/odds/<kind>_<id>.json)과 같은 형식 → 첫 화면 인라인(peek)에 그대로 실림.
- 팀 이름: 우리(API-Sports) 영문명 → The Odds API 이름 후보 중 /participants 화이트리스트에 '정확히 하나'만 있을 때만 확정.
  확정 못 한 팀이 낀 경기, 홈/원정이 뒤집힌 경기, 시작 시각이 3시간 넘게 다른 경기, 후보가 2개 이상(더블헤더 모호)은 건너뜀.
"""
import os, json, time, threading, logging, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

import teamodds

log = logging.getLogger("theoddsapi")
HOST = "https://api.the-odds-api.com/v4"
SPORT = {("baseball", "KBO"): "baseball_kbo", ("baseball", "NPB"): "baseball_npb",
         ("baseball", "MLB"): "baseball_mlb", ("basketball", "NBA"): "basketball_nba"}
REGION = "eu"                 # 소수점 배당·유럽 북(Pinnacle 등). 지역 1개 = 1크레딧
BOOK_PREF = ["pinnacle", "betfair_ex_eu", "williamhill", "unibet_eu", "marathonbet", "onexbet", "betsson", "nordicbet"]
MONTH_CAP = 450               # 500 중 50은 여유
DAILY_CAP = 14                # 14 × 31 = 434
MIN_GAP = 4 * 3600            # 같은 리그 /odds 는 4시간에 한 번
RESERVE = 30
STATE = os.path.join(os.path.dirname(teamodds.SNAP_DIR), "theoddsapi_state.json")
_lk = threading.Lock()

# 우리 영문명(API-Sports) → The Odds API 이름 후보. 실제 확정은 /participants 목록과 대조해서만.
ALIAS = {
    "baseball_kbo": {
        "Doosan Bears": ["Doosan Bears"], "Hanwha Eagles": ["Hanwha Eagles"],
        "KIA Tigers": ["KIA Tigers", "Kia Tigers"], "KT Wiz Suwon": ["KT Wiz", "KT Wiz Suwon", "Kt Wiz"],
        "Kiwoom Heroes": ["Kiwoom Heroes"], "LG Twins": ["LG Twins"], "Lotte Giants": ["Lotte Giants"],
        "NC Dinos": ["NC Dinos"], "SSG Landers": ["SSG Landers"], "Samsung Lions": ["Samsung Lions"],
    },
    "baseball_npb": {
        "Chiba Lotte Marines": ["Chiba Lotte Marines"], "Chunichi Dragons": ["Chunichi Dragons"],
        "Fukuoka S. Hawks": ["Fukuoka SoftBank Hawks", "Fukuoka Softbank Hawks"],
        "Hanshin Tigers": ["Hanshin Tigers"], "Hiroshima Carp": ["Hiroshima Toyo Carp", "Hiroshima Carp"],
        "Nippon Ham Fighters": ["Hokkaido Nippon-Ham Fighters", "Nippon-Ham Fighters", "Nippon Ham Fighters"],
        "Orix Buffaloes": ["Orix Buffaloes"],
        "Rakuten Gold. Eagles": ["Tohoku Rakuten Golden Eagles", "Rakuten Golden Eagles"],
        "Seibu Lions": ["Saitama Seibu Lions", "Seibu Lions"],
        "Yakult Swallows": ["Tokyo Yakult Swallows", "Yakult Swallows"],
        "Yokohama BayStars": ["Yokohama DeNA BayStars", "Yokohama BayStars"],
        "Yomiuri Giants": ["Yomiuri Giants"],
    },
    "baseball_mlb": {"St.Louis Cardinals": ["St. Louis Cardinals"],
                     "Athletics": ["Athletics", "Oakland Athletics"]},
    "basketball_nba": {"Los Angeles Clippers": ["Los Angeles Clippers", "LA Clippers"]},
}


def _key():
    return os.environ.get("THE_ODDS_API_KEY", "").strip()


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
            json.dump(s, f, ensure_ascii=False)
        os.replace(STATE + ".tmp", STATE)
    except Exception:
        pass


def _get(path, params, s=None):
    """(json, cost). 실패 시 (None, 0). 키가 들어간 URL 은 로그/예외로 내보내지 않아요."""
    q = dict(params, apiKey=_key())
    url = f"{HOST}{path}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "twowinscore"}), timeout=12) as r:
            body = json.loads(r.read().decode())
            h = r.headers
    except Exception as e:
        log.warning("theoddsapi %s 실패: %s", path, type(e).__name__)   # 메시지에 URL(키) 포함될 수 있어 타입만
        return None, 0
    try:
        if s is not None:
                s["remaining"] = int(float(h.get("x-requests-remaining")))
    except (TypeError, ValueError):
        pass
    cost = int(float(h.get("x-requests-last") or 0))
    return body, cost


def _month_day():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m"), n.strftime("%Y-%m-%d")


def _budget_ok(s):
    m, d = _month_day()
    if s.get("month") != m:
        s.update(month=m, used=0)
    if s.get("day") != d:
        s.update(day=d, dused=0)
    if s.get("remaining") is not None and s["remaining"] <= RESERVE and s.get("rem_month") == m:
        return False
    return s["used"] < MONTH_CAP and s["dused"] < DAILY_CAP


def _charge(s, cost):
    m, _ = _month_day()
    s["used"] = s.get("used", 0) + cost
    s["dused"] = s.get("dused", 0) + cost
    s["rem_month"] = m


def _participants(sport, s):
    """화이트리스트(1크레딧, 30일 캐시)."""
    pc = s.setdefault("participants", {})
    e = pc.get(sport)
    if e and time.time() - e["t"] < 30 * 86400:
        return set(e["names"])
    if not _budget_ok(s):
        return set(e["names"]) if e else None
    body, cost = _get(f"/sports/{sport}/participants", {}, s)
    _charge(s, cost)
    if not isinstance(body, list):
        return set(e["names"]) if e else None
    names = sorted({x.get("full_name") for x in body if x.get("full_name")})
    pc[sport] = {"t": time.time(), "names": names}
    return set(names)


def _map(sport, ours, wl):
    """확정된 The Odds API 이름 또는 None."""
    if not ours or not wl:
        return None
    cands = ALIAS.get(sport, {}).get(ours) or [ours]
    low = {n.lower(): n for n in wl}
    hit = {low[c.lower()] for c in cands if c.lower() in low}
    return hit.pop() if len(hit) == 1 else None


def _match(g, evs, home, away):
    """홈·원정 정확히 같고 시작 ±3시간 안의 이벤트가 정확히 1개일 때만."""
    st = g["start"].astimezone(timezone.utc)
    hits = []
    for ev in evs or []:
        if ev.get("home_team") != home or ev.get("away_team") != away:
            continue
        try:
            ct = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if abs((ct - st).total_seconds()) <= 3 * 3600:
            hits.append(ev)
    return hits[0] if len(hits) == 1 else None


def _pick(ev, home, away):
    best = None
    for b in ev.get("bookmakers") or []:
        for mk in b.get("markets") or []:
            if mk.get("key") != "h2h":
                continue
            px = {o.get("name"): o.get("price") for o in mk.get("outcomes") or []}
            try:
                o = {"H": float(px[home]), "A": float(px[away])}
            except (KeyError, TypeError, ValueError):
                continue
            if "Draw" in px:          # 이 리그들은 2-way 만 표시
                continue
            r = BOOK_PREF.index(b["key"]) if b.get("key") in BOOK_PREF else 99
            if best is None or r < best[0]:
                best = (r, b, o, mk.get("last_update") or b.get("last_update"))
    if not best:
        return None
    _, b, o, upd = best
    return {"o": o, "bk": "toa_" + b.get("key", ""), "name": b.get("title") or b.get("key"), "upd": upd, "x": {},
            "mv": {}, "at": datetime.now(teamodds.SEOUL).strftime("%H:%M"), "src": "the-odds-api"}


def fill(games):
    """warmer 가 부르는 진입점. games: 오늘·내일 경기 dict 목록. 채운 경기 수 반환."""
    if not _key():
        return 0
    with _lk:
        s = _load()
        if not _budget_ok(s):
            return 0
        now = datetime.now(timezone.utc)
        gaps = {}
        for g in games:
            sp = SPORT.get((g.get("kind"), g.get("league")))
            if not sp or g.get("state") != "scheduled" or not g.get("id") or not g.get("start"):
                continue
            if teamodds.snap_get(g["kind"], g["id"]):      # API-Sports(또는 이전 채움)에 이미 있음
                continue
            if not (0 < (g["start"].astimezone(timezone.utc) - now).total_seconds() < 36 * 3600):
                continue
            gaps.setdefault(sp, []).append(g)
        done = 0
        for sp, gs in gaps.items():
            if time.time() - s.get("last", {}).get(sp, 0) < MIN_GAP or not _budget_ok(s):
                continue
            wl = _participants(sp, s)
            if not wl:
                continue
            want = []
            for g in gs:
                h, a = _map(sp, g.get("home_en"), wl), _map(sp, g.get("away_en"), wl)
                if h and a and h != a:
                    want.append((g, h, a))
                else:
                    log.info("theoddsapi: 이름 확정 불가로 건너뜀 %s %s vs %s", sp, g.get("home_en"), g.get("away_en"))
            if not want:
                continue
            evs, _ = _get(f"/sports/{sp}/events", {})          # 무료
            pairs = [(g, h, a, _match(g, evs, h, a)) for g, h, a in want]
            ids = sorted({ev["id"] for *_, ev in pairs if ev})
            if not ids or not _budget_ok(s):
                continue
            body, cost = _get(f"/sports/{sp}/odds", {"regions": REGION, "markets": "h2h", "oddsFormat": "decimal",
                                                      "eventIds": ",".join(ids)}, s)
            _charge(s, cost)
            s.setdefault("last", {})[sp] = time.time()
            by = {e.get("id"): e for e in body or []} if isinstance(body, list) else {}
            for g, h, a, ev in pairs:
                e = by.get(ev["id"]) if ev else None
                if not e or e.get("home_team") != h or e.get("away_team") != a:
                    continue
                r = _pick(e, h, a)
                if r and not teamodds.snap_get(g["kind"], g["id"]):
                    teamodds._snap_put(g["kind"], g["id"], r)
                    done += 1
        _save(s)
        return done

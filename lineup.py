"""야구 라인업/박스스코어 (실제 데이터만). KBO=네이버 스포츠, MLB=statsapi. 그 외=None."""
import json, time, threading, urllib.request
import data  # noqa: F401 (vendor 경로)
import starters as S

UA = {"User-Agent": "Mozilla/5.0 (twowinscore)"}
NAVER_H = {**UA, "Referer": "https://m.sports.naver.com/"}
_c, _lk = {}, threading.Lock()


def _j(url, h=UA):
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=12) as r:
        return json.loads(r.read().decode())


def _cache(key, ttl, fn):
    now = time.time()
    with _lk:
        e = _c.get(key)
        if e and now < e[0]:
            return e[1]
    try:
        v = fn()
    except Exception:
        v, ttl = (e[1] if e else None), 20
    with _lk:
        if len(_c) > 500:
            _c.clear()
        _c[key] = (now + ttl, v)
    return v


def _n(v):
    return v if isinstance(v, (int, float)) else (int(v) if isinstance(v, str) and v.isdigit() else None)


def _avg(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f"{f:.3f}".lstrip("0") if f < 1 else f"{f:.3f}"


# ---------- KBO ----------
KPOS = {"투": "투수", "포": "포수", "一": "1루수", "二": "2루수", "三": "3루수", "유": "유격수", "좌": "좌익수", "중": "중견수", "우": "우익수", "지": "지명", "타": "대타", "주": "대주자"}


def _kbo_side(rec, pv, side):
    bs = ((rec or {}).get("battersBoxscore") or {}).get(side) or []
    ps = ((rec or {}).get("pitchersBoxscore") or {}).get(side) or []
    bat, pit = [], []
    if bs:
        seen = set()
        for x in bs:
            o = x.get("batOrder")
            sub = o in seen
            seen.add(o)
            p = x.get("pos") or ""
            bat.append({"id": x.get("playerCode") or x.get("name"), "o": o, "sub": sub, "name": x.get("name"),
                        "pos": "-".join(KPOS.get(c, c) for c in p),
                        "avg": _avg(x.get("hra")), "ab": _n(x.get("ab")), "r": _n(x.get("run")), "h": _n(x.get("hit")),
                        "rbi": _n(x.get("rbi")), "bb": _n(x.get("bb")), "so": _n(x.get("kk")), "hr": _n(x.get("hr"))})
        for x in ps:
            pit.append({"id": x.get("pcode") or x.get("name"), "name": x.get("name"), "ip": (x.get("inn") or "").replace(".0", "") or None,
                        "h": _n(x.get("hit")), "r": _n(x.get("r")), "er": _n(x.get("er")), "bb": _n(x.get("bb")),
                        "so": _n(x.get("kk")), "np": _n(x.get("bf")), "era": x.get("era") or None, "dec": x.get("wls") or ""})
        return {"bat": bat, "pit": pit, "pre": False}
    lu = ((pv or {}).get(side + "TeamLineUp") or {}).get("fullLineUp") or []
    for x in lu:
        if x.get("batorder"):
            bat.append({"id": x.get("playerCode"), "o": x["batorder"], "sub": False, "name": x.get("playerName"), "pos": x.get("positionName") or "", "avg": None})
    bat.sort(key=lambda b: b["o"])
    return {"bat": bat, "pit": [], "pre": True}


def _kbo(g, live):
    st = S._kbo(g)
    if not st or not st.get("_gid"):
        return None
    gid, swap = st["_gid"], st.get("_swap")
    ttl = 25 if live else 300
    rec = _cache(("kr", gid), ttl, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/record", NAVER_H).get("result") or {}).get("recordData"))
    pv = None
    if not (((rec or {}).get("battersBoxscore") or {}).get("away")):
        pv = _cache(("kp", gid), 120, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/preview", NAVER_H).get("result") or {}).get("previewData"))
    a, h = _kbo_side(rec, pv, "away"), _kbo_side(rec, pv, "home")
    if swap:
        a, h = h, a
    if a["pre"] and h["pre"] and pv:   # 발표 라인업에 시즌 타율 붙이기 (네이버 시즌 기록)
        try:
            import roster
            for side_, tid in ((a, g.get("away_id")), (h, g.get("home_id"))):
                code = roster.KBO.get(tid)
                if not code:
                    continue
                yr = g["start"].year
                hs = _cache(("kh", code, yr), 3600, lambda: (_j(f"https://api-gw.sports.naver.com/statistics/categories/kbo/seasons/{yr}/players?teamCode={code}&playerType=HITTER&pageSize=100", NAVER_H).get("result") or {}).get("seasonPlayerStats") or [])
                m = {x.get("playerId"): x.get("hitterHra") for x in hs or []}
                for b in side_["bat"]:
                    b["avg"] = _avg(m.get(b["id"]))
        except Exception:
            pass
    return {"src": "네이버 스포츠", "away": a, "home": h}


# ---------- MLB ----------
MPOS = {"P": "투수", "C": "포수", "1B": "1루수", "2B": "2루수", "3B": "3루수", "SS": "유격수", "LF": "좌익수", "CF": "중견수", "RF": "우익수", "DH": "지명", "PH": "대타", "PR": "대주자"}


def _mlb_side(t):
    pl = t.get("players") or {}
    bat, pit = [], []
    for pid in t.get("batters") or []:
        p = pl.get(f"ID{pid}") or {}
        bo = str(p.get("battingOrder") or "")
        if not bo:
            continue
        b = (p.get("stats") or {}).get("batting") or {}
        bat.append({"id": pid, "o": int(bo[0]), "sub": bo[1:] != "00", "_k": int(bo), "name": (p.get("person") or {}).get("fullName"),
                    "pos": "-".join(MPOS.get(x.get("abbreviation"), x.get("abbreviation")) for x in p.get("allPositions") or [p.get("position") or {}]),
                    "avg": ((p.get("seasonStats") or {}).get("batting") or {}).get("avg"),
                    **({"ab": b.get("atBats"), "r": b.get("runs"), "h": b.get("hits"), "rbi": b.get("rbi"), "bb": b.get("baseOnBalls"), "so": b.get("strikeOuts"), "hr": b.get("homeRuns")} if b else {})})
    bat.sort(key=lambda x: x.pop("_k"))
    for pid in t.get("pitchers") or []:
        p = pl.get(f"ID{pid}") or {}
        s = (p.get("stats") or {}).get("pitching") or {}
        if not s:
            continue
        pit.append({"id": pid, "name": (p.get("person") or {}).get("fullName"), "ip": s.get("inningsPitched"), "h": s.get("hits"), "r": s.get("runs"),
                    "er": s.get("earnedRuns"), "bb": s.get("baseOnBalls"), "so": s.get("strikeOuts"), "np": s.get("numberOfPitches") or s.get("pitchesThrown"),
                    "era": ((p.get("seasonStats") or {}).get("pitching") or {}).get("era"), "dec": s.get("note") or ""})
    return {"bat": bat, "pit": pit, "pre": not any("ab" in b for b in bat) and not pit}


def _mlb(g, live):
    st = S._mlb(g)
    pk = st and st.get("_pk")
    if not pk:
        return None
    bx = _cache(("mb", pk), 25 if live else 300, lambda: _j(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"))
    if not bx:
        return None
    t = bx.get("teams") or {}
    return {"src": "MLB 공식 기록", "away": _mlb_side(t.get("away") or {}), "home": _mlb_side(t.get("home") or {})}


def get(g):
    if g.get("kind") != "baseball":
        return None
    try:
        live = data.state(g) == "live"
    except Exception:
        live = False
    try:
        if g.get("league") == 5:
            return _kbo(g, live)
        if g.get("league") == 1:
            return _mlb(g, live)
    except Exception:
        return None
    return None

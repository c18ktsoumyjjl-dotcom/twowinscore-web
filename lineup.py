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
        if g.get("league") in (1, 2):
            r = None
            try:
                r = ov_lineup(g)
            except Exception:
                r = None
            return r or (_mlb(g, live) if g.get("league") == 1 else None)
    except Exception:
        return None
    return None


# ---------- 농구 ----------
def _nm(s):
    return (s or "").replace(" ", "").lower()


def _bk_naver(g, live):
    day = g["start"].strftime("%Y-%m-%d")
    games = _cache(("nbk", day), 120, lambda: (_j("https://api-gw.sports.naver.com/schedule/games?fields=basic&upperCategoryId=kbasketball"
                                                     f"&fromDate={day}&toDate={day}&size=100", NAVER_H).get("result") or {}).get("games") or [])
    h, a = _nm(g["home"]), _nm(g["away"])
    m, swap, hits = None, False, 0
    for x in games or []:
        nh, na = _nm(x.get("homeTeamName")), _nm(x.get("awayTeamName"))
        if not nh or not na:
            continue
        if (nh in h or h in nh) and (na in a or a in na):
            m, swap, hits = x, False, hits + 1
        elif (nh in a or a in nh) and (na in h or h in na):
            m, swap, hits = x, True, hits + 1
    if not m or hits != 1:   # 확실히 한 경기일 때만
        return None
    gid = m["gameId"]
    rd = _cache(("nbr", gid), 25 if live else 300, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/record", NAVER_H).get("result") or {}).get("recordData"))
    if not rd or not (rd.get("homePlayerStats") or rd.get("awayPlayerStats")):
        return None
    P = {"GD": "가드", "FD": "포워드", "CT": "센터", "C": "센터", "F": "포워드", "G": "가드"}
    def side(lst):
        out = []
        for x in lst or []:
            sec = x.get("playTimeSec") or 0
            out.append({"id": x.get("playerId") or x.get("playerName"), "name": x.get("playerName"), "no": x.get("backNum"), "pos": P.get(x.get("position"), x.get("position") or ""),
                        "st": bool(x.get("startFlag")), "min": x.get("playTimeStr") if sec else None, "_s": sec, "pts": x.get("scoreTot"), "reb": x.get("reboundTot"),
                        "ast": x.get("as"), "to": x.get("to"), "stl": x.get("st"), "blk": x.get("bs"), "tpm": x.get("threeP")})
        return out
    ho, aw = side(rd.get("homePlayerStats")), side(rd.get("awayPlayerStats"))
    if swap:
        ho, aw = aw, ho
    return {"src": "네이버 스포츠", "cols": ["min", "pts", "reb", "ast", "to", "stl", "blk", "tpm"], "home": ho, "away": aw}


def _bk_espn(g, live):
    """NBA: ESPN 박스스코어(정식 선발 표시·정확한 선수 이름). 팀 영문명+시작 ±3시간으로 정확히 한 경기일 때만."""
    import html as _h
    from datetime import datetime as _dt, timezone as _tz, timedelta as _tdl
    try:
        en = json.load(open(__import__("os").path.join(__import__("os").path.dirname(__file__), "team_en.json")))
    except Exception:
        return None
    he, ae = en.get(f"basketball:{g.get('home_id')}"), en.get(f"basketball:{g.get('away_id')}")
    if not he or not ae:
        return None
    st = g["start"].astimezone(_tz.utc)
    m, hits = None, 0
    for dd in {(st - _tdl(hours=12)).strftime("%Y%m%d"), st.strftime("%Y%m%d")}:
        evs = _cache(("esb", dd), 300, lambda dd=dd: _j(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={dd}").get("events") or [])
        for e in evs or []:
            cs = ((e.get("competitions") or [{}])[0]).get("competitors") or []
            side = {c.get("homeAway"): ((c.get("team") or {}).get("displayName")) for c in cs}
            try:
                t = _dt.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=_tz.utc)
            except Exception:
                continue
            if abs((t - st).total_seconds()) > 3 * 3600:
                continue
            if side.get("home") == he and side.get("away") == ae and (not m or m["id"] != e["id"]):
                m, hits = e, hits + 1
    if not m or hits != 1:
        return None
    sm = _cache(("esm", m["id"]), 25 if live else 600, lambda: _j(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={m['id']}"))
    out = {}
    P = {"G": "가드", "F": "포워드", "C": "센터", "PG": "가드", "SG": "가드", "SF": "포워드", "PF": "포워드"}
    for t in ((sm or {}).get("boxscore") or {}).get("players") or []:
        nm = (t.get("team") or {}).get("displayName")
        sd = "home" if nm == he else "away" if nm == ae else None
        if not sd:
            return None
        rows = []
        for sec in t.get("statistics") or []:
            keys = sec.get("keys") or []
            for a in sec.get("athletes") or []:
                v = dict(zip(keys, a.get("stats") or []))
                ath = a.get("athlete") or {}
                n = lambda k: int(v[k]) if str(v.get(k, "")).lstrip("-").isdigit() else None
                mins = n("minutes")
                tp = str(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted") or "").split("-")[0]
                rows.append({"id": ath.get("id") or ath.get("displayName"), "name": _h.unescape(ath.get("displayName") or ""), "no": ath.get("jersey"),
                             "pos": P.get((ath.get("position") or {}).get("abbreviation"), ""), "st": bool(a.get("starter")),
                             "min": str(mins) if mins else None, "_s": (mins or 0) * 60, "pts": n("points"), "reb": n("rebounds"), "ast": n("assists"),
                             "to": n("turnovers"), "stl": n("steals"), "blk": n("blocks"), "tpm": int(tp) if tp.isdigit() else None})
        out[sd] = rows
    if "home" not in out or "away" not in out or not (out["home"] or out["away"]):
        return None
    if sum(p["st"] for p in out["home"]) not in (0, 5) or sum(p["st"] for p in out["away"]) not in (0, 5):
        return None   # 선발 5명이 아니면 믿지 않음
    return {"src": "ESPN", "cols": ["min", "pts", "reb", "ast", "to", "stl", "blk", "tpm"], "home": out["home"], "away": out["away"]}


def _bk_api(g, live):
    import teamodds as T
    gid = g.get("id")
    rs = _cache(("abk", gid), 30 if live else 600, lambda: T._get("basketball", "/games/statistics/players", {"id": gid}))
    if not rs:
        return None
    hid = g.get("home_id")
    def sec(m):
        try:
            a, b = str(m).split(":")[:2]; return int(a) * 60 + int(b)
        except Exception:
            return 0
    ho, aw = [], []
    for x in rs:
        pl = x.get("player") or {}
        s = sec(x.get("minutes"))
        row = {"id": pl.get("id") or pl.get("name"), "name": __import__("html").unescape(pl.get("name") or ""), "pos": "", "st": x.get("type") == "starters",
               "min": x.get("minutes") if s else None, "_s": s, "pts": x.get("points"), "reb": (x.get("rebounds") or {}).get("total"),
               "ast": x.get("assists"), "tpm": (x.get("threepoint_goals") or {}).get("total")}
        ((ho if (x.get("team") or {}).get("id") == hid else aw)).append(row)
    has = lambda k: any(r.get(k) is not None for r in ho + aw)
    cols = [c for c in ("min", "pts", "reb", "ast", "tpm") if has(c)]
    if cols == [] or not has("pts"):
        return None
    ns = lambda L: sum(1 for r in L if r["st"])
    if ns(ho) not in (0, 5) or ns(aw) not in (0, 5):   # 선발 표시가 이상하면 선발/벤치 구분 없이 보여줌
        for r in ho + aw:
            r["st"] = False
    return {"src": "API-Sports", "cols": cols, "home": ho, "away": aw}


def basketball(g):
    try:
        live = data.state(g) == "live"
    except Exception:
        live = False
    r = None
    try:
        if g.get("league") in (91, 92):
            r = _bk_naver(g, live)
        elif g.get("league") == 12:
            r = _bk_espn(g, live)
        r = r or _bk_api(g, live)
    except Exception:
        r = None
    if not r or not (r.get("home") or r.get("away")):
        return None
    for k in ("home", "away"):
        r[k].sort(key=lambda p: (not p["st"], -(p["_s"] or 0)))
        for p in r[k]:
            p.pop("_s", None)
    return {"kind": "basketball", **r}


# ---------- 홈 목록 라이브 B/S/O + 주자 ----------
def _on(v):
    return str(v or "0").strip() not in ("", "0")


def bso(g):
    if g.get("kind") != "baseball" or data.state(g) != "live":
        return None
    if g.get("league") == 5:
        st = S._kbo(g)
        gid = st and st.get("_gid")
        if not gid:
            return None
        cs = _cache(("bso", gid), 12, lambda: (((_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/relay", NAVER_H).get("result") or {}).get("textRelayData") or {}).get("currentGameState")))
        if not cs or str(cs.get("out")) == "3":
            return None
        b, s, o = _n(cs.get("ball")), _n(cs.get("strike")), _n(cs.get("out"))
        if b is None or s is None or o is None:
            return None
        return {"b": min(b, 3), "s": min(s, 2), "o": min(o, 2), "r": [_on(cs.get("base1")), _on(cs.get("base2")), _on(cs.get("base3"))]}
    if g.get("league") in (1, 2):
        try:
            r = ov_bso(g)
        except Exception:
            r = None
        if r or g.get("league") == 2:
            return r
        st = S._mlb(g)
        pk = st and st.get("_pk")
        if not pk:
            return None
        ls = _cache(("bsom", pk), 12, lambda: _j(f"https://statsapi.mlb.com/api/v1/game/{pk}/linescore"))
        if not ls or ls.get("inningState") in ("Middle", "End") or ls.get("outs") == 3:
            return None
        if ls.get("balls") is None or ls.get("strikes") is None or ls.get("outs") is None:
            return None
        of = ls.get("offense") or {}
        return {"b": min(ls["balls"], 3), "s": min(ls["strikes"], 2), "o": min(ls["outs"], 2), "r": [bool(of.get("first")), bool(of.get("second")), bool(of.get("third"))]}
    return None


# ---------- 상세 라이브 필드 (KBO 네이버 문자중계 / MLB statsapi) ----------
def _ls_rows(inn_a, inn_h, n):
    return [[inn_a.get(str(i), "") if isinstance(inn_a, dict) else (inn_a[i - 1] if i <= len(inn_a) else "") for i in range(1, n + 1)],
            [inn_h.get(str(i), "") if isinstance(inn_h, dict) else (inn_h[i - 1] if i <= len(inn_h) else "") for i in range(1, n + 1)]]


def _field_kbo(g, live):
    st = S._kbo(g)
    gid = st and st.get("_gid")
    if not gid:
        return None
    swap = st.get("_swap")
    t = _cache(("fld", gid), 10 if live else 600, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/relay", NAVER_H).get("result") or {}).get("textRelayData"))
    if not t:
        return None
    cs = t.get("currentGameState") or {}
    isc = t.get("inningScore") or {}
    ia, ih = isc.get("away") or {}, isc.get("home") or {}
    if swap:
        ia, ih = ih, ia
    n = max([9] + [int(k) for k in list(ia) + list(ih) if str(k).isdigit()])
    ra, rh = _ls_rows(ia, ih, n)
    A = lambda k: cs.get(("home" if swap else "away") + k)
    H = lambda k: cs.get(("away" if swap else "home") + k)
    out = {"src": "네이버 스포츠", "ls": {"n": n, "away": {"inn": ra, "r": A("Score"), "h": A("Hit"), "e": A("Error")},
                                      "home": {"inn": rh, "r": H("Score"), "h": H("Hit"), "e": H("Error")}}}
    if not live:
        return out
    top = str(t.get("homeOrAway")) == "0"
    inn = t.get("inn")
    out["cur"] = {"inn": inn, "top": (top != bool(swap))}
    out["inn"] = f"{inn}회{'초' if top else '말'}" if inn else ""
    off = t.get("awayLineup" if top else "homeLineup") or {}
    dfn = t.get("homeLineup" if top else "awayLineup") or {}
    bats = off.get("batter") or []
    def by_order(o):
        c = [b for b in bats if str(b.get("batOrder")) == str(o)]
        return max(c, key=lambda b: b.get("seqno") or 0)["name"] if c else None
    # 네이버 KBO는 주자 이름을 직접 주지 않음 → 이름 추정 없이 베이스 불만 켬
    out["between"] = str(cs.get("out")) == "3"
    out["bases"] = [None if out["between"] else (True if _on(cs.get(f"base{i}")) else None) for i in (1, 2, 3)]
    out["b"], out["s"], out["o"] = (min(_n(cs.get(k)) or 0, m) for k, m in (("ball", 3), ("strike", 2), ("out", 2)))
    if out.get("between"):
        out["b"] = out["s"] = out["o"] = 0
    bt = next((b for b in bats if b.get("pcode") == cs.get("batter")), None)
    pt = next((p for p in dfn.get("pitcher") or [] if p.get("pcode") == cs.get("pitcher")), None)
    if bt and not out.get("between"):
        out["batter"] = {"name": bt.get("name"), "sub": f"{bt.get('batOrder')}번타자", "line": f"오늘 {bt.get('ab', 0)}타수 {bt.get('hit', 0)}안타" + (f" {bt['hr']}홈런" if bt.get("hr") else "") + (f" {bt['rbi']}타점" if bt.get("rbi") else "")}
    if pt and not out.get("between"):
        line = []
        if pt.get("inn") not in (None, ""):
            line.append(f"{pt.get('inn')}이닝")
        for k, lab in (("ballCount", "구"), ("kk", "삼진"), ("er", "자책")):
            if pt.get(k) not in (None, ""):
                line.append(f"{pt.get(k)}{lab}")
        out["pitcher"] = {"name": pt.get("name"), "sub": "투수", "line": "오늘 " + " ".join(line) if line else ""}
    plays = []
    for r in t.get("textRelays") or []:
        for o in reversed(r.get("textOptions") or []):
            if o.get("type") not in (1, 7, 8) and o.get("text"):
                plays.append(o["text"])
        if len(plays) >= 3:
            break
    out["plays"] = plays[:3]
    try:
        enrich_field(g, out, t, top, swap)
    except Exception:
        pass
    return out


EV_KO = {"single": "1루타", "double": "2루타", "triple": "3루타", "home_run": "홈런", "walk": "볼넷", "intent_walk": "고의4구", "hit_by_pitch": "몸에 맞는 공",
         "strikeout": "삼진", "strikeout_double_play": "삼진 병살", "field_out": "범타 아웃", "force_out": "포스 아웃", "grounded_into_double_play": "병살타",
         "double_play": "병살", "triple_play": "삼중살", "sac_fly": "희생플라이", "sac_bunt": "희생번트", "fielders_choice": "야수선택", "fielders_choice_out": "야수선택 아웃",
         "field_error": "실책 출루", "catcher_interf": "타격방해", "stolen_base_2b": "2루 도루", "stolen_base_3b": "3루 도루", "caught_stealing_2b": "2루 도루 실패",
         "wild_pitch": "폭투", "passed_ball": "포일", "balk": "보크", "pickoff_1b": "1루 견제사", "sac_fly_double_play": "희생플라이 병살"}


def _ko_play(x):
    r = x.get("result") or {}
    lab = EV_KO.get(r.get("eventType"))
    if not lab:
        return None   # 영어 그대로 두지 않음: 모르는 이벤트는 생략
    nm = ((x.get("matchup") or {}).get("batter") or {}).get("fullName") or ""
    if r.get("eventType") == "home_run":
        rb = r.get("rbi") or 1
        return f"{nm} 홈런! {'솔로' if rb == 1 else ('만루홈런' if rb == 4 else f'{rb}점')}".strip()
    return f"{nm} : {lab}" if nm else lab


def _field_mlb(g, live):
    st = S._mlb(g)
    pk = st and st.get("_pk")
    if not pk:
        return None
    ls = _cache(("fldm", pk), 10 if live else 600, lambda: _j(f"https://statsapi.mlb.com/api/v1/game/{pk}/linescore"))
    if not ls:
        return None
    inns = ls.get("innings") or []
    n = max(9, len(inns))
    ra = [((x.get("away") or {}).get("runs", "")) for x in inns] + [""] * (n - len(inns))
    rh = [((x.get("home") or {}).get("runs", "")) for x in inns] + [""] * (n - len(inns))
    tm = ls.get("teams") or {}
    out = {"src": "MLB 공식 기록", "ls": {"n": n, "away": {"inn": ra, **{k: (tm.get("away") or {}).get(v) for k, v in (("r", "runs"), ("h", "hits"), ("e", "errors"))}},
                                      "home": {"inn": rh, **{k: (tm.get("home") or {}).get(v) for k, v in (("r", "runs"), ("h", "hits"), ("e", "errors"))}}}}
    if not live:
        return out
    top = bool(ls.get("isTopInning"))
    out["cur"] = {"inn": ls.get("currentInning"), "top": top}
    out["inn"] = f"{ls.get('currentInning')}회{'초' if top else '말'}"
    between = ls.get("inningState") in ("Middle", "End")
    of, df = ls.get("offense") or {}, ls.get("defense") or {}
    out["between"] = between
    out["bases"] = [None if between else ((of.get(k) or {}).get("fullName") or (True if of.get(k) else None)) for k in ("first", "second", "third")]
    out["b"], out["s"], out["o"] = (0, 0, 0) if between else (min(ls.get("balls") or 0, 3), min(ls.get("strikes") or 0, 2), min(ls.get("outs") or 0, 2))
    if not between:
        bx = _cache(("mb", pk), 25, lambda: _j(f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore")) or {}
        def pl(side, pid):
            return (((bx.get("teams") or {}).get(side) or {}).get("players") or {}).get(f"ID{pid}") or {}
        b, p = of.get("batter") or {}, df.get("pitcher") or {}
        if b.get("id"):
            s = (pl("away" if top else "home", b["id"]).get("stats") or {}).get("batting") or {}
            out["batter"] = {"name": b.get("fullName"), "sub": "타자", "line": f"오늘 {s.get('atBats', 0)}타수 {s.get('hits', 0)}안타" if s else ""}
        if p.get("id"):
            s = (pl("home" if top else "away", p["id"]).get("stats") or {}).get("pitching") or {}
            out["pitcher"] = {"name": p.get("fullName"), "sub": "투수", "line": f"오늘 {s.get('inningsPitched')}이닝 {s.get('numberOfPitches', 0)}구 {s.get('strikeOuts', 0)}삼진" if s else ""}
        pb = _cache(("fldp", pk), 15, lambda: _j(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live?fields=liveData,plays,allPlays,result,eventType,rbi,matchup,batter,fullName"))
        ap = (((pb or {}).get("liveData") or {}).get("plays") or {}).get("allPlays") or []
        out["plays"] = [p for p in (_ko_play(x) for x in reversed(ap)) if p][:3]
    return out


def field(g):
    if g.get("kind") != "baseball":
        return None
    try:
        stt = data.state(g)
    except Exception:
        stt = ""
    if stt not in ("live", "final"):
        return None
    live = stt == "live"
    try:
        if g.get("league") == 5:
            r = _field_kbo(g, live)
        elif g.get("league") in (1, 2):
            try:
                r = ov_field(g, live)
            except Exception:
                r = None
            if not r and g.get("league") == 1:
                r = _field_mlb(g, live)
        else:
            r = None
    except Exception:
        r = None
    if r:
        r["live"] = live
    return r


# ---------- 해외야구(MLB·NPB): 네이버 스포츠 한글 문자중계/기록 ----------
import re as _re
from datetime import timedelta as _td
OVC = {1: "mlb", 2: "npb"}
# 네이버 약칭 → 우리 표기(공백 제거). 확인된 것만.
NV_ALIAS = {"시카고w": "시카고화이트삭스", "시카고c": "시카고컵스"}


def _ov_match(g):
    cat = OVC.get(g.get("league"))
    if not cat:
        return None
    st = g["start"]
    d0, d1 = (st - _td(days=1)).strftime("%Y-%m-%d"), (st + _td(days=1)).strftime("%Y-%m-%d")
    games = _cache(("ovs", cat, d0), 300, lambda: (_j("https://api-gw.sports.naver.com/schedule/games?fields=basic,schedule,baseball"
                                                       f"&upperCategoryId=wbaseball&categoryId={cat}&fromDate={d0}&toDate={d1}&size=100", NAVER_H).get("result") or {}).get("games") or [])
    h, a = _nm(g["home"]), _nm(g["away"])
    ok = lambda x, y: bool(x) and bool(y) and (x in y or y in x)
    al = lambda n: NV_ALIAS.get(n, n)
    best, hits = None, 0
    for x in games or []:
        nh, na = al(_nm(x.get("homeTeamName"))), al(_nm(x.get("awayTeamName")))
        try:
            from datetime import datetime as _dt
            t = _dt.fromisoformat(x["gameDateTime"]).replace(tzinfo=st.tzinfo)
            dt = abs((t - st).total_seconds())
        except Exception:
            dt = 0
        if dt > 8 * 3600:
            continue
        if ok(nh, h) and ok(na, a):
            best = (x["gameId"], False)
        elif ok(nh, a) and ok(na, h) and not best:
            best = (x["gameId"], True)

    return best


def _ov_relay(gid, live):
    return _cache(("ovr", gid), 10 if live else 600, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/relay", NAVER_H).get("result") or {}).get("textRelayData"))


def _ov_record(gid, live):
    return _cache(("ovb", gid), 25 if live else 600, lambda: (_j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/record", NAVER_H).get("result") or {}).get("recordData"))


def _live(g):
    try:
        return data.state(g) == "live"
    except Exception:
        return False


def ov_lineup(g):
    m = _ov_match(g)
    if not m:
        return None
    gid, swap = m
    rd = _ov_record(gid, _live(g))
    if not rd or not (rd.get("awayBatter") or rd.get("homeBatter")):
        return None
    def side(k):
        bat, pit, seen = [], [], set()
        for x in rd.get(k + "Batter") or []:
            o = x.get("batOrder")
            bat.append({"id": x.get("playerId") or x.get("name"), "o": o, "sub": o in seen, "name": x.get("name"), "pos": x.get("posName") or "",
                        "avg": _avg(x.get("avg")), "ab": x.get("ab"), "r": x.get("run"), "h": x.get("hit"), "rbi": x.get("rbi"), "bb": x.get("bb"), "so": x.get("so"), "hr": x.get("hr")})
            seen.add(o)
        for x in rd.get(k + "Pitcher") or []:
            pit.append({"id": x.get("playerId") or x.get("name"), "name": x.get("name"), "ip": (x.get("inn") or "").replace(".0", "") or None, "h": x.get("hit"), "r": x.get("run", x.get("r")),
                        "er": x.get("er"), "bb": x.get("bb"), "so": x.get("so"), "np": x.get("bf"), "era": x.get("era"), "dec": x.get("wls") or ""})
        return {"bat": bat, "pit": pit, "pre": False}
    a, h = side("away"), side("home")
    if swap:
        a, h = h, a
    return {"src": "네이버 스포츠", "away": a, "home": h}


def _ov_state(g):
    m = _ov_match(g)
    if not m:
        return None, None, None
    gid, swap = m
    return _ov_relay(gid, _live(g)), swap, gid


def ov_bso(g):
    t, swap, _ = _ov_state(g)
    bc = ((t or {}).get("baseInfo") or {}).get("ballCount") or {}
    if not bc or bc.get("o") is None or bc.get("o") == 3:
        return None
    return {"b": min(bc.get("b") or 0, 3), "s": min(bc.get("s") or 0, 2), "o": min(bc.get("o") or 0, 2), "r": [bool(bc.get("base1")), bool(bc.get("base2")), bool(bc.get("base3"))]}


_PITCH = _re.compile(r"^\d+구\s")


def ov_field(g, live):
    t, swap, gid = _ov_state(g)
    if not t:
        return None
    bi = t.get("baseInfo") or {}
    isc = bi.get("inningScore") or {}
    ia, ih = list(isc.get("away") or []), list(isc.get("home") or [])
    rh = bi.get("rheb") or {}
    A, H = (rh.get("home") or {}, rh.get("away") or {}) if swap else (rh.get("away") or {}, rh.get("home") or {})
    if swap:
        ia, ih = ih, ia
    n = max(9, len(ia), len(ih))
    out = {"src": "네이버 스포츠", "ls": {"n": n, "away": {"inn": ia + [""] * (n - len(ia)), "r": A.get("r"), "h": A.get("h"), "e": A.get("e")},
                                      "home": {"inn": ih + [""] * (n - len(ih)), "r": H.get("r"), "h": H.get("h"), "e": H.get("e")}}}
    if not live:
        return out
    bc = bi.get("ballCount") or {}
    top = str(t.get("homeOrAway")) == "0"
    inn = t.get("inn")
    out["inn"] = f"{inn}회{'초' if top else '말'}" if inn else (t.get("statusInfo") or "")
    out["cur"] = {"inn": inn, "top": top != bool(swap)}
    between = bc.get("o") == 3
    out["between"] = between
    out["bases"] = [None if between else (bc.get(f"base{i}") or None) for i in (1, 2, 3)]
    out["b"], out["s"], out["o"] = (0, 0, 0) if between else (min(bc.get("b") or 0, 3), min(bc.get("s") or 0, 2), min(bc.get("o") or 0, 2))
    rd = _ov_record(gid, live) or {}
    if not between:
        bid = bc.get("batterId")
        bs = next((x for x in (rd.get(("away" if top else "home") + "Batter") or []) if x.get("playerId") == bid), None)
        if bc.get("batter"):
            out["batter"] = {"name": bc["batter"], "sub": f"{bs.get('batOrder')}번타자" if bs else "타자",
                             "line": (f"오늘 {bs.get('ab', 0)}타수 {bs.get('hit', 0)}안타" + (f" {bs['hr']}홈런" if bs.get("hr") else "") + (f" {bs['rbi']}타점" if bs.get("rbi") else "")) if bs else ""}
        dk = "home" if top else "away"
        pn, pid = bi.get(dk + "Pitcher"), bi.get(dk + "PitcherId")
        ps = next((x for x in (rd.get(dk + "Pitcher") or []) if x.get("playerId") == pid), None)
        if pn:
            line = []
            if ps:
                line += [f"{ps.get('inn')}이닝"] if ps.get("inn") else []
            if bi.get(dk + "PitcherPitchBallCount"):
                line.append(f"{bi[dk + 'PitcherPitchBallCount']}구")
            if ps:
                line += [f"{ps.get('so', 0)}삼진", f"{ps.get('er', 0)}자책"]
            out["pitcher"] = {"name": pn, "sub": "투수", "line": ("오늘 " + " ".join(line)) if line else ""}
    plays = []
    for r in t.get("textRelays") or []:
        lines = [_re.sub(r"<[^>]+>", "", x).strip() for x in (r.get("text") or "").split("<br/>")]
        for x in reversed([x for x in lines if x and not _PITCH.match(x)]):
            plays.append(x)
        if len(plays) >= 3:
            break
    out["plays"] = plays[:3]
    try:
        enrich_field(g, out, t, top, swap)
    except Exception:
        pass
    return out


# ---------- 필드 카드 보강: 네이버 시즌 기록·사진(피드가 주는 playerImageUrl만) ----------
def _nv_stats(cat, code, extra=""):
    if not code:
        return {}
    yr = time.localtime().tm_year
    def f():
        m = {}
        for t in ("HITTER", "PITCHER"):
            u = (f"https://api-gw.sports.naver.com/statistics/categories/{cat}/seasons/{yr}/players?teamCode={code}&playerType={t}&pageSize=100{extra}")
            for x in (_j(u, NAVER_H).get("result") or {}).get("seasonPlayerStats") or []:
                if x.get("playerId"):
                    m.setdefault(str(x["playerId"]), {}).update(x)
        return m
    return _cache(("nvst", cat, code), 3600, f) or {}


def _team_cat(g, side):
    import roster as R
    tid = g.get(side + "_id")
    if g.get("league") == 5:
        return "kbo", R.KBO.get(tid), ""
    if g.get("league") == 2 and tid in R.NPB:
        c, lg = R.NPB[tid]
        return "npb", c, "&league=PL" if lg == "P" else ""
    if g.get("league") == 1:
        try:
            return "mlb", R._naver_mlb_code(g[side]), ""
        except Exception:
            return "mlb", None, ""
    return None, None, ""


def _f3(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f"{f:.3f}".lstrip("0") if f < 1 else f"{f:.3f}"


def _card(kind, pid, st, base):
    """base: 이름·등번호·손 등 피드 값. st: 네이버 시즌 기록(같은 playerId). 없는 값은 넣지 않음."""
    c = dict(base)
    if st:
        if st.get("playerImageUrl"):
            c["photo"] = st["playerImageUrl"]
        if c.get("no") in (None, "") and st.get("backNumber") is not None:
            c["no"] = st["backNumber"]
        if kind == "p":
            s = []
            if st.get("pitcherEra") is not None:
                s.append(f"ERA {float(st['pitcherEra']):.2f}")
            if st.get("pitcherWin") is not None and st.get("pitcherLose") is not None:
                s.append(f"{st['pitcherWin']}승 {st['pitcherLose']}패")
            if st.get("pitcherKk") is not None:
                s.append(f"{st['pitcherKk']}삼진")
        else:
            s = []
            if st.get("hitterHra") is not None:
                s.append(f"타율 {_f3(st['hitterHra'])}")
            if st.get("hitterHr") is not None:
                s.append(f"{st['hitterHr']}홈런")
            if st.get("hitterRbi") is not None:
                s.append(f"{st['hitterRbi']}타점")
            if st.get("hitterOps") is not None:
                s.append(f"OPS {_f3(st['hitterOps'])}")
        if s:
            c["season"] = " · ".join(s)
    return c


KPOS_N = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}


def enrich_field(g, out, raw, top, swap):
    """raw: KBO=textRelayData, 해외=('ov', textRelayData). out 에 pcard/bcard/def/next 추가."""
    off_side = ("away" if top else "home")
    def_side = ("home" if top else "away")
    # 우리 쪽 away/home 기준 팀 → 네이버 시즌 기록
    our_off = {"away": "home", "home": "away"}[off_side] if swap else off_side
    our_def = {"away": "home", "home": "away"}[def_side] if swap else def_side
    try:
        so = _nv_stats(*_team_cat(g, our_off))
        sd = _nv_stats(*_team_cat(g, our_def))
    except Exception:
        so, sd = {}, {}
    if g.get("league") == 5:
        t = raw
        cs = t.get("currentGameState") or {}
        off = t.get(off_side + "Lineup") or {}
        dfn = t.get(def_side + "Lineup") or {}
        bt = next((b for b in off.get("batter") or [] if b.get("pcode") == cs.get("batter")), None)
        pt = next((p for p in dfn.get("pitcher") or [] if p.get("pcode") == cs.get("pitcher")), None)
        if bt and out.get("batter"):
            out["bcard"] = _card("b", bt["pcode"], so.get(str(bt["pcode"])), {"name": bt.get("name"), "no": bt.get("backnum"), "hand": bt.get("hitType"),
                                                                             "sub": out["batter"].get("sub"), "today": out["batter"].get("line")})
        if pt and out.get("pitcher"):
            out["pcard"] = _card("p", pt["pcode"], sd.get(str(pt["pcode"])), {"name": pt.get("name"), "no": pt.get("backnum"), "hand": pt.get("hitType"),
                                                                             "sub": "투수", "today": out["pitcher"].get("line"),
                                                                             **({"pc": pt.get("ballCount")} if pt.get("ballCount") is not None else {})})
        # 현재 수비: 수비팀 타자 중 교체되어 나가지 않은(cout 없음) 선수의 수비 위치 + 현재 투수
        dl = []
        for b in dfn.get("batter") or []:
            if b.get("cout"):
                continue
            ps = KPOS_N.get(b.get("pos"))
            if ps and ps != "P":
                dl.append({"pos": ps, "name": b.get("name")})
        poss = [d["pos"] for d in dl]
        if len(set(poss)) == len(poss) and pt and not out.get("between"):   # 위치 중복·공수교대 등 모호하면 표시 안 함
            out["def"] = dl + [{"pos": "P", "name": pt.get("name")}]
    else:
        t = raw
        bi = t.get("baseInfo") or {}
        bc = bi.get("ballCount") or {}
        if out.get("batter") and bc.get("batterId"):
            st = so.get(str(bc["batterId"]))
            hand = {"L": "좌타", "R": "우타", "S": "양타"}.get(bc.get("batterHitType"))
            out["bcard"] = _card("b", bc["batterId"], st, {"name": out["batter"]["name"], "sub": out["batter"].get("sub"), "today": out["batter"].get("line"),
                                                           **({"hand": hand} if hand else {})})
        dk = def_side
        pid = bi.get(dk + "PitcherId")
        if out.get("pitcher") and pid:
            out["pcard"] = _card("p", pid, sd.get(str(pid)), {"name": out["pitcher"]["name"], "sub": "투수", "today": out["pitcher"].get("line"),
                                                              **({"pc": bi.get(dk + "PitcherPitchBallCount")} if bi.get(dk + "PitcherPitchBallCount") else {})})
        nx = bi.get("nextPlayer") or {}
        if nx.get("player") and not out.get("between"):
            out["next"] = f"{nx.get('playerNum')}번 {nx['player']}" if nx.get("playerNum") else nx["player"]
    return out


def bso_mini(g, b):
    """홈 목록용: 현재 투수·타자 한 줄. 피드가 명확히 준 값만(이름·투구수·시즌 타율)."""
    if not b:
        return b
    try:
        f = field(g) or {}
    except Exception:
        return b
    if f.get("between"):
        return b
    p, t = f.get("pcard") or {}, f.get("bcard") or {}
    if p.get("name"):
        b["p"] = {"n": p["name"]}
        if isinstance(p.get("pc"), int):
            b["p"]["pc"] = p["pc"]
    if t.get("name"):
        b["t"] = {"n": t["name"]}
        m = _re.search(r"타율 (\.\d{3}|\d\.\d{3})", t.get("season") or "")
        if m:
            b["t"]["avg"] = m.group(1)
    return b


# ---------- 축구: 공식 발표 선발 (API-Sports /fixtures/lineups) ----------
_FP = {"G": "GK", "D": "DF", "M": "MF", "F": "FW"}


def football(g):
    """경기별 공식 발표 라인업만. 팀 id가 이 경기 홈/원정과 정확히 맞고 양 팀 선발 11명일 때만 보여줌.
    발표 전·불일치 → {'none': True} (예상 라인업이나 시즌 주전으로 대신 채우지 않음)."""
    import teamodds as T
    if g.get("kind") != "football" or not g.get("id"):
        return None
    st = data.state(g) if g else ""
    ttl = 120 if st == "scheduled" else 300
    rs = _cache(("fbl", g["id"]), ttl, lambda: T._get("football", "/fixtures/lineups", {"fixture": g["id"]}))
    if not rs:
        return {"kind": "football", "none": True}
    by = {((x.get("team") or {}).get("id")): x for x in rs}
    if len(rs) != 2 or set(by) != {g.get("home_id"), g.get("away_id")}:
        return {"kind": "football", "none": True, "why": "mismatch"}
    out = {"kind": "football", "src": "API-Sports · 공식 발표", "logo": {"home": g.get("home_logo") or "", "away": g.get("away_logo") or ""}}
    for side in ("home", "away"):
        x = by[g.get(side + "_id")]
        xi = [(p.get("player") or {}) for p in x.get("startXI") or []]
        if len(xi) != 11 or sum(1 for p in xi if p.get("pos") == "G") != 1 or len({p.get("id") or p.get("name") for p in xi}) != 11:
            return {"kind": "football", "none": True, "why": "invalid"}
        sub = [(p.get("player") or {}) for p in x.get("substitutes") or []]
        mk = lambda p: {"id": p.get("id") or p.get("name"), "no": p.get("number"), "name": __import__("html").unescape(p.get("name") or ""), "pos": _FP.get(p.get("pos"), ""), "g": p.get("grid") or ""}
        out[side] = {"_no": {p.get("number") for p in xi}, "form": x.get("formation") or "", "coach": ((x.get("coach") or {}).get("name") or ""), "xi": [mk(p) for p in xi], "subs": [mk(p) for p in sub]}
    try:
        ef = _espn_forms(g, out)
    except Exception:
        ef = None
    ef = _freeze(g, st, ef)
    if ef and not ef.get("agree"):   # ESPN과 선발 11명이 다르면 틀릴 수 있는 라인업은 숨김
        return {"kind": "football", "none": True, "why": "disagree"}
    for side in ("home", "away"):
        t = out[side]
        t["pitch"] = _grid_ok(t["xi"], ((ef or {}).get("pos") or {}).get(side) or {})
        if not t["pitch"]:
            for p in t["xi"]:
                p["_g"] = p.pop("g", None)
    try:
        _ko_names(g, out)
    except Exception:
        pass
    for side in ("home", "away"):
        for p in out[side]["xi"]:
            p.pop("_g", None)
        nos = out[side].pop("_no")
        e = (ef or {}).get(side)
        if e and out[side]["form"] and e != out[side]["form"]:   # 두 출처 포메이션이 다르면 숨김 (라인업은 유지)
            out[side]["form"] = ""
    return out


ESPN_FB = {17: "afc.champions", 18: "afc.cup", 2: "uefa.champions", 3: "uefa.europa", 39: "eng.1", 140: "esp.1", 135: "ita.1", 78: "ger.1", 61: "fra.1", 292: "kor.1", 98: "jpn.1"}


def _espn_forms(g, out):
    """ESPN 같은 경기 포메이션 {home, away}. 시작 ±20분 + 양 팀 선발 등번호 9개 이상 일치로만 같은 경기로 봄. 못 찾으면 None."""
    from datetime import datetime as _dt, timezone as _tz
    lg = ESPN_FB.get(g.get("league"))
    if not lg:
        return None
    st = g["start"].astimezone(_tz.utc)
    dd = st.strftime("%Y%m%d")
    evs = _cache(("efs", lg, dd), 600, lambda: _j(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={dd}").get("events") or [])
    for e in evs or []:
        try:
            t = _dt.strptime(e["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=_tz.utc)
        except Exception:
            continue
        if abs((t - st).total_seconds()) > 1200:
            continue
        sm = _cache(("efm", e["id"]), 900, lambda i=e["id"]: _j(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={i}"))
        R = {r.get("homeAway"): r for r in (sm or {}).get("rosters") or []}
        ok = True
        for side in ("home", "away"):
            nos = {int(p["jersey"]) for p in (R.get(side) or {}).get("roster") or [] if p.get("starter") and str(p.get("jersey", "")).isdigit()}
            if len(nos & out[side]["_no"]) < 9:
                ok = False
        if ok:
            agree = all({int(p["jersey"]) for p in R[sd].get("roster") or [] if p.get("starter") and str(p.get("jersey", "")).isdigit()} == out[sd]["_no"] for sd in ("home", "away"))
            pos = {sd: {int(p["jersey"]): ((p.get("position") or {}).get("abbreviation") or "") for p in R[sd].get("roster") or [] if p.get("starter") and str(p.get("jersey", "")).isdigit()} for sd in ("home", "away")}
            return {**{sd: (R[sd].get("formation") or None) for sd in ("home", "away")}, "agree": agree, "pos": pos}
    return None


def _side_tag(a):
    a = (a or "").upper()
    if a.endswith("-L") or a in ("LB", "LM", "LW", "LWB", "LF"):
        return "L"
    if a.endswith("-R") or a in ("RB", "RM", "RW", "RWB", "RF"):
        return "R"
    return None


def _grid_ok(xi, epos):
    """피치 배치는 API-Sports grid(행:열, 열1=선수 기준 왼쪽)를 ESPN 좌/우 포지션으로 확인됐을 때만.
    확인 근거가 없거나 하나라도 어긋나면 False → 표(행 정보 없음)로 표시."""
    rows = {}
    for p in xi:
        try:
            r, c = map(int, str(p.get("g") or "").split(":"))
        except Exception:
            return False
        rows.setdefault(r, []).append(c)
    if len(rows) < 3 or len({(r, c) for r in rows for c in rows[r]}) != 11:
        return False
    good = 0
    for p in xi:
        tag = _side_tag(epos.get(p.get("no")))
        if not tag:
            continue
        r, c = map(int, p["g"].split(":"))
        n = len(rows[r])
        if n < 2:
            continue
        mid = (n + 1) / 2
        if (tag == "L" and c >= mid) or (tag == "R" and c <= mid):
            return False
        good += 1
    return good >= 2


def _ko_names(g, out):
    """한글 이름: 한국 팀 + 네이버 공식 라인업의 행 구성이 API-Sports grid와 정확히 같을 때만.
    네이버 홈 행 = GK부터, 행 안은 오른쪽→왼쪽 / 원정 행 = 최전방부터, 행 안은 왼쪽→오른쪽 (포항·조호르 등 4경기로 확인)."""
    import teamodds as T
    kr = {}
    for sd in ("home", "away"):
        tid = g.get(sd + "_id")
        info = _cache(("ftm", tid), 86400, lambda tid=tid: T._get("football", "/teams", {"id": tid}))
        kr[sd] = bool(info) and ((info[0].get("team") or {}).get("country") == "South-Korea")
    if not any(kr.values()):
        return
    st = g["start"]
    day = st.strftime("%Y-%m-%d")
    games = []
    for up in ("kfootball", "wfootball"):   # ACL·K리그는 kfootball, 해외 리그는 wfootball
        games += _cache(("nfs", up, day), 600, lambda up=up: (_j(f"https://api-gw.sports.naver.com/schedule/games?fields=basic&upperCategoryId={up}&fromDate={day}&toDate={day}&size=100", NAVER_H).get("result") or {}).get("games") or []) or []
    gid = None
    for x in games or []:
        try:
            from datetime import datetime as _dt
            t = _dt.fromisoformat(x["gameDateTime"]).replace(tzinfo=st.tzinfo)
        except Exception:
            continue
        if abs((t - st).total_seconds()) <= 600:
            ln = _cache(("nfl", x["gameId"]), 300, lambda i=x["gameId"]: ((_j(f"https://api-gw.sports.naver.com/schedule/games/{i}/lineup", NAVER_H).get("result") or {}).get("lineUpData") or {}).get("lineup"))
            if ln and _nv_hits(ln, out, kr) >= 3:
                gid = ln
                break
    if not gid:
        return
    _ko_apply(gid, out, kr)


def _nv_names(nside):
    pl = (nside or {}).get("players") or {}
    return [(p.get("name") or "").strip() for r in (pl.get("lineup") or []) for p in r]


def _ko_apply(ln, out, kr):
    """선수마다 이름 자체로 확인(한글 이름의 로마자 표기 후보 = API-Sports 영문 이름)되고, 서로 1:1일 때만 한글 이름. 자리 순서로는 절대 붙이지 않음."""
    import ko_roman
    n = 0
    for sd in ("home", "away"):
        if not kr.get(sd):
            continue
        names = {x for x in _nv_names(ln.get(sd)) if x}
        ps = out[sd]["xi"] + out[sd].get("subs", [])
        hit = {id(p): [k for k in names if ko_roman.match(k, p.get("name"))] for p in ps}
        for p in ps:
            h = hit[id(p)]
            if len(h) == 1 and sum(1 for q in ps if h[0] in hit[id(q)]) == 1:
                p["ko"] = h[0]
                n += 1
    return n


def _rows_of(xi):
    rows = {}
    for p in xi:
        try:
            r, c = map(int, str(p.get("_g") or p.get("g") or "").split(":"))
        except Exception:
            return None
        rows.setdefault(r, []).append((c, p))
    return [[p for _, p in sorted(v, key=lambda x: x[0])] for _, v in sorted(rows.items())]


def _nv_map(nside, xi, sd):
    nrows = ((nside or {}).get("players") or {}).get("lineup") or []
    ar = _rows_of(xi)
    if not ar or not nrows:
        return None
    if sd == "home":
        pairs = list(zip(nrows, [r[::-1] for r in ar]))
    else:
        pairs = list(zip(nrows, [r for r in ar[::-1]]))
    if len(nrows) != len(ar) or any(len(a) != len(b) for a, b in pairs):
        return None
    m = {}
    for nr, arow in pairs:
        for np_, ap in zip(nr, arow):
            nm = (np_.get("name") or "").strip()
            if not nm:
                return None
            if np_.get("pos") and ap.get("pos") and np_["pos"] != ap["pos"]:
                return None   # 포지션까지 같아야 같은 선수로 봄
            m[ap["no"]] = nm
    return m if len(m) == 11 else None


def _nv_hits(ln, out, kr):
    import copy
    try:
        return _ko_apply(ln, copy.deepcopy(out), kr)
    except Exception:
        return 0


def _nv_match(ln, out):
    try:
        return all(_nv_map(ln[sd], out[sd]["xi"], sd) is not None for sd in ("home", "away"))
    except Exception:
        return False


def _freeze(g, st, ef):
    """ESPN 확인 자료는 킥오프 전 발표 시점 것으로 고정. 경기 중 ESPN은 실시간 전술 위치로 바뀌어(예: 3-4-3→4-4-2) 비교 기준이 못 됨.
    킥오프 전: 저장. 경기 중·후: 저장본(또는 검증해 둔 data/lu_seed) 사용, 없으면 실시간 ESPN 그대로(어긋나면 숨김 쪽으로 안전)."""
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    fn = os.path.join(base, "cache", "lu_freeze", f"{g['id']}.json")
    if st == "scheduled":
        if ef:
            try:
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                json.dump({**ef, "pos": {k: {str(n): a for n, a in v.items()} for k, v in (ef.get("pos") or {}).items()}}, open(fn, "w"))
            except Exception:
                pass
        return ef
    for f in (fn, os.path.join(base, "lu_seed", f"{g['id']}.json")):
        try:
            d = json.load(open(f))
            d["pos"] = {k: {int(n): a for n, a in v.items()} for k, v in (d.get("pos") or {}).items()}
            return d
        except Exception:
            continue
    return ef


def _ko_freeze(g, st, out):
    """한글 이름도 킥오프 전 확인된 것으로 고정 (경기 중 네이버 라인업은 교체 반영으로 행 구성이 바뀜). 등번호로만 붙임."""
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    fn = os.path.join(base, "cache", "lu_freeze", f"{g['id']}_ko.json")
    cur = {sd: {str(p["no"]): p["ko"] for p in out[sd]["xi"] if p.get("ko")} for sd in ("home", "away")}
    if st == "scheduled":
        if any(cur.values()):
            try:
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                json.dump(cur, open(fn, "w"), ensure_ascii=False)
            except Exception:
                pass
        return
    for f in (fn, os.path.join(base, "lu_seed", f"{g['id']}_ko.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for sd in ("home", "away"):
            if cur[sd]:
                continue
            m = d.get(sd) or {}
            if m and all(str(p["no"]) in m for p in out[sd]["xi"]):   # 선발 11명이 모두 같을 때만
                for p in out[sd]["xi"]:
                    p["ko"] = m[str(p["no"])]
        return

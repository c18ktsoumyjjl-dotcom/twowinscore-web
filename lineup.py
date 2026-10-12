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
        row = {"id": pl.get("id") or pl.get("name"), "name": pl.get("name"), "pos": "", "st": x.get("type") == "starters",
               "min": x.get("minutes") if s else None, "_s": s, "pts": x.get("points"), "reb": (x.get("rebounds") or {}).get("total"),
               "ast": x.get("assists"), "tpm": (x.get("threepoint_goals") or {}).get("total")}
        ((ho if (x.get("team") or {}).get("id") == hid else aw)).append(row)
    has = lambda k: any(r.get(k) is not None for r in ho + aw)
    cols = [c for c in ("min", "pts", "reb", "ast", "tpm") if has(c)]
    if cols == [] or not has("pts"):
        return None
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
        r = r or _bk_api(g, live)
    except Exception:
        r = None
    if not r:
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
    return out

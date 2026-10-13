"""팀 페이지 선수 명단: 실제 데이터만. 종목별 선발/후보 근거와 짧은 시즌 기록."""
import json, time, urllib.request, urllib.parse
import teamodds as T

UA = {"User-Agent": "Mozilla/5.0 (twowinscore)"}
TTL = 6 * 3600


def _j(url, h=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(h or {})}), timeout=15) as r:
        return json.loads(r.read().decode())


def _p(name, no=None, pos="", st=None):
    return {"name": name or "?", "no": no if no not in ("", None) else None, "pos": pos or "", "st": [x for x in (st or []) if x]}


def _g(label, ps, basis=""):
    return {"label": label, "basis": basis, "ps": ps}


# ---------- 축구: API-Sports /players (선발 출전 수) ----------
FPOS = {"Goalkeeper": "골키퍼", "Defender": "수비수", "Midfielder": "미드필더", "Attacker": "공격수"}
FORD = ["골키퍼", "수비수", "미드필더", "공격수"]


def _football(tid, base):
    fx = T._get("football", "/fixtures", {"team": tid, "last": 1})
    season = fx and (fx[0].get("league") or {}).get("season")
    if not season:
        return None
    nums = {p["name"]: p["no"] for p in base}
    ps, page = [], 1
    while page <= 4:
        r = T._get("football", "/players", {"team": tid, "season": season, "page": page})
        for x in r:
            pl, sts = x.get("player") or {}, [s for s in x.get("statistics") or [] if (s.get("team") or {}).get("id") == tid]
            if not sts:
                continue
            ap = sum((s.get("games") or {}).get("appearences") or 0 for s in sts)
            ln = sum((s.get("games") or {}).get("lineups") or 0 for s in sts)
            gl = sum((s.get("goals") or {}).get("total") or 0 for s in sts)
            asst = sum((s.get("goals") or {}).get("assists") or 0 for s in sts)
            pos = FPOS.get((sts[0].get("games") or {}).get("position"), "")
            ps.append({**_p(pl.get("name"), (sts[0].get("games") or {}).get("number") or nums.get(pl.get("name")), pos,
                            [f"{ap}경기", f"{gl}골", f"{asst}도움"]), "_ln": ln, "_ap": ap})
        if len(r) < 20:
            break
        page += 1
    ps = [p for p in ps if p["_ap"] > 0]
    if not ps:
        return None
    key = lambda p: (FORD.index(p["pos"]) if p["pos"] in FORD else 9, -p["_ln"])
    top = set(id(p) for p in sorted(ps, key=lambda p: -p["_ln"])[:11] if p["_ln"] > 0)
    if sum(1 for p in ps if p["_ln"] > 0) < 11 or max(p["_ln"] for p in ps) < 3:   # 시즌 표본이 너무 적으면 주전 구분 안 함
        return [_g("출전 선수", sorted(ps, key=key), f"{season} 시즌 출전 기록 (경기 수가 적어 주전 구분 안 함)")], f"API-Sports · {season} 시즌 출전 선수"
    return [_g("주전급", sorted([p for p in ps if id(p) in top], key=key), f"{season} 시즌 선발 출전 많은 11명 · 경기별 선발 라인업 아님"),
            _g("후보", sorted([p for p in ps if id(p) not in top], key=key), "그 외 출전 선수")], f"API-Sports · {season} 시즌 출전 선수"


# ---------- 농구: 최근 경기 박스스코어 (선발/벤치 구분 제공) ----------
def _basketball(tid, base, past):
    gids = [r["gid"] for r in past if r.get("gid")][:5]
    if not gids:
        return None
    agg, last = {}, {}
    for i, gid in enumerate(gids):
        for x in T._get("basketball", "/games/statistics/players", {"id": gid}):
            if (x.get("team") or {}).get("id") != tid:
                continue
            pid = (x.get("player") or {}).get("id")
            a = agg.setdefault(pid, {"name": (x.get("player") or {}).get("name"), "n": 0, "p": 0, "r": 0, "a": 0})
            if x.get("minutes") in (None, "", "0:00", "00:00"):
                continue
            a["n"] += 1; a["p"] += x.get("points") or 0; a["r"] += (x.get("rebounds") or {}).get("total") or 0; a["a"] += x.get("assists") or 0
            if i == 0:
                last[pid] = x.get("type")
    if not last:
        return None
    bpos = {p["name"]: (p["no"], p["pos"]) for p in base}
    def mk(pid):
        a = agg[pid]; n = a["n"] or 1; no, pos = bpos.get(a["name"], (None, ""))
        return {**_p(a["name"], no, pos, [f"{a['p']/n:.1f}점", f"{a['r']/n:.1f}리바", f"{a['a']/n:.1f}어시"] if a["n"] else []), "_s": a["p"] / n}
    st = [mk(p) for p in agg if last.get(p) == "starters"]
    bn = [mk(p) for p in agg if last.get(p) != "starters" and agg[p]["n"]]
    o = lambda l: sorted(l, key=lambda p: -p["_s"])
    return [_g("선발", o(st), "최근 경기 선발 5명"), _g("후보", o(bn), "최근 경기 벤치 출전")], f"API-Sports · 최근 {len(gids)}경기 평균"


# ---------- KBO: 네이버 스포츠 시즌 기록 ----------
# API-Sports NPB team id → (네이버 팀코드, 리그). 퍼시픽은 league=PL 필요.
NPB = {55: ("JL", "P"), 56: ("JN", "C"), 57: ("SF", "P"), 58: ("HS", "C"), 59: ("HI", "C"), 60: ("NH", "P"), 61: ("OX", "P"),
       62: ("RT", "P"), 63: ("SE", "P"), 64: ("YA", "C"), 65: ("YK", "C"), 66: ("YO", "C")}
KBO = {88: "OB", 89: "HH", 90: "HT", 91: "KT", 92: "WO", 93: "LG", 94: "LT", 95: "NC", 97: "SS", 647: "SK"}
NAVER_H = {"Referer": "https://m.sports.naver.com/"}


def _kbo(tid, cat="kbo", code=None, extra=""):
    code = code or KBO.get(tid)
    if not code:
        return None
    y = time.localtime().tm_year
    for yr in (y, y - 1):
        u = "https://api-gw.sports.naver.com/statistics/categories/" + cat + "/seasons/%d/players?teamCode=%s&playerType=%s&pageSize=100" + extra
        hs = (_j(u % (yr, code, "HITTER"), NAVER_H).get("result") or {}).get("seasonPlayerStats") or []
        pi = (_j(u % (yr, code, "PITCHER"), NAVER_H).get("result") or {}).get("seasonPlayerStats") or []
        if hs or pi:
            break
    else:
        return None
    def pos(x):
        try:
            return json.loads(x.get("profile") or "{}").get("position") or ""
        except Exception:
            return ""
    H = [{**_p(x["playerName"], x.get("backNumber"), pos(x),
               [f"타율 {x['hitterHra']:.3f}".replace("0.", ".") if x.get("hitterHra") is not None else "", f"{x.get('hitterHr') or 0}홈런", f"{x.get('hitterRbi') or 0}타점"]),
          "_ab": x.get("hitterAb") or 0} for x in hs if x.get("playerName")]
    P = [{**_p(x["playerName"], x.get("backNumber"), "투수",
               [f"{x.get('pitcherWin') or 0}승 {x.get('pitcherLose') or 0}패", f"ERA {x['pitcherEra']:.2f}" if x.get("pitcherEra") is not None else ""]),
          "_qs": (x.get("pitcherQs") or 0) if cat == "kbo" else ((x.get("pitcherStart") or 0) if (x.get("pitcherStart") or 0) >= 5 else 0),
          "_ip": x.get("pitcherGameCount") or 0} for x in pi if x.get("playerName")]
    for p, x in zip(P, [x for x in pi if x.get("playerName")]):
        try:
            a, _, fr = str(x.get("pitcherInning") or "0").partition(" ")
            p["_inn"] = float(a) + (1 / 3 if fr.startswith("1") else 2 / 3 if fr.startswith("2") else 0)
        except ValueError:
            p["_inn"] = 0
    if cat == "npb":
        return _bb_groups(H, P, None, "_qs"), f"네이버 스포츠 · {yr} 시즌 기록"
    if cat == "kbo":
        return _bb_groups(H, P, "퀄리티스타트 1회 이상", "_qs", "퀄리티스타트 기록 없음"), f"네이버 스포츠 · {yr} 시즌 기록"
    return _bb_groups(H, P, "시즌 선발 등판 5경기 이상", "_qs", "선발 등판 5경기 미만"), f"네이버 스포츠 · {yr} 시즌 기록"


def _naver_mlb_code(ko_name):
    def f():
        import datetime as D
        m = {}
        for d in ("2026-08-01", "2026-08-08", "2026-08-15"):
            e = (D.date.fromisoformat(d) + D.timedelta(days=6)).isoformat()
            for x in (_j("https://api-gw.sports.naver.com/schedule/games?fields=basic&upperCategoryId=wbaseball&categoryId=mlb"
                         f"&fromDate={d}&toDate={e}&size=500", NAVER_H).get("result") or {}).get("games") or []:
                for k in ("home", "away"):
                    if x.get(k + "TeamCode") and x.get(k + "TeamName"):
                        m[x[k + "TeamName"].replace(" ", "")] = x[k + "TeamCode"]
        return m
    m = T._cached(("nvmlb",), 7 * 86400, lambda prev: f() or prev) or {}
    n = (ko_name or "").replace(" ", "")
    n = {"시카고화이트삭스": "시카고W", "시카고컵스": "시카고C"}.get(n, n)
    if n in m:
        return m[n]
    c = [v for k, v in m.items() if k in n or n in k]
    return c[0] if len(c) == 1 else None


def _bb_groups(H, P, sp_basis, sk, rest_basis=""):
    """근거가 있는 것만 선발로 분류. 근거 없는 나머지는 '그 외'로만 표시(불펜이라 단정하지 않음)."""
    H.sort(key=lambda p: -p["_ab"]); reg = H[:9]
    if sp_basis is None:   # 선발 등판 근거 데이터 없음(NPB 등): 투수 한 묶음, 이닝순
        P.sort(key=lambda p: -p.get("_inn", 0))
        return [g for g in [_g("선발 타자", reg, "시즌 타수 상위 9명"), _g("그 외 타자", H[9:], "타수 10위 이하"),
                            _g("투수", P, "선발/불펜 구분 정보 없음 · 이닝순")] if g["ps"]]
    sp = sorted([p for p in P if p[sk] > 0], key=lambda p: -p[sk]); rp = [p for p in P if p[sk] <= 0]
    return [g for g in [_g("선발 타자", reg, "시즌 타수 상위 9명"), _g("선발 투수", sp, sp_basis),
                        _g("그 외 타자", H[9:], "타수 10위 이하"), _g("그 외 투수", rp, rest_basis)] if g["ps"]]


# ---------- MLB: 공식 statsapi ----------
MLBPOS = {"P": "투수", "C": "포수", "1B": "1루수", "2B": "2루수", "3B": "3루수", "SS": "유격수", "LF": "좌익수", "CF": "중견수", "RF": "우익수", "DH": "지명타자", "OF": "외야수", "TWP": "투타겸업"}


def _mlb_id(en):
    ts = T._cached(("mlbteams",), 86400, lambda prev: _j("https://statsapi.mlb.com/api/v1/teams?sportId=1").get("teams"))
    n = (en or "").lower()
    for t in ts or []:
        if n and (t["name"].lower() == n or t.get("teamName", "").lower() in n.split() or n.endswith(t.get("teamName", "").lower())):
            return t["id"]


def _mlb(en):
    mid = _mlb_id(en)
    if not mid:
        return None
    y = time.localtime().tm_year
    d = _j(f"https://statsapi.mlb.com/api/v1/teams/{mid}/roster?rosterType=active&season={y}"
           f"&hydrate=person(stats(type=season,season={y},group=[hitting,pitching]))")
    H, P = [], []
    for r in d.get("roster") or []:
        pe, pc = r.get("person") or {}, (r.get("position") or {}).get("abbreviation")
        sts = {s["group"]["displayName"]: (s.get("splits") or [{}])[0].get("stat") or {} for s in pe.get("stats") or [] if s.get("group")}
        if pc == "P":
            s = sts.get("pitching") or {}
            P.append({**_p(pe.get("fullName"), r.get("jerseyNumber"), "투수", [f"{s['wins']}승 {s['losses']}패" if "wins" in s else "", f"ERA {s['era']}" if s.get("era") else ""]), "_gs": (s.get("gamesStarted") or 0) if (s.get("gamesStarted") or 0) >= 5 else 0})
        else:
            s = sts.get("hitting") or {}
            H.append({**_p(pe.get("fullName"), r.get("jerseyNumber"), MLBPOS.get(pc, pc or ""), [f"타율 {s['avg']}" if s.get("avg") else "", f"{s['homeRuns']}홈런" if "homeRuns" in s else "", f"{s['rbi']}타점" if "rbi" in s else ""]), "_ab": s.get("atBats") or 0})
    if not (H or P):
        return None
    return _bb_groups(H, P, "시즌 선발 등판 5경기 이상", "_gs", "선발 등판 5경기 미만"), f"MLB 공식 기록 · {y} 시즌"


# ---------- NHL: 공식 api-web ----------
HPOS = {"C": "센터", "L": "레프트윙", "R": "라이트윙", "D": "디펜스", "G": "골리"}


def _nhl(en):
    st = T._cached(("nhlstand",), 86400, lambda prev: _j("https://api-web.nhle.com/v1/standings/now").get("standings"))
    n, ab = (en or "").lower(), None
    for t in st or []:
        nm = ((t.get("teamName") or {}).get("default") or "").lower()
        if n and (nm == n or nm.replace("é", "e") == n):
            ab = (t.get("teamAbbrev") or {}).get("default")
    if not ab:
        return None
    d = _j(f"https://api-web.nhle.com/v1/club-stats/{ab}/now")
    nm = lambda x: f"{(x.get('firstName') or {}).get('default','')} {(x.get('lastName') or {}).get('default','')}".strip()
    ps = [{**_p(nm(x), None, HPOS.get(x.get("positionCode"), ""), [f"{x.get('gamesPlayed',0)}경기", f"{x.get('goals',0)}골", f"{x.get('assists',0)}도움", f"{x.get('points',0)}포인트"]), "_k": (1 if x.get("positionCode") == "D" else 0, -(x.get("points") or 0))} for x in d.get("skaters") or []]
    ps += [{**_p(nm(x), None, "골리", [f"{x.get('gamesPlayed',0)}경기", f"{x.get('wins',0)}승", f"세이브율 {x['savePercentage']:.3f}".replace("0.", ".") if x.get("savePercentage") is not None else ""]), "_k": (2, -(x.get("gamesPlayed") or 0))} for x in d.get("goalies") or []]
    if not ps:
        return None
    return [_g("선수 명단", sorted(ps, key=lambda p: p["_k"]), "포지션별 · 포인트순")], f"NHL 공식 기록 · {d.get('season','')[:4]} 시즌"


# ---------- 배구: V리그 (네이버 스포츠 시즌 기록) ----------
KOVO = {1171: ("kovo", "1001"), 1175: ("kovo", "1002"), 1172: ("kovo", "1004"), 1170: ("kovo", "1005"),
        1173: ("kovo", "1006"), 4144: ("kovo", "1008"), 1176: ("kovo", "1009"),
        1181: ("wkovo", "2001"), 1178: ("wkovo", "2002"), 3820: ("wkovo", "2003"), 1180: ("wkovo", "2004"),
        1179: ("wkovo", "2005"), 1182: ("wkovo", "2006"), 2162: ("wkovo", "2007")}


def _kovo(tid):
    cat, code = KOVO[tid]
    base = "https://api-gw.sports.naver.com/statistics/categories/" + cat + "/seasons"
    seasons = [x for x in (_j(base, NAVER_H).get("result") or {}).get("seasons") or [] if x.get("isEnable") == "Y"]
    seasons.sort(key=lambda x: x.get("seasonCode") or "", reverse=True)
    for se in seasons[:2]:
        rows = (_j(f"{base}/{se['seasonCode']}/players?pageSize=300", NAVER_H).get("result") or {}).get("seasonPlayerStats") or []
        rows = [x for x in rows if str(x.get("teamId")) == code and x.get("playerName")]
        if rows:
            break
    else:
        return None
    def pos(x):
        try:
            v = json.loads(x.get("profile") or "{}").get("position") or ""
        except Exception:
            v = ""
        return v or {"OH": "아웃사이드 히터", "OP": "아포짓 스파이커", "MB": "미들 블로커", "S": "세터", "L": "리베로"}.get(x.get("position") or "", "")
    ps = []
    for x in rows:
        if pos(x) == "리베로":
            dg = x.get("digSuccess") or 0
            rt, ra = x.get("receiveTotal") or 0, x.get("receiveAccurate") or 0
            st = [f"디그 {dg}", f"리시브 정확 {ra * 100 / rt:.1f}%" if rt else ""]
        else:
            ht = x.get("hittingTotal") or 0
            st = [f"{x.get('point') or 0}득점", f"공격 {(x.get('hittingSuccess') or 0) * 100 / ht:.1f}%" if ht else "",
                  f"블로킹 {x.get('blockingSuccess') or 0}", f"서브득점 {x.get('servesSuccess') or 0}"]
        ps.append({**_p(x["playerName"], x.get("backNumber"), pos(x), st), "_set": x.get("matchesSet") or 0})
    ps.sort(key=lambda p: -p["_set"])
    top = [p for p in ps if p["_set"] > 0][:7]
    rest = [p for p in ps if p not in top]
    return ([_g("주전", top, "시즌 출전 세트 상위 7명"), _g("후보", rest, "")],
            f"네이버 스포츠 · {se.get('title')} 시즌 기록")


def get(t):
    kind, tid = t["kind"], t["id"]
    def f(prev):
        r = None
        if kind == "football":
            r = _football(tid, t["roster"])
        elif kind == "basketball":
            r = _basketball(tid, t["roster"], t["past"])
        elif kind == "baseball":
            if tid in KBO:
                r = _kbo(tid)
            elif tid in NPB:
                code, lg = NPB[tid]
                r = _kbo(tid, "npb", code, "&league=PL" if lg == "P" else "")
            else:
                code = _naver_mlb_code(t["name"])
                r = (_kbo(tid, "mlb", code) if code else None) or _mlb(t.get("en") or t["name"])
        elif kind == "hockey":
            r = _nhl(t.get("en") or t["name"])
        elif kind == "volleyball" and tid in KOVO:
            r = _kovo(tid)
        if not r and t["roster"]:   # 기록 근거가 없으면 포지션순 단일 명단
            r = [_g("선수 명단", [_p(p["name"], p["no"], p["pos"]) for p in t["roster"]], "포지션순")], "API-Sports"
        if not r:
            return {"groups": [], "src": ""}
        for g in r[0]:
            for p in g["ps"]:
                for k in [k for k in p if k.startswith("_")]:
                    p.pop(k)
        return {"groups": [g for g in r[0] if g["ps"]], "src": r[1]}
    return T._cached(("roster", kind, tid), TTL, lambda prev: f(prev) or prev, 900) or {"groups": [], "src": ""}

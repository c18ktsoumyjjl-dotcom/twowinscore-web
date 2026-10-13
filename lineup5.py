"""확정 라인업 5종목 (실제 발표/기록만, 추측 없음). 반환: {ok, kind, pre, why, src, home:{...}, away:{...}}.
축구=lineup.football (ESPN 확인 규칙 유지), 농구=lineup.basketball(네이버 KBL/ESPN NBA 선발 표시),
배구=네이버 문자중계 세트별 lineup, 하키=NHL 시프트차트(1P 00:00) + 박스스코어 골리, 야구=lineup.get 타순·수비·선발투수."""
import html
from datetime import timedelta
from zoneinfo import ZoneInfo
import data, lineup as L
from pname import ko

PRE = {"ok": True, "pre": True}


def _team(g, sd, **kw):
    return {"name": g.get(sd), "logo": g.get(sd + "_logo") or "", "players": [], "bench": [], **kw}


def build(g):
    k = g.get("kind")
    try:
        f = {"football": _fb, "basketball": _bk, "volleyball": _vb, "hockey": _hk, "baseball": _bb}.get(k)
        r = f(g) if f else None
    except Exception:
        r = None
    r = r or dict(PRE)
    r["kind"] = k
    r["state"] = data.state(g)
    return r


# ---- 축구
def _fb(g):
    lu = L.football(g)
    if not lu or lu.get("none"):
        return {**PRE, "why": (lu or {}).get("why")}
    out = {"ok": True, "src": lu.get("src") or "API-Sports"}
    for sd in ("home", "away"):
        t = lu[sd]
        mk = lambda p: {"id": p.get("id"), "no": p.get("no"), "pos": p.get("pos"), "name": p.get("ko") or ko("football", p.get("id"), p.get("name")),
                        "photo": f"https://media.api-sports.io/football/players/{p['id']}.png" if str(p.get("id") or "").isdigit() else None}
        pl = []
        if t.get("pitch"):
            rows = {}
            for p in t["xi"]:
                r, c = map(int, str(p.get("g")).split(":"))
                rows.setdefault(r, []).append((c, p))
            n = max(rows)
            for r, v in rows.items():
                v.sort(key=lambda z: z[0])
                for i, (c, p) in enumerate(v):
                    pl.append({**mk(p), "x": (i + 1) / (len(v) + 1), "y": 0.84 - (r - 1) * 0.70 / max(1, n - 1)})
        out[sd] = _team(g, sd, form=t.get("form") or "", coach=t.get("coach") or "", pitch=bool(t.get("pitch")),
                        players=pl, xi=[mk(p) for p in t["xi"]], bench=[f"{p.get('no') or ''} {mk(p)['name']}".strip() for p in t.get("subs") or []])
    out["pitch"] = out["home"]["pitch"] and out["away"]["pitch"]
    return out


# ---- 농구
BK = {"가드": [(.30, .30), (.70, .30)], "포워드": [(.17, .60), (.83, .60)], "센터": [(.5, .80)]}


def _bk(g):
    lu = L.basketball(g)
    if not lu or not lu.get("home"):
        return None
    src = lu.get("src") or ""
    if "네이버" in src:
        ph = lambda p: f"https://sports-phinf.pstatic.net/player/kbl/default/{p['id']}.png"
    elif "ESPN" in src:
        ph = lambda p: f"https://a.espncdn.com/i/headshots/nba/players/full/{p['id']}.png"
    else:
        ph = lambda p: None
    out = {"ok": True, "src": src}
    for sd in ("home", "away"):
        st = [p for p in lu.get(sd) or [] if p.get("st")]
        if len(st) != 5:
            return {**PRE, "src": src}
        free = [c for v in BK.values() for c in v]
        used, pl = [], []
        for p in st:
            c = next((c for c in BK.get(p.get("pos"), []) if c not in used), None)
            if c:
                used.append(c); pl.append((p, c))
        for p in st:
            if all(p is not q for q, _ in pl):
                c = next(c for c in free if c not in used); used.append(c); pl.append((p, c))
        nm = lambda p: ko("basketball", p.get("id"), p.get("name"))
        out[sd] = _team(g, sd, players=[{"x": c[0], "y": c[1], "no": p.get("no"), "name": nm(p), "pos": p.get("pos"), "photo": ph(p)} for p, c in pl],
                        bench=[f"{p.get('no') or ''} {nm(p)}".strip() for p in lu[sd] if not p.get("st")])
    return out


# ---- 배구 (네이버 세트별 선발)
VB = {1: (.80, .70), 2: (.80, .26), 3: (.50, .26), 4: (.20, .26), 5: (.20, .70), 6: (.50, .70)}


def _vb(g):
    import naver_kr
    x, swap = naver_kr._find(g)
    if not x:
        return {**PRE, "why": "nosrc"}
    gid = x["gameId"]
    live = data.state(g) == "live"
    t = L._cache(("lu5vb", gid), 20 if live else 600,
                 lambda: (L._j(f"https://api-gw.sports.naver.com/schedule/games/{gid}/relay", L.NAVER_H).get("result") or {}).get("textRelayData"))
    lu = (t or {}).get("lineup") or {}
    if not lu.get("homePlayerName1") or not lu.get("awayPlayerName1"):
        return {**PRE, "src": "네이버 스포츠"}
    cat = x.get("categoryId") or "kovo"
    out = {"ok": True, "src": "네이버 스포츠 (세트별 선발)", "set": lu.get("set")}
    for sd in ("home", "away"):
        ns = ("away" if sd == "home" else "home") if swap else sd
        pl = []
        for i in range(1, 7):
            n = lu.get(f"{ns}PlayerName{i}")
            if not n:
                return {**PRE, "src": "네이버 스포츠"}
            pl.append({"x": VB[i][0], "y": VB[i][1], "no": None, "name": n, "pos": lu.get(f"{ns}PlayerPosition{i}"),
                       "photo": f"https://sports-phinf.pstatic.net/player/{cat}/default/{lu.get(f'{ns}PlayerCode{i}')}.png"})
        lb = [lu.get(f"{ns}PlayerName{i}") for i in range(7, 10) if lu.get(f"{ns}PlayerName{i}") and lu.get(f"{ns}PlayerPosition{i}") == "L"]
        out[sd] = _team(g, sd, form=f"{lu.get('set')}세트 선발" if lu.get("set") else "", players=pl, bench=[f"리베로 {n}" for n in lb])
    return out


# ---- 하키 (NHL)
def _nhl_id(g):
    if g.get("league") != 57:
        return None
    for dd in (0, -1, 1):
        day = (g["start"].astimezone(ZoneInfo("America/New_York")) + timedelta(days=dd)).strftime("%Y-%m-%d")
        sc = L._cache(("nhlsc", day), 600, lambda: L._j(f"https://api-web.nhle.com/v1/score/{day}"))
        for x in (sc or {}).get("games") or []:
            f = lambda t: ((t.get("name") or t.get("commonName") or {}).get("default") or "").strip().lower()
            h, a = f(x["homeTeam"]), f(x["awayTeam"])
            if h and a and (g.get("home_en") or "").lower().endswith(h) and (g.get("away_en") or "").lower().endswith(a):
                return x["id"]
    return None


def _hk(g):
    nid = _nhl_id(g)
    if not nid:
        return {**PRE, "why": "nosrc"}
    st = data.state(g)
    if st == "scheduled":
        return {**PRE, "src": "NHL"}
    ttl = 60 if st == "live" else 3600
    pp = L._cache(("nhlpbp", nid), ttl, lambda: L._j(f"https://api-web.nhle.com/v1/gamecenter/{nid}/play-by-play"))
    sh = L._cache(("nhlsh", nid), ttl, lambda: L._j(f"https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={nid}"))
    bx = L._cache(("nhlbx", nid), ttl, lambda: L._j(f"https://api-web.nhle.com/v1/gamecenter/{nid}/boxscore"))
    if not pp or not sh:
        return {**PRE, "src": "NHL"}
    R = {r["playerId"]: r for r in pp.get("rosterSpots") or []}
    start = {s["playerId"] for s in sh.get("data") or [] if s.get("period") == 1 and s.get("startTime") == "00:00"}
    gst = set()
    for sd in ("homeTeam", "awayTeam"):
        for x in ((bx or {}).get("playerByGameStats") or {}).get(sd, {}).get("goalies") or []:
            if x.get("starter"):
                gst.add(x.get("playerId"))
    out = {"ok": True, "src": "NHL 공식 (시프트차트·박스스코어)"}
    for sd in ("home", "away"):
        t = pp[sd + "Team"]
        ps = [R[i] for i in start if i in R and R[i]["teamId"] == t["id"]]
        G = [p for p in ps if p["positionCode"] == "G"] or [R[i] for i in gst if i in R and R[i]["teamId"] == t["id"]]
        D = [p for p in ps if p["positionCode"] == "D"]
        F = sorted([p for p in ps if p["positionCode"] in ("L", "C", "R")], key=lambda p: "LCR".index(p["positionCode"]))
        if len(G) != 1 or len(D) + len(F) != 5:
            return {**PRE, "src": "NHL"}
        pos = [(.5, .86)] + ([(.30, .66), (.70, .66)] if len(D) == 2 else [(.2 + .6 * i / max(1, len(D) - 1), .66) for i in range(len(D))])
        fx = [(.20, .32), (.50, .24), (.80, .32)] if len(F) == 3 else [(.2 + .6 * i / max(1, len(F) - 1), .30) for i in range(len(F))]
        pl = []
        for p, c in zip(G + D + F, pos + fx):
            en = f"{(p.get('firstName') or {}).get('default', '')[:1]}. {(p.get('lastName') or {}).get('default', '')}"
            pl.append({"x": c[0], "y": c[1], "no": p.get("sweaterNumber"), "name": ko("hockey", p.get("playerId"), en), "pos": p["positionCode"], "photo": p.get("headshot")})
        out[sd] = _team(g, sd, form="G · D2 · F3", players=pl)
    return out


# ---- 야구
BB = {"투수": (.5, .62), "포수": (.5, .90), "1루수": (.73, .60), "2루수": (.62, .44), "유격수": (.38, .44), "3루수": (.27, .60), "좌익수": (.17, .24), "중견수": (.5, .12), "우익수": (.83, .24)}


def _bb(g):
    lu = L.get(g)
    if not lu:
        return {**PRE, "why": "nosrc"}
    out = {"ok": True, "src": lu.get("src") or ""}
    for sd in ("away", "home"):
        t = lu.get(sd) or {}
        bat = [b for b in t.get("bat") or [] if not b.get("sub")]
        pit = t.get("pit") or []
        if len(bat) < 9 or not pit:
            return {**PRE, "src": out["src"]}
        sp = pit[0]
        pl = [{"x": BB["투수"][0], "y": BB["투수"][1], "o": "SP", "name": sp.get("name"), "pos": "투수"}]
        for b in bat:
            if b.get("pos") in BB and b["pos"] != "투수":
                pl.append({"x": BB[b["pos"]][0], "y": BB[b["pos"]][1], "o": b.get("o"), "name": b.get("name"), "pos": b["pos"]})
        out[sd] = _team(g, sd, form=f"선발 {sp.get('name')}", players=pl,
                        bat=[{"o": b.get("o"), "name": b.get("name"), "pos": b.get("pos"), "avg": b.get("avg")} for b in bat],
                        sp={"name": sp.get("name"), "era": sp.get("era")})
    return out

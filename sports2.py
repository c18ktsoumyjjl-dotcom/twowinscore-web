"""축구·아이스하키 (API-Sports football v3 / hockey v1). 확인된 값만 쓴다."""
import os, json, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
HOSTS = {"football": "https://v3.football.api-sports.io", "hockey": "https://v1.hockey.api-sports.io"}
LEAGUES = {
    ("football", 39): "EPL", ("football", 140): "라리가", ("football", 135): "세리에A", ("football", 78): "분데스리가",
    ("football", 61): "리그1", ("football", 292): "K리그1", ("football", 2): "챔피언스리그",
    ("hockey", 57): "NHL", ("hockey", 35): "KHL",
}
SEASON = {("football", 292): 2026, ("hockey", 57): 2026, ("hockey", 35): 2026}  # 나머지 축구 유럽 리그는 2026(=2026-27)
FB_LIVE = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT"}
FB_FIN = {"FT", "AET", "PEN"}
HK_LIVE = {"P1", "P2", "P3", "OT", "PT", "BT"}
HK_FIN = {"FT", "AOT", "AP"}
CANC = {"CANC", "ABD", "AWD", "WO"}
POST = {"PST", "POST", "SUSP"}


def get(kind, path, params):
    url = HOSTS[kind] + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": os.environ.get("API_SPORTS_KEY", "")})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode())
    if body.get("errors"):
        raise RuntimeError("api errors")
    return body.get("response") or []


def is_live(kind, st):
    return st in (FB_LIVE if kind == "football" else HK_LIVE)


def state(kind, st):
    if is_live(kind, st):
        return "live"
    if st in (FB_FIN if kind == "football" else HK_FIN):
        return "final"
    if st in CANC:
        return "cancelled"
    if st in POST:
        return "postponed"
    if st in ("NS", "TBD"):
        return "scheduled"
    return "other"


def _period(kind, st, elapsed):
    if kind == "football":
        e = f" {elapsed}'" if elapsed else ""
        return {"1H": "전반" + e, "HT": "하프타임", "2H": "후반" + e, "ET": "연장" + e, "BT": "연장 휴식",
                "P": "승부차기", "LIVE": "진행 중", "INT": "중단", "FT": "종료", "AET": "연장 종료", "PEN": "승부차기 종료"}.get(st, st)
    return {"P1": "1피리어드", "P2": "2피리어드", "P3": "3피리어드", "OT": "연장", "PT": "슛아웃", "BT": "휴식",
            "FT": "종료", "AOT": "연장 종료", "AP": "슛아웃 종료"}.get(st, st)


def fetch_day(kind, day):
    out = []
    if kind == "football":
        for raw in get(kind, "/fixtures", {"date": day.isoformat(), "timezone": "Asia/Seoul"}):
            lg = (raw.get("league") or {}).get("id")
            if (kind, lg) not in LEAGUES:
                continue
            fx, t, goals = raw.get("fixture") or {}, raw.get("teams") or {}, raw.get("goals") or {}
            st = (fx.get("status") or {}).get("short") or ""
            sc = raw.get("score") or {}
            lines = []
            ht = sc.get("halftime") or {}
            if ht.get("home") is not None and ht.get("away") is not None:
                lines.append(["전반", ht["home"], ht["away"]])
                ft = sc.get("fulltime") or {}
                if ft.get("home") is not None:
                    lines.append(["후반", ft["home"] - ht["home"], ft["away"] - ht["away"]])
                et = sc.get("extratime") or {}
                if et.get("home") is not None:
                    lines.append(["연장", et["home"], et["away"]])
                pk = sc.get("penalty") or {}
                if pk.get("home") is not None:
                    lines.append(["승부차기", pk["home"], pk["away"]])
            out.append(_mk(kind, lg, fx.get("id"), fx.get("date"), st, t, goals.get("home"), goals.get("away"),
                           _period(kind, st, (fx.get("status") or {}).get("elapsed")), lines, raw.get("league", {}).get("round")))
    else:
        for raw in get(kind, "/games", {"date": day.isoformat(), "timezone": "Asia/Seoul"}):
            lg = (raw.get("league") or {}).get("id")
            if (kind, lg) not in LEAGUES:
                continue
            st = (raw.get("status") or {}).get("short") or ""
            sc, per = raw.get("scores") or {}, raw.get("periods") or {}
            lines = []
            for k, lab in (("first", "1P"), ("second", "2P"), ("third", "3P"), ("overtime", "OT"), ("penalties", "SO")):
                v = per.get(k)
                if v and "-" in str(v):
                    try:
                        h, a = [int(x) for x in str(v).split("-")]
                        lines.append([lab, h, a])
                    except ValueError:
                        pass
            out.append(_mk(kind, lg, raw.get("id"), raw.get("date"), st, raw.get("teams") or {}, sc.get("home"), sc.get("away"),
                           _period(kind, st, None), lines, None))
    return [g for g in out if g]


def _mk(kind, lg, gid, date, st, t, hs, as_, period, lines, rnd):
    try:
        start = datetime.fromisoformat(str(date).replace("Z", "+00:00")).astimezone(SEOUL)
    except Exception:
        return None
    h, a = t.get("home") or {}, t.get("away") or {}
    return {"key": f"{kind}:{lg}:{gid}", "id": gid, "kind": kind, "league": lg, "start": start.isoformat(), "status": st,
            "home": h.get("name") or "?", "away": a.get("name") or "?", "home_id": h.get("id"), "away_id": a.get("id"),
            "home_logo": h.get("logo"), "away_logo": a.get("logo"), "home_score": hs, "away_score": as_,
            "period": period, "lines": lines, "label": LEAGUES[(kind, lg)], "round": rnd}


def standings(kind, league):
    season = SEASON.get((kind, league), 2026)
    resp = get(kind, "/standings", {"league": league, "season": season})
    groups = []
    if kind == "football":
        for item in resp:
            for grp in ((item.get("league") or {}).get("standings") or []):
                rows = []
                name = ""
                for r in grp:
                    a = r.get("all") or {}
                    name = r.get("group") or name
                    rows.append({"rank": r.get("rank"), "team": (r.get("team") or {}).get("name"), "played": a.get("played"),
                                 "win": a.get("win"), "draw": a.get("draw"), "lose": a.get("lose"), "pts": r.get("points"),
                                 "gd": r.get("goalsDiff"), "form": r.get("form")})
                if rows and any((x.get("played") or 0) > 0 for x in rows):
                    groups.append([name if len(resp) > 1 or len((resp[0].get("league") or {}).get("standings") or []) > 1 else "", rows])
    else:
        buckets = {}
        for grp in resp:
            for r in grp:
                g = r.get("games") or {}
                name = (r.get("group") or {}).get("name") or ""
                buckets.setdefault(name, []).append({"rank": r.get("position"), "team": (r.get("team") or {}).get("name"), "played": g.get("played"),
                             "win": (g.get("win") or {}).get("total"), "lose": (g.get("lose") or {}).get("total"),
                             "otl": (g.get("lose_overtime") or {}).get("total"), "pts": r.get("points")})
        for name, rows in buckets.items():
            if any((x.get("played") or 0) > 0 for x in rows):
                rows.sort(key=lambda x: x.get("rank") or 99)
                groups.append([name, rows])
        conf = [gr for gr in groups if "Conference" in (gr[0] or "")]
        if conf:
            groups = conf
        elif len(groups) > 1:
            big = max(groups, key=lambda gr: len(gr[1]))
            groups = [big]
        KO = {"Eastern Conference": "동부 컨퍼런스", "Western Conference": "서부 컨퍼런스"}
        groups = [[KO.get(n, n), r] for n, r in groups]
    lab = f"{season}-{str(season + 1)[2:]}" if (kind, league) not in (("football", 292),) else str(season)
    return groups, lab


def events(g):
    """축구 득점·카드 (실제 이벤트만). [{t,hot}] 최신순."""
    if g["kind"] != "football":
        return None
    rows = get("football", "/fixtures/events", {"fixture": g["id"]})
    out = []
    for e in rows:
        tm = e.get("time") or {}
        minute = f"{tm.get('elapsed')}'" + (f"+{tm['extra']}" if tm.get("extra") else "")
        team = (e.get("team") or {}).get("name") or ""
        who = (e.get("player") or {}).get("name") or ""
        typ, det = e.get("type"), e.get("detail") or ""
        if typ == "Goal":
            kind = "자책골" if "Own" in det else "페널티 골" if "Penalty" in det else "골"
            if "Missed" in det:
                out.append({"t": f"😱 {minute} {team} {who} 페널티 실축", "hot": False}); continue
            ast = (e.get("assist") or {}).get("name")
            out.append({"t": f"⚽🔥 {minute} {team} {who} {kind}!!" + (f" (도움 {ast})" if ast else ""), "hot": True})
        elif typ == "Card":
            out.append({"t": f"{'🟥' if 'Red' in det else '🟨'} {minute} {team} {who} {'퇴장' if 'Red' in det else '경고'}", "hot": "Red" in det})
        elif typ == "Var" and det:
            out.append({"t": f"📺 {minute} VAR · {det}", "hot": False})
    out.reverse()
    return out

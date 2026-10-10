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
    ("football", 293): "K리그2", ("football", 660): "WK리그(여자)", ("football", 98): "J1리그", ("football", 99): "J2리그",
    ("football", 307): "사우디 리그", ("football", 40): "챔피언십", ("football", 3): "유로파리그", ("football", 848): "컨퍼런스리그",
    ("football", 253): "MLS", ("football", 5): "UEFA 네이션스리그", ("football", 10): "A매치 친선",
    ("hockey", 106): "아시아리그", ("hockey", 16): "핀란드 리가", ("hockey", 47): "스웨덴 SHL", ("hockey", 58): "AHL",
}
SEASON = {("football", 292): 2026, ("football", 98): 2027, ("football", 293): 2026, ("football", 660): 2026, ("football", 253): 2026, ("hockey", 57): 2026, ("hockey", 35): 2026}  # 나머지 축구 유럽 리그는 2026(=2026-27)
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
    from teams_ko import ko
    h, a = t.get("home") or {}, t.get("away") or {}
    hn, hen = ko(kind, h.get("id"), h.get("name") or "?")
    an, aen = ko(kind, a.get("id"), a.get("name") or "?")
    return {"home_en": hen, "away_en": aen,"key": f"{kind}:{lg}:{gid}", "id": gid, "kind": kind, "league": lg, "start": start.isoformat(), "status": st,
            "home": hn, "away": an, "home_id": h.get("id"), "away_id": a.get("id"),
            "home_logo": h.get("logo"), "away_logo": a.get("logo"), "home_score": hs, "away_score": as_,
            "period": period, "lines": lines, "label": LEAGUES[(kind, lg)], "round": rnd}


def standings(kind, league):
    from teams_ko import ko
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
                    tn, ten = ko(kind, (r.get("team") or {}).get("id"), (r.get("team") or {}).get("name"))
                    rows.append({"en": ten, "rank": r.get("rank"), "team": tn, "played": a.get("played"),
                                 "win": a.get("win"), "draw": a.get("draw"), "lose": a.get("lose"), "pts": r.get("points"),
                                 "gd": r.get("goalsDiff"), "form": (r.get("form") or "")[:5][::-1]})
                if rows and any((x.get("played") or 0) > 0 for x in rows):
                    groups.append([name if len(resp) > 1 or len((resp[0].get("league") or {}).get("standings") or []) > 1 else "", rows])
    else:
        buckets = {}
        for grp in resp:
            for r in grp:
                g = r.get("games") or {}
                name = (r.get("group") or {}).get("name") or ""
                tn, ten = ko(kind, (r.get("team") or {}).get("id"), (r.get("team") or {}).get("name"))
                buckets.setdefault(name, []).append({"tid": (r.get("team") or {}).get("id"), "en": ten, "rank": r.get("position"), "team": tn, "played": g.get("played"),
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
    if (kind, league) in (("football", 292), ("football", 293), ("football", 660), ("football", 253)):
        lab = str(season)
    elif (kind, league) == ("football", 98):
        lab = f"{season - 1}-{str(season)[2:]}"
    else:
        lab = f"{season}-{str(season + 1)[2:]}"
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
        from teams_ko import ko
        team = ko("football", (e.get("team") or {}).get("id"), (e.get("team") or {}).get("name") or "")[0]
        who = (e.get("player") or {}).get("name") or ""
        typ, det = e.get("type"), e.get("detail") or ""
        if typ == "Goal":
            kind = "자책골" if "Own" in det else "페널티 골" if "Penalty" in det else "골"
            if "Missed" in det or det == "Missed Penalty":
                out.append({"t": f"😱 {minute} {team} {who} 페널티 실축", "hot": False}); continue
            ast = (e.get("assist") or {}).get("name")
            out.append({"t": f"⚽🔥 {minute} {team} {who} {kind}!!" + (f" (도움 {ast})" if ast else ""), "hot": True})
        elif typ == "Card":
            out.append({"t": f"{'🟥' if 'Red' in det else '🟨'} {minute} {team} {who} {'퇴장' if 'Red' in det else '경고'}", "hot": "Red" in det})
        elif typ == "subst":
            ast = (e.get("assist") or {}).get("name")
            out.append({"t": f"🔁 {minute} {team} 선수 교체 · {who}" + (f" ↔ {ast}" if ast else ""), "hot": False})
        elif typ == "Var" and det:
            out.append({"t": f"📺 {minute} VAR · " + {"Goal cancelled": "골 취소", "Goal Disallowed": "골 취소", "Penalty confirmed": "페널티 확정",
                 "Penalty cancelled": "페널티 취소", "Card upgrade": "카드 상향", "Goal confirmed": "골 인정"}.get(det, det) + (f" ({team})" if team else ""), "hot": False})
    out.reverse()
    return out


def _norm(kind, x):
    """축구 fixture / 하키 game 원본 → (ts, 상태, hid, aid, hname, aname, hs, as)."""
    from teams_ko import ko
    if kind == "football":
        fx, t, gl = x.get("fixture") or {}, x.get("teams") or {}, x.get("goals") or {}
        st, ts, hs, a_ = (fx.get("status") or {}).get("short"), fx.get("timestamp") or 0, gl.get("home"), gl.get("away")
    else:
        t, sc = x.get("teams") or {}, x.get("scores") or {}
        st, ts, hs, a_ = (x.get("status") or {}).get("short"), x.get("timestamp") or 0, sc.get("home"), sc.get("away")
    h, a = t.get("home") or {}, t.get("away") or {}
    return ts, st, h.get("id"), a.get("id"), ko(kind, h.get("id"), h.get("name"))[0], ko(kind, a.get("id"), a.get("name"))[0], hs, a_


def _done(kind, n):
    return n[1] in (FB_FIN if kind == "football" else HK_FIN) and n[6] is not None and n[7] is not None


def team_form(kind, tid, before_ts, league=None):
    """최근 종료 5경기 (최근순). 축구는 모든 대회, 하키는 해당 리그 시즌."""
    if kind == "football":
        resp = get(kind, "/fixtures", {"team": tid, "last": 10, "timezone": "Asia/Seoul"})
    else:
        resp = get(kind, "/games", {"team": tid, "league": league, "season": SEASON.get((kind, league), 2026), "timezone": "Asia/Seoul"})
    rows = [n for n in (_norm(kind, x) for x in resp) if _done(kind, n) and n[0] < before_ts]
    rows.sort(reverse=True)
    out = []
    for ts, _st, hid, aid, hn, an, hs, as_ in rows[:5]:
        home = hid == tid
        me, op = (hs, as_) if home else (as_, hs)
        out.append({"date": datetime.fromtimestamp(ts, SEOUL).strftime("%m/%d"), "opp": an if home else hn,
                    "ha": "홈" if home else "원정", "me": me, "op": op, "r": "W" if me > op else ("L" if me < op else "D")})
    return out


def h2h(kind, a, b, before_ts):
    path = "/fixtures/headtohead" if kind == "football" else "/games/h2h"
    resp = get(kind, path, {"h2h": f"{a}-{b}", "timezone": "Asia/Seoul"})
    rows = [n for n in (_norm(kind, x) for x in resp) if _done(kind, n) and n[0] < before_ts]
    rows.sort(reverse=True)
    return [{"date": datetime.fromtimestamp(ts, SEOUL).strftime("%Y.%m.%d"), "home": hn, "away": an, "hs": hs, "as": as_,
             "hid": hid, "aid": aid} for ts, _st, hid, aid, hn, an, hs, as_ in rows[:5]]

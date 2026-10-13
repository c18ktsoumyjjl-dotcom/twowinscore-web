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
    ("football", 17): "AFC 챔피언스리그 엘리트", ("football", 18): "AFC 챔피언스리그2",
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
    if st == "SUSP":
        return "live"          # 일시 중단도 진행 중 섹션에 남긴다(종료로 보지 않음)
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


def fetch_day(kind, day, other=None):
    """other 리스트를 주면 화이트리스트 밖 경기(기타 리그)를 거기에 담아요(같은 API 호출, 추가 비용 없음)."""
    out = []
    if kind == "football":
        for raw in get(kind, "/fixtures", {"date": day.isoformat(), "timezone": "Asia/Seoul"}):
            lg = (raw.get("league") or {}).get("id")
            olab = None
            if (kind, lg) not in LEAGUES:
                if other is None:
                    continue
                olab = other_label(raw)
            fx, t, goals = raw.get("fixture") or {}, raw.get("teams") or {}, raw.get("goals") or {}
            st = (fx.get("status") or {}).get("short") or ""
            sc = raw.get("score") or {}
            lines = []
            ht = sc.get("halftime") or {}
            elapsed = (fx.get("status") or {}).get("elapsed")
            started = st in FB_FIN or (elapsed or 0) >= 45 or (fx.get("periods") or {}).get("second")
            if started and ht.get("home") is not None and ht.get("away") is not None:
                lines.append(["전반", ht["home"], ht["away"]])
                ft = sc.get("fulltime") or {}
                if ft.get("home") is not None:
                    lines.append(["후반", ft["home"] - ht["home"], ft["away"] - ht["away"]])
                elif st in ("2H", "INT", "LIVE") and goals.get("home") is not None and goals.get("away") is not None:
                    lines.append(["후반", goals["home"] - ht["home"], goals["away"] - ht["away"]])  # 진행 중 후반 = 현재 - 전반
                et = sc.get("extratime") or {}
                if et.get("home") is not None and st in ("ET", "BT", "P", "AET", "PEN"):
                    lines.append(["연장", et["home"], et["away"]])
                pk = sc.get("penalty") or {}
                if pk.get("home") is not None and st in ("P", "PEN"):
                    lines.append(["승부차기", pk["home"], pk["away"]])
            out.append(_mk(kind, lg, fx.get("id"), fx.get("date"), st, t, goals.get("home"), goals.get("away"),
                           _period(kind, st, (fx.get("status") or {}).get("elapsed")), lines, raw.get("league", {}).get("round"),
                           (fx.get("status") or {}).get("long"), _fb_reason(raw), olab))
            if olab:
                other.append(out.pop())
    else:
        for raw in get(kind, "/games", {"date": day.isoformat(), "timezone": "Asia/Seoul"}):
            lg = (raw.get("league") or {}).get("id")
            olab = None
            if (kind, lg) not in LEAGUES:
                if other is None:
                    continue
                olab = other_label(raw)
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
                           _period(kind, st, None), lines, None, (raw.get("status") or {}).get("long"), None, olab))
            if olab:
                other.append(out.pop())
    return [g for g in out if g]


COUNTRY_KO = {"England": "잉글랜드", "Spain": "스페인", "Italy": "이탈리아", "Germany": "독일", "France": "프랑스",
              "Netherlands": "네덜란드", "Portugal": "포르투갈", "Belgium": "벨기에", "Scotland": "스코틀랜드", "Turkey": "튀르키예",
              "Greece": "그리스", "Russia": "러시아", "Ukraine": "우크라이나", "Poland": "폴란드", "Czech-Republic": "체코",
              "Austria": "오스트리아", "Switzerland": "스위스", "Denmark": "덴마크", "Sweden": "스웨덴", "Norway": "노르웨이",
              "Finland": "핀란드", "Croatia": "크로아티아", "Serbia": "세르비아", "Romania": "루마니아", "Hungary": "헝가리",
              "USA": "미국", "Canada": "캐나다", "Mexico": "멕시코", "Brazil": "브라질", "Argentina": "아르헨티나",
              "Chile": "칠레", "Colombia": "콜롬비아", "Uruguay": "우루과이", "Peru": "페루", "Ecuador": "에콰도르",
              "Japan": "일본", "China": "중국", "South-Korea": "한국", "Australia": "호주", "Saudi-Arabia": "사우디",
              "Iran": "이란", "Qatar": "카타르", "UAE": "UAE", "India": "인도", "Indonesia": "인도네시아", "Thailand": "태국",
              "Vietnam": "베트남", "Egypt": "이집트", "Morocco": "모로코", "Nigeria": "나이지리아", "Ghana": "가나",
              "South-Africa": "남아공", "World": "국제", "Europe": "유럽", "Asia": "아시아", "Cuba": "쿠바",
              "Israel": "이스라엘", "Slovakia": "슬로바키아", "Slovenia": "슬로베니아", "Bulgaria": "불가리아", "Ireland": "아일랜드",
              "Wales": "웨일스", "Iceland": "아이슬란드", "Lithuania": "리투아니아", "Latvia": "라트비아", "Estonia": "에스토니아",
              "Kazakhstan": "카자흐스탄", "Belarus": "벨라루스", "Paraguay": "파라과이", "Bolivia": "볼리비아", "Venezuela": "베네수엘라", "Albania": "알바니아", "Bosnia": "보스니아", "Cyprus": "키프로스", "Georgia": "조지아", "Armenia": "아르메니아", "Azerbaijan": "아제르바이잔", "Moldova": "몰도바", "North-Macedonia": "북마케도니아", "Montenegro": "몬테네그로", "Kosovo": "코소보", "Luxembourg": "룩셈부르크", "Malta": "몰타", "Algeria": "알제리", "Tunisia": "튀니지", "Kenya": "케냐", "Costa-Rica": "코스타리카", "Honduras": "온두라스", "Guatemala": "과테말라", "Puerto-Rico": "푸에르토리코", "Philippines": "필리핀", "Malaysia": "말레이시아", "Singapore": "싱가포르", "Taiwan": "대만", "Hong-Kong": "홍콩", "New-Zealand": "뉴질랜드"}


def other_label(raw):
    lg = raw.get("league") or {}
    c = lg.get("country") if isinstance(lg.get("country"), str) else ((raw.get("country") or {}).get("name") or "")
    c = COUNTRY_KO.get(c, c or "")
    n = lg.get("name") or "기타"
    return (c + " " + n).strip()[:60]


def _fb_reason(raw):
    """이벤트에 중단 사유 코멘트가 실제로 있을 때만. 없으면 None (지어내지 않는다)."""
    for e in reversed(raw.get("events") or []):
        c = str(e.get("comments") or "")
        if any(w in c.lower() for w in ("interrupt", "suspend", "abandon", "weather", "rain", "storm", "light", "crowd", "fan")):
            return c[:60]
    return None


def _mk(kind, lg, gid, date, st, t, hs, as_, period, lines, rnd, slong=None, reason=None, olab=None):
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
            "period": period, "lines": lines, "label": olab or LEAGUES[(kind, lg)], "round": rnd, **({"other": 1} if olab else {}),
            "status_long": slong, "halt_reason": reason}


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


def raw_events(g):
    return get("football", "/fixtures/events", {"fixture": g["id"]})


def _half(e):
    tm = e.get("time") or {}
    el = tm.get("elapsed") or 0
    if "Shootout" in str(e.get("comments") or ""):
        return "승부차기"
    return "전반" if el <= 45 else "후반" if el <= 90 else "연장"


def goals(g, rows):
    """득점 목록 (실제 이벤트만). 실축·취소 제외. [{half,min,side,who,kind,ast}] 시간순."""
    from teams_ko import ko
    out = []
    for e in rows or []:
        if e.get("type") != "Goal":
            continue
        det = e.get("detail") or ""
        if "Missed" in det:
            continue
        tm = e.get("time") or {}
        tid = (e.get("team") or {}).get("id")
        side = "home" if tid == g.get("home_id") else "away" if tid == g.get("away_id") else None
        if side is None:
            continue
        half = _half(e)
        mn = "" if half == "승부차기" else f"{tm.get('elapsed')}'" + (f"+{tm['extra']}" if tm.get("extra") else "")
        out.append({"half": half, "min": mn, "side": side, "who": __import__("pname").ko("football", (e.get("player") or {}).get("id"), (e.get("player") or {}).get("name") or ""),
                    "kind": "자책골" if "Own" in det else "PK" if "Penalty" in det else "",
                    "ast": __import__("pname").ko("football", (e.get("assist") or {}).get("id"), (e.get("assist") or {}).get("name") or ""), "o": (tm.get("elapsed") or 0) * 100 + (tm.get("extra") or 0)})
    out.sort(key=lambda x: x["o"])
    return out


def events(g, rows=None):
    """축구 득점·카드 (실제 이벤트만). [{t,hot}] 최신순."""
    if g["kind"] != "football":
        return None
    if rows is None:
        rows = raw_events(g)
    out = []
    for e in rows:
        tm = e.get("time") or {}
        minute = f"{tm.get('elapsed')}'" + (f"+{tm['extra']}" if tm.get("extra") else "")
        from teams_ko import ko
        team = ko("football", (e.get("team") or {}).get("id"), (e.get("team") or {}).get("name") or "")[0]
        who = __import__("pname").ko("football", (e.get("player") or {}).get("id"), (e.get("player") or {}).get("name") or "")
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

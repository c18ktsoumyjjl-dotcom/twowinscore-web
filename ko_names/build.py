"""한글 선수 이름 사전 (API-Sports 선수 id → 한글). 실행: python3 ko_names/build.py
확인 규칙(둘 이상 키 일치만 채택, 추측 금지):
  · 같은 팀 + 등번호 + 포지션 군(GK/DF/MF/FW) 일치, 그리고 로마자 대조가 다른 선수를 가리키지 않을 것
  · 또는 같은 팀 + 한글 이름의 로마자 표기 = 영문 이름 (팀 안에서 1:1)
출처: 네이버 스포츠 시즌 선수 기록(팀·등번호·포지션), API-Sports 스쿼드. 키·비밀값 없음."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lineup as L, teamodds as T, ko_roman as K

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ko_names.json")
YEAR = time.localtime().tm_year
FPOS = {"Goalkeeper": "GK", "Defender": "DF", "Midfielder": "MF", "Attacker": "FW"}


def naver_players(cat, season):
    u = f"https://api-gw.sports.naver.com/statistics/categories/{cat}/seasons/{season}/players?pageSize=300"
    tids = sorted({p["teamId"] for p in (L._j(u, L.NAVER_H).get("result") or {}).get("seasonPlayerStats") or []})
    out = []
    for t in tids:
        out += (L._j(u + "&teamCode=" + t, L.NAVER_H).get("result") or {}).get("seasonPlayerStats") or []
    return out


def pair(api_sq, nv):
    """API 선수 목록 ↔ 네이버 한 팀 선수 목록 → {api_id: (ko, how)}"""
    res = {}
    byno = {}
    for p in nv:
        if p.get("backNumber") is not None:
            byno.setdefault(int(p["backNumber"]), []).append(p)
    for a in api_sq:
        ro = [p for p in nv if K.match(p.get("playerName"), a.get("name"))]
        ro_ok = ro[0] if len(ro) == 1 and sum(1 for b in api_sq if K.match(ro[0]["playerName"], b.get("name"))) == 1 else None
        nm = None
        if a.get("number") is not None:
            c = [p for p in byno.get(int(a["number"]), []) if p.get("position") == FPOS.get(a.get("position"))]
            nm = c[0] if len(c) == 1 else None
        if nm and not ro and K.looks_korean(a.get("name")) and K.candidates(nm["playerName"]) and K.close(nm["playerName"], a.get("name")) < 0.75:
            continue   # 한국식 영문 이름인데 한글 이름과 닮지 않음 → 등번호 바뀐 다른 선수일 수 있음
        if nm and ro and nm not in ro:
            continue   # 등번호와 이름이 서로 다른 선수를 가리킴 → 버림
        if ro_ok and nm and ro_ok is not nm:
            continue
        hit = ro_ok or nm
        if hit:
            res[str(a["id"])] = {"ko": hit["playerName"], "how": "num+pos+roman" if (ro_ok and nm) else ("roman" if ro_ok else "num+pos")}
    # 같은 한글 선수가 두 API 선수에 붙으면 둘 다 버림
    cnt = {}
    for v in res.values():
        cnt[v["ko"]] = cnt.get(v["ko"], 0) + 1
    return {k: v for k, v in res.items() if cnt[v["ko"]] == 1}


def football():
    nv = naver_players("kleague", YEAR) + naver_players("kleague2", YEAR)
    teams = {}
    for p in nv:
        teams.setdefault(p["teamId"], []).append(p)
    api_teams = []
    for lg in (292, 293):
        api_teams += [t["team"] for t in T._get("football", "/teams", {"league": lg, "season": YEAR})]
    out, stat = {}, []
    for t in api_teams:
        sq = (T._get("football", "/players/squads", {"team": t["id"]}) or [{}])[0].get("players") or []
        # 팀 짝: 로마자로 확인되는 선수 수가 가장 많고 3명 이상, 2위와 확실히 차이
        sc = sorted(((sum(1 for a in sq if any(K.match(p["playerName"], a["name"]) for p in ps)), tid) for tid, ps in teams.items()), reverse=True)
        if not sc or sc[0][0] < 3 or (len(sc) > 1 and sc[1][0] * 2 >= sc[0][0]):
            stat.append((t["name"], len(sq), 0, "team?"))
            continue
        m = pair(sq, teams[sc[0][1]])
        for k, v in m.items():
            out[k] = {**v, "team": t["id"]}
        stat.append((t["name"], len(sq), len(m), ""))
        time.sleep(0.3)
    return out, stat


import unicodedata, re as _re


def prev_season(cat):
    ss = sorted([x for x in (L._j(f"https://api-gw.sports.naver.com/statistics/categories/{cat}/seasons", L.NAVER_H).get("result") or {}).get("seasons") or [] if x.get("isEnable") == "Y"], key=lambda x: x.get("year") or 0)
    cur = cur_season(cat)
    yrs = [x for x in ss if x["seasonCode"] != cur]
    return yrs[-1]["seasonCode"] if yrs else None


def cur_season(cat):
    ss = [x for x in (L._j(f"https://api-gw.sports.naver.com/statistics/categories/{cat}/seasons", L.NAVER_H).get("result") or {}).get("seasons") or [] if x.get("isEnable") == "Y"]
    cur = [x for x in ss if x.get("isSeason") == "Y"] or sorted(ss, key=lambda x: x.get("year") or 0)[-1:]
    return cur[0]["seasonCode"] if cur else None


def _fold(x):
    x = (x or "").translate(str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "ı": "i", "œ": "oe"}))
    x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    return [t for t in _re.split(r"[^a-z]+", x) if t]


def _sp(x):
    return (x or "").replace(" ", "")


def _view(p):
    try:
        return json.loads(p.get("profile") or "{}").get("viewName") or ""
    except Exception:
        return ""


def _en_ok(api_name, view):
    """API 영문 이름의 (약어 아닌) 토큰이 모두 네이버 영문 표기(viewName)에 있음, 3자 이상 토큰 1개 이상."""
    a, v = _fold(api_name), set(_fold(view))
    full = [t for t in a if len(t) >= 2]
    return bool(v) and bool(full) and any(len(t) >= 3 for t in full) and all(t in v for t in full)


HANGUL = _re.compile(r"^[가-힣 ·\-]+$")


def pair_foreign(sq, nv):
    """같은 팀 + 영문 이름 일치(팀 안에서 유일) + 등번호 일치(둘 다 있으면 필수) 또는 포지션/전체 이름 일치."""
    res = {}
    for a in sq:
        en = [p for p in nv if _en_ok(a.get("name"), _view(p))]
        if len(en) != 1:
            continue
        p = en[0]
        has_no = a.get("number") is not None and p.get("backNumber") not in (None, "")
        no_ok = has_no and int(a["number"]) == int(p["backNumber"])
        pos_ok = p.get("position") == FPOS.get(a.get("position"))
        full = _fold(a.get("name")) == _fold(_view(p))
        if has_no and not no_ok and not full:
            continue
        if not (no_ok or pos_ok or full):
            continue
        if not HANGUL.match(p.get("playerName") or ""):
            continue
        res[str(a["id"])] = {"ko": p["playerName"], "how": "en+" + ("num" if no_ok else "full" if full else "pos")}
    cnt = {}
    for v in res.values():
        cnt[v["ko"]] = cnt.get(v["ko"], 0) + 1
    return {k: v for k, v in res.items() if cnt[v["ko"]] == 1}


FOREIGN = {"epl": [39], "primera": [140], "seria": [135], "bundesliga": [78], "ligue1": [61], "champs": [2], "acl": [17, 18], "spl": [307], "jleague": [98]}


def football_foreign():
    out, stat = {}, []
    done = set()
    for cat, lgs in FOREIGN.items():
        se = cur_season(cat)
        nv = naver_players(cat, se) if se else []
        ids = {p["playerId"] for p in nv}
        ps = prev_season(cat)
        nv += [p for p in (naver_players(cat, ps) if ps else []) if p["playerId"] not in ids]   # 지난 시즌: 이번 시즌 기록 없는 선수만 (같은 팀 + 영문 이름 + 등번호로 다시 확인)
        teams = {}
        for p in nv:
            teams.setdefault(p["teamId"], []).append(p)
        for t in [x["team"] for lg in lgs for x in T._get("football", "/teams", {"league": lg, "season": YEAR})]:
            if (cat, t["id"]) in done:
                continue
            done.add((cat, t["id"]))
            sq = (T._get("football", "/players/squads", {"team": t["id"]}) or [{}])[0].get("players") or []
            sc = sorted(((sum(1 for a in sq if any(_en_ok(a["name"], _view(p)) for p in ps)), tid) for tid, ps in teams.items()), reverse=True)
            if not sc or sc[0][0] < 5 or (len(sc) > 1 and sc[1][0] * 2 >= sc[0][0]):
                # 영문 표기가 없는 리그(ACL·J리그·사우디): 한글 팀 이름이 정확히 같은 네이버 팀 1개 → 팀+등번호+포지션
                import teams_ko
                kn = _sp(teams_ko.ko("football", t["id"], t["name"])[0])
                hit = [tid for tid, ps in teams.items() if kn and kn in {_sp(ps[0].get("teamName")), _sp(ps[0].get("teamShortName"))}]
                if len(hit) != 1:
                    stat.append((cat, t["name"], len(sq), 0, "team?"))
                    continue
                m = pair(sq, teams[hit[0]])
                m = {k: v for k, v in m.items() if HANGUL.match(v["ko"])}
                for k, v in m.items():
                    out[k] = {**v, "team": t["id"]}
                stat.append((cat, t["name"], len(sq), len(m), ""))
                continue
            m = pair_foreign(sq, teams[sc[0][1]])
            for k, v in m.items():
                out[k] = {**v, "team": t["id"]}
            stat.append((cat, t["name"], len(sq), len(m), ""))
    return out, stat


def mlb():
    """MLB: 네이버 MLB 시즌 기록(한글 이름·영문 viewName·등번호·팀) ↔ MLB StatsAPI 40인 로스터(id·전체 영문 이름·등번호).
    같은 팀 + 영문 전체 이름 일치(팀 안에서 유일) + 등번호(둘 다 있으면 일치 필수)."""
    yr = str(YEAR)
    nv = []
    for t in ("HITTER", "PITCHER"):
        u = f"https://api-gw.sports.naver.com/statistics/categories/mlb/seasons/{yr}/players?pageSize=300&playerType={t}"
        tids = sorted({p["teamId"] for p in (L._j(u, L.NAVER_H).get("result") or {}).get("seasonPlayerStats") or []})
        for c in tids:
            nv += (L._j(u + "&teamCode=" + c, L.NAVER_H).get("result") or {}).get("seasonPlayerStats") or []
    teams = {}
    for p in nv:
        teams.setdefault(p["teamId"], {})[p["playerId"]] = p
    names = lambda p: [x.strip() for x in _view(p).split(",") if x.strip()]
    out, stat = {}, []
    for t in L._j("https://statsapi.mlb.com/api/v1/teams?sportId=1").get("teams") or []:
        ro = L._j(f"https://statsapi.mlb.com/api/v1/teams/{t['id']}/roster?rosterType=40Man").get("roster") or []
        api = [{"id": r["person"]["id"], "name": r["person"]["fullName"], "no": r.get("jerseyNumber")} for r in ro]
        sc = sorted(((sum(1 for a in api if any(_fold(a["name"]) == _fold(n) for p in ps.values() for n in names(p))), tid) for tid, ps in teams.items()), reverse=True)
        if not sc or sc[0][0] < 5 or (len(sc) > 1 and sc[1][0] * 2 >= sc[0][0]):
            stat.append((t["name"], len(api), 0, "team?"))
            continue
        ps = list(teams[sc[0][1]].values())
        m = {}
        for a in api:
            c = [p for p in ps if any(_fold(a["name"]) == _fold(n) for n in names(p))]
            if len(c) != 1 or not HANGUL.match(c[0].get("playerName") or ""):
                continue
            p = c[0]
            if a["no"] not in (None, "") and p.get("backNumber") not in (None, "") and str(a["no"]) != str(p["backNumber"]):
                continue
            m[str(a["id"])] = {"ko": p["playerName"], "how": "fullname+" + ("num" if a["no"] not in (None, "") and p.get("backNumber") not in (None, "") else "team"), "team": t["id"]}
        cnt = {}
        for v in m.values():
            cnt[v["ko"]] = cnt.get(v["ko"], 0) + 1
        m = {k: v for k, v in m.items() if cnt[v["ko"]] == 1}
        out.update(m)
        stat.append((t["name"], len(api), len(m), ""))
    return out, stat


if __name__ == "__main__":
    fb, st = football()
    tot = sum(x[1] for x in st)
    print("kleague", len(fb), "/", tot)
    ff, st2 = football_foreign()
    for k, v in ff.items():
        fb.setdefault(k, v)
    agg = {}
    for c, n, a, b, _ in st2:
        x = agg.setdefault(c, [0, 0]); x[0] += b; x[1] += a
    for c, (b, a) in agg.items():
        print(c, b, "/", a, f"{100*b/max(a,1):.0f}%")
    print("unpaired teams", [x[:2] for x in st2 if x[4]])
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    old["football"] = fb
    if True:
        mb, sm = mlb()
        old["mlb"] = mb
        print("mlb", len(mb), "/", sum(x[1] for x in sm), "unpaired", [x[0] for x in sm if x[3]])
    old["_built"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(old, open(OUT, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    print("football total", len(fb))

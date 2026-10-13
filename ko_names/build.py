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


if __name__ == "__main__":
    fb, st = football()
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    old["football"] = fb
    old["_built"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(old, open(OUT, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    tot = sum(x[1] for x in st)
    for x in st:
        print(*x)
    print("football", len(fb), "/", tot, f"{100*len(fb)/max(tot,1):.0f}%")

"""NBA 한글 이름 (다음스포츠 팀 선수 명단: 한글 이름·등번호·생년월일) ↔ ESPN 현재 로스터(id·등번호·생년월일).
채택: 같은 팀(팀 짝은 일치 선수 수 최다·2위와 확실한 차이) + 등번호 일치 + 생년월일 일치(ESPN UTC 표기 ±1일). 그 외 영문 그대로.
위키 확인 이름과 표기만 다르면(같은 선수) 다음 표기 사용."""
import json, os, datetime, urllib.request, time
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ko_names.json")
UA = {"User-Agent": "Mozilla/5.0"}
j = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20))
D = "https://sports.daum.net/prx/hermes/api/"


def dob_ok(espn, daum):
    if not espn or not daum:
        return False
    try:
        e = datetime.date.fromisoformat(espn[:10]); d = datetime.datetime.strptime(daum, "%Y%m%d").date()
    except Exception:
        return False
    return abs((e - d).days) <= 1


def main():
    dt = {}
    for t in j(D + "team/list.json?leagueCode=nba&pageSize=40")["list"]:
        dt[t["teamId"]] = j(D + f"person/list.json?leagueCode=nba&teamId={t['teamId']}&pageSize=60").get("list") or []
        time.sleep(0.2)
    et = {}
    for t in j("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")["sports"][0]["leagues"][0]["teams"]:
        et[t["team"]["id"]] = j(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{t['team']['id']}/roster").get("athletes") or []
    key = lambda a, p: str(a.get("jersey")) == str(p.get("backNumber")) and dob_ok(a.get("dateOfBirth"), p.get("birthDate"))
    out, tot, bad = {}, 0, []
    for eid, ro in et.items():
        tot += len(ro)
        sc = sorted(((sum(1 for a in ro if any(key(a, p) for p in ps)), tid) for tid, ps in dt.items()), reverse=True)
        if sc[0][0] < 3 or sc[1][0] * 2 >= sc[0][0]:
            bad.append(eid); continue
        ps = dt[sc[0][1]]
        for a in ro:
            c = [p for p in ps if key(a, p)]
            if len(c) == 1 and c[0].get("nameKo"):
                out[str(a["id"])] = {"ko": c[0]["nameKo"].strip(), "how": "daum:team+num+dob", "team": eid, "no": a.get("jersey")}
    old = json.load(open(OUT))
    prev = old.get("nba") or {}
    for k, v in prev.items():
        if k in out and out[k]["ko"].replace(" ", "") != v["ko"].replace(" ", ""):
            continue   # 같은 선수(두 출처 모두 확인), 표기만 다름 → 국내 스포츠 매체(다음) 표기 사용
        out.setdefault(k, v)
    old["nba"] = out
    json.dump(old, open(OUT, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    print("nba", len(out), "/", tot, "unpaired teams", bad)


main()

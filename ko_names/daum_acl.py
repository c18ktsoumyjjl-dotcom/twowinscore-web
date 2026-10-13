"""ACL 엘리트·ACL2 해외 클럽: 다음스포츠 팀 선수 명단(한글·등번호·포지션) ↔ API-Sports 스쿼드(id·등번호·포지션).
팀 짝: 등번호+포지션 일치 수 최다(6명 이상)·2위보다 6명 이상 많음(무작위 등번호·포지션 겹침은 팀당 약 15명). 선수: 같은 팀 + 등번호 + 포지션 군 일치, 양쪽 모두 그 등번호 유일.
이미 확인된 축구 이름은 덮지 않음."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import teamodds as T
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ko_names.json")
D = "https://sports.daum.net/prx/hermes/api/"
j = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20))
FPOS = {"Goalkeeper": "GK", "Defender": "DF", "Midfielder": "MF", "Attacker": "FW"}
EAST = {"Japan", "China", "Hong-Kong", "Vietnam", "Cambodia"}
YEAR = time.localtime().tm_year

dt = {}
for c in ("AFCCL", "ACL2"):
    for t in j(D + f"team/list.json?leagueCode={c}&pageSize=60")["list"]:
        ps = j(D + f"person/list.json?leagueCode={c}&pageSize=80&teamId={t['teamId']}").get("list") or []
        dt[t["teamId"]] = [p for p in ps if p.get("backNumber") and p.get("nameKo")]
        time.sleep(0.2)
old = json.load(open(OUT)); fb = old["football"]
key = lambda a, p: a.get("number") is not None and str(a["number"]) == str(p["backNumber"]) and FPOS.get(a.get("position")) == ((p.get("position") or {}).get("nameMain"))
add, tot, seen, bad = 0, 0, set(), []
for lg in (17, 18):
    for t in [x["team"] for x in T._get("football", "/teams", {"league": lg, "season": YEAR})]:
        if t["id"] in seen or t["country"] in ("South-Korea",):
            continue
        seen.add(t["id"])
        sq = []
        for _ in range(4):
            sq = sq or list({a["id"]: a for a in (T._get("football", "/players/squads", {"team": t["id"]}) or [{}])[0].get("players") or []}.values())
            if sq:
                break
            time.sleep(5)
        tot += len(sq)
        sc = sorted(((sum(1 for a in sq if any(key(a, p) for p in ps)), tid) for tid, ps in dt.items()), reverse=True)
        if not sc or sc[0][0] < 6 or (len(sc) > 1 and sc[0][0] - sc[1][0] < 6):
            bad.append((t["name"], t["id"], len(sq), sc[:2])); continue
        ps = dt[sc[0][1]]
        for a in sq:
            c = [p for p in ps if key(a, p)]
            if len(c) != 1 or sum(1 for b in sq if b.get("number") == a.get("number")) != 1:
                continue
            if str(a["id"]) in fb:
                continue
            nm = c[0]["nameKo"].strip()
            if " " in nm:
                continue   # 다음 ACL 표기는 이름 순서가 선수마다 제각각(마네 사디오 / 하파에우 하탕) → 여러 단어 이름은 순서 확인 불가라 제외, 한 단어 이름만
            fb[str(a["id"])] = {"ko": c[0]["nameKo"].strip(), "how": "daum-acl:team+num+pos", "team": t["id"]}
            add += 1
json.dump(old, open(OUT, "w"), ensure_ascii=False, indent=0, sort_keys=True)
print("acl foreign added", add, "squad players", tot, "covered", sum(1 for v in fb.values() if v.get("team") in seen), "unpaired", bad)

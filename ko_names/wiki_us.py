"""NBA·NHL 한글 이름: 공식 현재 로스터(ESPN NBA / NHL api-web: id·전체 영문 이름·등번호)
→ 영문 위키백과 문서 제목이 영문 전체 이름과 정확히 같고(또는 '이름 (basketball|ice hockey)'), 문서 설명에 해당 종목 선수,
→ 그 문서의 한국어 위키백과 언어 링크 제목(괄호 제거, 한글만) 채택. 하나라도 어긋나면 영문 그대로."""
import json, os, re, sys, time, urllib.request, urllib.parse
UA = {"User-Agent": "twowinscore-names/1.0 (contact via twowinscore.com)"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ko_names.json")
HANGUL = re.compile(r"^[가-힣 ·\-\.]+$")


def j(u):
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20))
        except Exception:
            time.sleep(2)
    return {}


def wiki(names, sport_word):
    """names: list of exact English names → {name: ko}"""
    res = {}
    cands = {}
    for n in names:
        cands[n] = [n, f"{n} ({sport_word})"]
    titles = [t for v in cands.values() for t in v]
    info = {}
    for i in range(0, len(titles), 40):
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "langlinks|description", "lllang": "ko", "lllimit": "max",
                                    "titles": "|".join(titles[i:i + 40])})
        r = j("https://en.wikipedia.org/w/api.php?" + q).get("query") or {}
        for p in (r.get("pages") or {}).values():
            if "missing" in p:
                continue
            ll = [x.get("*") for x in p.get("langlinks") or []]
            info[p["title"]] = (p.get("description") or "", ll[0] if ll else None)
        time.sleep(0.3)
    for n, ts in cands.items():
        hit = [(t, info[t]) for t in ts if t in info and sport_word in info[t][0].lower() and info[t][1]]
        if len(hit) != 1:
            continue
        ko = re.sub(r"\s*\(.*?\)\s*$", "", hit[0][1][1]).strip()
        if HANGUL.match(ko):
            res[n] = ko
    return res


def nba():
    ps = []
    for t in (j("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams").get("sports") or [{}])[0].get("leagues", [{}])[0].get("teams", []):
        tid = t["team"]["id"]
        for a in j(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{tid}/roster").get("athletes") or []:
            ps.append((str(a["id"]), a.get("fullName") or a.get("displayName"), a.get("jersey"), tid))
    m = wiki(sorted({p[1] for p in ps}), "basketball")
    dup = {}
    for p in ps:
        dup[p[1]] = dup.get(p[1], 0) + 1
    return {p[0]: {"ko": m[p[1]], "how": "enwiki-exact+langlink", "team": p[3], "no": p[2]} for p in ps if p[1] in m and dup[p[1]] == 1}, len(ps)


def nhl():
    ps = []
    for t in j("https://api-web.nhle.com/v1/standings/now").get("standings") or []:
        ab = t["teamAbbrev"]["default"]
        r = j(f"https://api-web.nhle.com/v1/roster/{ab}/current")
        for grp in ("forwards", "defensemen", "goalies"):
            for a in r.get(grp) or []:
                ps.append((str(a["id"]), f"{a['firstName']['default']} {a['lastName']['default']}", a.get("sweaterNumber"), ab))
    m = wiki(sorted({p[1] for p in ps}), "ice hockey")
    dup = {}
    for p in ps:
        dup[p[1]] = dup.get(p[1], 0) + 1
    return {p[0]: {"ko": m[p[1]], "how": "enwiki-exact+langlink", "team": p[3], "no": p[2]} for p in ps if p[1] in m and dup[p[1]] == 1}, len(ps)


if __name__ == "__main__":
    which = sys.argv[1]
    d, n = (nba if which == "nba" else nhl)()
    old = json.load(open(OUT))
    old["nba" if which == "nba" else "hockey"] = d
    json.dump(old, open(OUT, "w"), ensure_ascii=False, indent=0, sort_keys=True)
    print(which, len(d), "/", n)

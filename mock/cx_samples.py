"""문자중계 시안용 예시 데이터(실제 경기 아님) → commentary.py 로 문장 생성."""
import json, sys, time
sys.path.insert(0, ".")
import data
import commentary as C, plays
from datetime import datetime
def run(g, cache=None, snaps=()):
    plays._cached = lambda key, ttl, fn: (cache or {}).get(key.split(":")[0])
    C._hist.pop(g["key"], None); C._stats.pop(g["key"], None)
    for (h, a, lines, per) in snaps:
        g2 = dict(g, home_score=h, away_score=a, lines=lines, period=per); C._snap(g2)
    if cache and cache.get("fbstat2"):
        plays._cached = lambda key, ttl, fn: (cache or {}).get(key.split(":")[0]) if key.split(":")[0] != "fbstat" else cache["fbstat1"]
        C.build(g)
        plays._cached = lambda key, ttl, fn: (cache or {}).get(key.split(":")[0]) if key.split(":")[0] != "fbstat" else cache["fbstat2"]
    r = C.build(g)
    return r
def st(sh, sot, ck, pos, gk=0):
    return [{"team": {"id": 1}, "statistics": [{"type": "Total Shots", "value": sh[0]}, {"type": "Shots on Goal", "value": sot[0]}, {"type": "Corner Kicks", "value": ck[0]}, {"type": "Ball Possession", "value": f"{pos}%"}, {"type": "Goalkeeper Saves", "value": gk}]},
            {"team": {"id": 2}, "statistics": [{"type": "Total Shots", "value": sh[1]}, {"type": "Shots on Goal", "value": sot[1]}, {"type": "Corner Kicks", "value": ck[1]}, {"type": "Ball Possession", "value": f"{100-pos}%"}, {"type": "Goalkeeper Saves", "value": 1}]}]
out = {}
fb = {"key": "football:ex:1", "id": 1, "kind": "football", "league": 292, "state": "live", "home": "포항", "away": "조호르", "home_id": 1, "away_id": 2, "home_score": 2, "away_score": 1, "period": "후반 67'", "lines": [["전반", 0, 1], ["후반", 2, 0]]}
ev = [{"time": {"elapsed": 23}, "team": {"id": 2}, "player": {"name": "Bergson"}, "assist": {"name": "Arif Aiman"}, "type": "Goal", "detail": "Normal Goal"},
      {"time": {"elapsed": 38}, "team": {"id": 1}, "player": {"name": "Shin Kwang-hoon"}, "type": "Card", "detail": "Yellow Card"},
      {"time": {"elapsed": 46}, "team": {"id": 1}, "player": {"name": "Kim In-sung"}, "assist": {"name": "Hong Yun-sang"}, "type": "subst", "detail": "Substitution 1"},
      {"time": {"elapsed": 52}, "team": {"id": 1}, "player": {"name": "Lee Ho-jae"}, "type": "Goal", "detail": "Normal Goal"},
      {"time": {"elapsed": 61}, "team": {"id": 1}, "player": {"name": "Lee Ho-jae"}, "type": "Goal", "detail": "Penalty"}]
out["football"] = run(fb, {"fbraw": ev, "fbstat1": st((8, 9), (3, 4), (3, 2), 54), "fbstat2": st((9, 9), (4, 4), (4, 2), 55)})
bb = {"key": "basketball:ex:1", "id": 2, "kind": "basketball", "league": 12, "state": "live", "home": "LA 레이커스", "away": "보스턴", "home_score": 98, "away_score": 97, "period": "4Q 2:41", "lines": [["1", 27, 25], ["2", 22, 28], ["3", 26, 24], ["4", 23, 20]]}
snaps = [(88, 95, [["1", 27, 25], ["2", 22, 28], ["3", 26, 24], ["4", 13, 18]], "4Q 5:10"), (90, 95, None, "4Q 4:48"), (93, 95, None, "4Q 4:20"), (95, 95, None, "4Q 3:55"),
         (95, 97, None, "4Q 3:31"), (98, 97, None, "4Q 2:41")]
snaps = [(h, a, l or [["1", 27, 25], ["2", 22, 28], ["3", 26, 24], ["4", h - 75, a - 77]], p) for h, a, l, p in snaps]
out["basketball"] = run(bb, {}, snaps)
vb = {"key": "volleyball:ex:1", "id": 3, "kind": "volleyball", "league": 153, "state": "live", "home": "정관장", "away": "SOOP", "home_score": 2, "away_score": 1, "period": "4세트", "lines": [["1", 25, 21], ["2", 23, 25], ["3", 26, 24], ["4", 24, 22]]}
vs = [(2, 1, [["1", 25, 21], ["2", 23, 25], ["3", 26, 24], ["4", x, y]], "4세트") for x, y in ((19, 21), (20, 21), (21, 21), (22, 21), (23, 21), (23, 22), (24, 22))]
out["volleyball"] = run(vb, {}, vs)
hk = {"key": "hockey:ex:1", "id": 4, "kind": "hockey", "league": 57, "state": "live", "home": "토론토", "away": "몬트리올", "home_id": 1, "away_id": 2, "home_score": 3, "away_score": 2, "period": "3P 18:12", "lines": [["1P", 1, 0], ["2P", 0, 2], ["3P", 2, 0]]}
he = [{"period": "P1", "minute": "07", "team": {"id": 1}, "players": ["A. Matthews"], "type": "goal"}, {"period": "P2", "minute": "04", "team": {"id": 2}, "players": ["N. Suzuki"], "type": "goal"},
      {"period": "P2", "minute": "15", "team": {"id": 2}, "players": ["C. Caufield"], "type": "goal"}, {"period": "P3", "minute": "05", "team": {"id": 2}, "players": ["A. Barron"], "type": "penalty"},
      {"period": "P3", "minute": "06", "team": {"id": 1}, "players": ["W. Nylander"], "type": "goal"}, {"period": "P3", "minute": "18", "team": {"id": 1}, "players": ["M. Marner"], "type": "goal"}]
out["hockey"] = run(hk, {"hkraw": he})
kb = {"key": "baseball:ex:1", "id": 5, "kind": "baseball", "league": 5, "state": "live", "home": "LG", "away": "KIA", "home_score": 5, "away_score": 4, "period": "8회말",
      "innings": {"away": {"inn": {"1": 2, "2": 0, "3": 0, "4": 2, "5": 0, "6": 0, "7": 0, "8": 0}}, "home": {"inn": {"1": 0, "2": 1, "3": 0, "4": 0, "5": 0, "6": 3, "7": 0, "8": 1}}}}
out["baseball"] = run(kb, {})
json.dump({k: {"items": [x["t"] for x in v["items"]], "ctx": v["ctx"]} for k, v in out.items()}, open("mock/cx_samples.json", "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    print("==", k); [print(" ", x["t"]) for x in v["items"]]; print("  ctx:", v["ctx"])

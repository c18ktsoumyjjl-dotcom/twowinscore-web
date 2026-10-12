"""홈 목록 큐레이션 (라이브스코어 기준). 여기만 고치면 돼요.

- KEEP: 종목별로 홈 목록(주 + 기타)에 기본 노출할 API-Sports 리그 id.
  종목이 여기 없으면(축구·배구) 리그 필터 없음.
- 축구: 오늘 화면에서 진행 중 + 앞으로 FOOTBALL_WINDOW_H 시간 안의 경기만 기본 노출.
  끝난(종료·취소) 경기는 기본 목록에서 빠져요.
- 숨긴 경기도 API 에는 hide=true 로 그대로 내려가서 검색·즐겨찾기로는 항상 보여요.
"""
from datetime import timedelta

KEEP = {
    "baseball": {1, 2, 5},                     # MLB, NPB, KBO
    "basketball": {12, 56, 91, 52, 117, 113, 2, 72, 104, 108, 89, 60,
                   190},                       # 190: API 이름은 "Super Cup" 이지만 라이브스코어 "오스트리아 Superliga" 와 같은 경기(Wels-Gmunden, Vienna-Kufstein 10/12)
    "hockey": {57, 35, 10, 32, 70, 55, 21, 91, 15, 19},
}
FOOTBALL_WINDOW_H = 24
FOOTBALL_DONE = {"final", "cancelled"}


def league_id(g):
    lid = g.get("league")
    if isinstance(lid, int):
        return lid
    try:
        return int(str(g["key"]).split(":")[1])
    except Exception:
        return None


def hidden(g, now, is_today):
    keep = KEEP.get(g["kind"])
    if keep is not None and league_id(g) not in keep:
        return True
    if g["kind"] == "football" and is_today:
        if g["state"] in FOOTBALL_DONE:
            return True
        if g["state"] == "scheduled" and g["start"] > now + timedelta(hours=FOOTBALL_WINDOW_H):
            return True
    return False


def next_day_football(games, now):
    """내일 날짜지만 지금부터 24시간 안에 시작하는 축구 (라이브스코어처럼 자정 넘어 이어보기)."""
    lim = now + timedelta(hours=FOOTBALL_WINDOW_H)
    return [g for g in games if g["kind"] == "football" and g["state"] in ("scheduled", "live") and g["start"] < lim]

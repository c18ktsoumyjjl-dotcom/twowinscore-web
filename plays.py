"""문자중계: 실제 데이터에서만 만든다. 지어내지 않는다.
- MLB: statsapi.mlb.com live feed (득점·홈런·안타 등 실제 플레이, 선수 이름 그대로)
- 그 외 야구(KBO·NPB): API-Sports 이닝별 점수 변화만
- 농구: 쿼터별 점수, 배구: 세트별 점수
"""
import os, json, time, urllib.request
from datetime import timedelta
import mlb_official
from injuries import MLB_TEAM

UA = {"User-Agent": "Mozilla/5.0 (twowinscore-web)"}
CACHE = os.environ.get("CACHE_DIR", "/tmp/twowinscore-cache")
_mem = {}

EV_KO = {"home_run": ("홈런", "🔥"), "triple": ("3루타", "💥"), "double": ("2루타", "⚡"), "single": ("안타", "⚾"),
         "walk": ("볼넷", "👀"), "intent_walk": ("고의4구", "👀"), "hit_by_pitch": ("몸에 맞는 공", "😵"),
         "sac_fly": ("희생플라이", "🎯"), "field_error": ("상대 실책", "😱"), "grounded_into_double_play": ("병살타", "😩"),
         "field_out": ("아웃", "⚾"), "force_out": ("포스아웃", "⚾"), "fielders_choice": ("야수선택", "⚾"),
         "fielders_choice_out": ("야수선택", "⚾"), "sac_bunt": ("희생번트", "🎯"), "wild_pitch": ("폭투", "😱"),
         "passed_ball": ("포일", "😱"), "stolen_base_2b": ("도루", "💨"), "balk": ("보크", "😱")}
SHOW = {"home_run", "triple", "double", "single"}


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode())


def _cached(key, ttl, fn):
    hit = _mem.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        val = None
        ttl_fail = time.time() - ttl + 60
        _mem[key] = (ttl_fail, None)
        return None
    _mem[key] = (time.time(), val)
    return val


def _mlb_pk(g):
    if g.get("mlb_pk"):
        return g["mlb_pk"]
    hs, as_ = MLB_TEAM.get(g.get("home_id")), MLB_TEAM.get(g.get("away_id"))
    if not hs or not as_:
        return None
    d = g["start"].astimezone(mlb_official.SEOUL)
    d0, d1 = (d - timedelta(days=1)).date().isoformat(), d.date().isoformat()
    games = mlb_official._schedule(d0, d1) or []
    for x in games:
        t = x.get("teams") or {}
        if (t.get("home") or {}).get("team", {}).get("id") == hs and (t.get("away") or {}).get("team", {}).get("id") == as_:
            st = mlb_official._start(x)
            if st and abs((st - g["start"]).total_seconds()) < 8 * 3600:
                return x.get("gamePk")
    return None


def _mlb(g):
    pk = _mlb_pk(g)
    if not pk:
        return None
    ttl = 30 if g["state"] == "live" else 6 * 3600
    feed = _cached(f"mlbfeed:{pk}", ttl, lambda: _get(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"))
    if not feed:
        return None
    plays = ((feed.get("liveData") or {}).get("plays") or {}).get("allPlays") or []
    side_name = {"top": g["away"], "bottom": g["home"]}
    out = []
    for p in plays:
        res, ab, mu = p.get("result") or {}, p.get("about") or {}, p.get("matchup") or {}
        ev = res.get("eventType")
        rbi = res.get("rbi") or 0
        scoring = ab.get("isScoringPlay")
        if ev not in SHOW and not scoring:
            continue
        name, emo = EV_KO.get(ev, (res.get("event") or "플레이", "⚾"))
        batter = (mu.get("batter") or {}).get("fullName")
        inn = f"{ab.get('inning')}회{'초' if ab.get('halfInning') == 'top' else '말'}"
        team = side_name.get(ab.get("halfInning"), "")
        if ev == "home_run":
            line = f"{emo} {inn} {team} {batter} {'만루 ' if rbi == 4 else ''}홈런!! " + (f"{rbi}점 홈런이에요" if rbi > 1 else "솔로포!")
        elif scoring:
            line = f"{emo} {inn} {team} {batter} {name}" + (f" · {rbi}타점" if rbi else "") + " — 득점!"
        else:
            line = f"{emo} {inn} {team} {batter} {name}"
        if scoring and res.get("awayScore") is not None:
            line += f"  ({g['away']} {res['awayScore']} : {res['homeScore']} {g['home']})"
        out.append({"t": line, "hot": bool(scoring)})
    if g["state"] == "final" and out:
        out.append({"t": f"🏁 경기 종료 · {g['away']} {g.get('away_score')} : {g.get('home_score')} {g['home']}", "hot": True})
    out.reverse()
    return {"source": "MLB 공식 경기 기록(statsapi)", "items": out}


def _innings(g):
    inn = g.get("innings")
    if not inn:
        return None
    ev, a, h = [], 0, 0
    keys = sorted({int(k) for s in ("home", "away") for k in inn[s]["inn"] if str(k).isdigit()})
    for n in keys:
        for side, half in (("away", "초"), ("home", "말")):
            r = inn[side]["inn"].get(str(n))
            if r is None:
                continue
            try:
                r = int(r)
            except (TypeError, ValueError):
                continue
            if side == "away":
                a += r
            else:
                h += r
            if r > 0:
                team = g["away"] if side == "away" else g["home"]
                emo = "🔥" if r >= 3 else "⚾"
                word = "빅이닝!" if r >= 3 else "냈어요!"
                ev.append({"t": f"{emo} {n}회{half} {team} {r}점 {word}  ({g['away']} {a} : {h} {g['home']})", "hot": r >= 3})
    if g["state"] == "final" and ev:
        ev.append({"t": f"🏁 경기 종료 · {g['away']} {g.get('away_score')} : {g.get('home_score')} {g['home']}", "hot": True})
    ev.reverse()
    return {"source": "이닝별 점수(API-Sports)", "items": ev} if ev else None


def _periods(g):
    lines = g.get("lines") or []
    if not lines:
        return None
    k = g["kind"]
    emo = {"basketball": "🏀", "volleyball": "🏐", "hockey": "🏒"}.get(k, "⚽")
    ev, th, ta = [], 0, 0
    for lab, hs, as_ in lines:
        th, ta = th + hs, ta + as_
        name = f"{lab}쿼터" if k == "basketball" and str(lab).isdigit() else f"{lab}세트" if k == "volleyball" and str(lab).isdigit() else lab
        if k == "volleyball":
            win = g["home"] if hs > as_ else g["away"]
            ev.append({"t": f"{emo} {name} {win} 따냈어요! ({hs}-{as_})", "hot": abs(hs - as_) <= 2})
        elif k == "hockey":
            if hs == as_ == 0:
                ev.append({"t": f"{emo} {name} 무득점 · 팽팽해요 (합계 {th}-{ta})", "hot": False})
            else:
                ev.append({"t": f"{emo}🔥 {name} {g['home']} {hs}골 · {g['away']} {as_}골 (합계 {th}-{ta})", "hot": True})
        else:
            best = g["home"] if hs > as_ else g["away"] if as_ > hs else None
            msg = f"{best} {abs(hs - as_)}점 우세" if best else "동점 쿼터"
            ev.append({"t": f"{emo} {name} {g['home']} {hs} - {as_} {g['away']} · {msg} (합계 {th}-{ta})", "hot": abs(hs - as_) >= 10})
    if g["state"] == "final":
        ev.append({"t": f"🏁 경기 종료 · {g['home']} {g.get('home_score')} : {g.get('away_score')} {g['away']}", "hot": True})
    ev.reverse()
    src = {"basketball": "쿼터별 점수(API-Sports)", "volleyball": "세트별 점수(API-Sports)", "hockey": "피리어드별 점수(API-Sports)"}[k]
    return {"source": src, "items": ev}


def _football(g):
    import sports2
    ttl = 60 if g["state"] == "live" else 6 * 3600
    items = _cached("fbev:" + str(g["id"]), ttl, lambda: sports2.events(g))
    if not items:
        return None
    if g["state"] == "final":
        items = [{"t": f"🏁 경기 종료 · {g['home']} {g.get('home_score')} : {g.get('away_score')} {g['away']}", "hot": True}] + items
    return {"source": "경기 이벤트(API-Sports 득점·카드)", "items": items}


def commentary(g):
    if g.get("state") not in ("live", "final"):
        return None
    try:
        if g["kind"] == "baseball" and g["league"] == 1:
            r = _mlb(g)
            if r and r["items"]:
                return r
        if g["kind"] == "baseball":
            return _innings(g)
        if g["kind"] == "football":
            return _football(g)
        return _periods(g)
    except Exception:
        return None

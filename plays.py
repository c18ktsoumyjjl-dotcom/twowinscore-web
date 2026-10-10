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
EV_KO.update({"strikeout": ("삼진", "🔥"), "strikeout_double_play": ("삼진 병살", "🔥"), "stolen_base_3b": ("3루 도루", "💨"),
              "stolen_base_home": ("홈스틸", "💨"), "caught_stealing_2b": ("도루 실패", "🚫"), "caught_stealing_3b": ("도루 실패", "🚫"),
              "caught_stealing_home": ("홈 도루 실패", "🚫"), "pickoff_1b": ("견제사", "🎯"), "pickoff_2b": ("견제사", "🎯"),
              "pickoff_3b": ("견제사", "🎯"), "double_play": ("병살", "😩"), "triple_play": ("삼중살", "🤯")})
SHOW = {"home_run", "triple", "double", "single", "walk", "intent_walk", "hit_by_pitch", "strikeout", "strikeout_double_play",
        "field_error", "grounded_into_double_play", "double_play", "triple_play", "sac_fly", "wild_pitch", "passed_ball", "balk"}
RUN_EV = {"stolen_base_2b", "stolen_base_3b", "stolen_base_home", "caught_stealing_2b", "caught_stealing_3b",
          "caught_stealing_home", "pickoff_1b", "pickoff_2b", "pickoff_3b"}
FUN = {"single": "깔끔한 안타!", "double": "2루타! 장타 터졌어요", "triple": "3루타!! 빠르다", "walk": "볼넷으로 출루",
       "intent_walk": "고의4구, 승부를 피했어요", "hit_by_pitch": "몸에 맞고 출루 😵", "strikeout": "삼진! 돌려세웠어요",
       "strikeout_double_play": "삼진 병살! 한 번에 투아웃", "field_error": "상대 실책으로 출루", "grounded_into_double_play": "병살타… 아쉬워요",
       "double_play": "병살 처리", "triple_play": "삼중살!! 보기 드문 장면", "sac_fly": "희생플라이", "wild_pitch": "폭투!",
       "passed_ball": "포일!", "balk": "보크!"}


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
        inn = f"{ab.get('inning')}회{'초' if ab.get('halfInning') == 'top' else '말'}"
        team = side_name.get(ab.get("halfInning"), "")
        fteam = side_name.get("bottom" if ab.get("halfInning") == "top" else "top", "")   # 수비 팀
        # 타석 중 일어난 주루·투수 교체 (playEvents 의 action)
        for pe in p.get("playEvents") or []:
            if pe.get("type") != "action":
                continue
            d = pe.get("details") or {}
            pev = d.get("eventType")
            if pev == "pitching_substitution":
                import re as _re
                m = _re.search(r":\s*(.+?)\s+replaces\s+(.+?)\.?$", d.get("description") or "")
                nm = f"{m.group(1)} 등판 ({m.group(2)} 강판)" if m else ""
                out.append({"t": f"🔁 {inn} {fteam} 투수 교체" + (f" · {nm}" if nm else ""), "hot": False})
            elif pev in RUN_EV:
                nm2, emo2 = EV_KO[pev]
                runner = (pe.get("player") or {}).get("id")
                rn = next((r.get("details", {}).get("runner", {}).get("fullName") for r in p.get("runners") or []
                           if r.get("details", {}).get("runner", {}).get("id") == runner), None)
                out.append({"t": f"{emo2} {inn} {team if pev.startswith('stolen') or pev.startswith('caught') else team} {rn or ''} {nm2}".replace("  ", " "), "hot": False})
        if ev not in SHOW and not scoring:
            continue
        name, emo = EV_KO.get(ev, (res.get("event") or "플레이", "⚾"))
        batter = (mu.get("batter") or {}).get("fullName")
        pitcher = (mu.get("pitcher") or {}).get("fullName")
        if ev == "home_run":
            line = f"{emo} {inn} {team} {batter} {'만루 ' if rbi == 4 else ''}홈런!! " + (f"{rbi}점 홈런이에요" if rbi > 1 else "솔로포!")
        elif scoring:
            line = f"{emo} {inn} {team} {batter} {name}" + (f" · {rbi}타점" if rbi else "") + " — 득점!"
        elif ev in ("strikeout", "strikeout_double_play"):
            line = f"{emo} {inn} {fteam} {pitcher}, {batter} {FUN[ev]}"
        else:
            line = f"{emo} {inn} {team} {batter} {FUN.get(ev, name)}"
        if scoring and res.get("awayScore") is not None:
            line += f"  ({g['away']} {res['awayScore']} : {res['homeScore']} {g['home']})"
        out.append({"t": line, "hot": bool(scoring) or ev in ("triple_play",)})
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
    lead, sh, sa = None, 0, 0
    for i, (lab, hs, as_) in enumerate(lines):
        th, ta = th + hs, ta + as_
        now_on = g["state"] == "live" and i == len(lines) - 1
        nl = "h" if th > ta else "a" if ta > th else None
        flip = k != "volleyball" and nl and lead and nl != lead
        if nl:
            lead = nl
        name = f"{lab}쿼터" if k == "basketball" and str(lab).isdigit() else f"{lab}세트" if k == "volleyball" and str(lab).isdigit() else lab
        if now_on:
            pname = f"{lab}쿼터" if k == "basketball" and str(lab).isdigit() else f"{lab}세트" if k == "volleyball" and str(lab).isdigit() else lab
            ev.append({"t": f"⏱️ {pname} 진행 중 · {g['home']} {hs} - {as_} {g['away']}" + ("" if k == "volleyball" else f" (합계 {th}-{ta})"), "hot": False})
        elif k == "volleyball":
            win = g["home"] if hs > as_ else g["away"]
            sh, sa = sh + (hs > as_), sa + (as_ > hs)
            ev.append({"t": f"{emo} {name} {win} 따냈어요! ({hs}-{as_}) · 세트 스코어 {g['home']} {sh}-{sa} {g['away']}", "hot": abs(hs - as_) <= 2})
        elif k == "hockey":
            if hs == as_ == 0:
                ev.append({"t": f"{emo} {name} 무득점 · 팽팽해요 (합계 {th}-{ta})", "hot": False})
            else:
                ev.append({"t": f"{emo}🔥 {name} {g['home']} {hs}골 · {g['away']} {as_}골 (합계 {th}-{ta})", "hot": True})
        else:
            best = g["home"] if hs > as_ else g["away"] if as_ > hs else None
            msg = f"{best} {abs(hs - as_)}점 우세" if best else "동점 쿼터"
            ev.append({"t": f"{emo} {name} {g['home']} {hs} - {as_} {g['away']} · {msg} (합계 {th}-{ta})", "hot": abs(hs - as_) >= 10})
        if flip:
            ev.append({"t": f"🔄 역전! {g['home'] if nl == 'h' else g['away']} 리드 ({g['home']} {th} : {ta} {g['away']})", "hot": True})
    if g["state"] == "final":
        ev.append({"t": f"🏁 경기 종료 · {g['home']} {g.get('home_score')} : {g.get('away_score')} {g['away']}", "hot": True})
    ev.reverse()
    src = {"basketball": "쿼터별 점수(API-Sports)", "volleyball": "세트별 점수(API-Sports)", "hockey": "피리어드별 점수(API-Sports)"}[k]
    return {"source": src, "items": ev}


def _football(g):
    import sports2
    ttl = 60 if g["state"] == "live" else 6 * 3600
    rows = _cached("fbraw:" + str(g["id"]), ttl, lambda: sports2.raw_events(g))
    items = sports2.events(g, rows) if rows else None
    if not items:
        return None
    if g["state"] == "final":
        items = [{"t": f"🏁 경기 종료 · {g['home']} {g.get('home_score')} : {g.get('away_score')} {g['away']}", "hot": True}] + items
    return {"source": "경기 이벤트(API-Sports 득점·도움·카드·교체·VAR)", "items": items}


def goals(g):
    """축구 득점 타임라인: 전반/후반/연장/승부차기별 양 팀 득점. 이벤트 없으면 구간 점수만."""
    if g.get("kind") != "football" or g.get("state") not in ("live", "final"):
        return None
    import sports2
    ttl = 60 if g["state"] == "live" else 6 * 3600
    try:
        rows = _cached("fbraw:" + str(g["id"]), ttl, lambda: sports2.raw_events(g))
        gl = sports2.goals(g, rows)
    except Exception:
        gl = []
    sc = {l[0]: (l[1], l[2]) for l in g.get("lines") or []}
    order = ["전반", "후반", "연장", "승부차기"]
    labs = [x for x in order if x in sc or any(y["half"] == x for y in gl)]
    if not labs and not gl:
        return None
    halves = []
    for lab in labs:
        its = [{k: y[k] for k in ("min", "side", "who", "kind", "ast")} for y in gl if y["half"] == lab]
        h, a = sc.get(lab, (None, None))
        if h is None and lab != "승부차기":
            h, a = sum(1 for y in its if y["side"] == "home"), sum(1 for y in its if y["side"] == "away")
        halves.append({"lab": lab, "h": h, "a": a, "items": its})
    tot = (g.get("home_score") or 0) + (g.get("away_score") or 0)
    got = sum(1 for y in gl if y["half"] != "승부차기")
    return {"halves": halves, "missing": max(0, tot - got), "home": g["home"], "away": g["away"]}


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

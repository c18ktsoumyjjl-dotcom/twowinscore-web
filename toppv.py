"""모바일 상세 상단(간결형). 렌더 시 외부 호출 없음: 배당·볼카운트·이벤트는 페이지가 뜬 뒤 비동기로 받는다."""
import re


def build(g, v, det=None):
    return {"kind": g["kind"], "state": g["state"], "period": g.get("period") or ""}


def _fb_events(g, lh):
    import plays, sports2
    ttl = 60 if g["state"] == "live" else 6 * 3600
    try:
        rows = plays._cached("fbraw:" + str(g["id"]), ttl, lambda: sports2.raw_events(g)) or []
    except Exception:
        rows = []
    lid = g["home_id"] if lh else g["away_id"]
    ev = []
    for e in rows:
        tm = e.get("time") or {}
        typ, det = e.get("type"), e.get("detail") or ""
        if typ == "Goal" and "Missed" not in det:
            t = "goal"
        elif typ == "Card":
            t = "red" if "Red" in det else "yel"
        elif typ == "subst":
            t = "sub"
        else:
            continue
        m = tm.get("elapsed") or 0
        ev.append({"t": t, "m": m, "s": "L" if (e.get("team") or {}).get("id") == lid else "R",
                   "who": __import__("pname").ko("football", (e.get("player") or {}).get("id"), (e.get("player") or {}).get("name") or ""), "lab": f"{m}'" + (f"+{tm['extra']}" if tm.get("extra") else "")})
    return ev


def _hk_events(g, lh):
    import plays, sports2
    ttl = 60 if g["state"] == "live" else 6 * 3600
    try:
        rows = plays._cached("hkraw:" + str(g["id"]), ttl, lambda: sports2.get("hockey", "/games/events", {"game": g["id"]})) or []
    except Exception:
        rows = []
    lid = g["home_id"] if lh else g["away_id"]
    ev = []
    for e in rows:
        p = str(e.get("period") or "")
        if e.get("type") not in ("goal", "penalty") or not p[1:].isdigit():
            continue
        ev.append({"t": "goal" if e["type"] == "goal" else "pen", "m": (int(p[1:]) - 1) * 20 + int(e.get("minute") or 0),
                   "s": "L" if (e.get("team") or {}).get("id") == lid else "R", "who": ", ".join(e.get("players") or []), "lab": f"{p[1:]}P {e.get('minute')}'"})
    return ev


def live(g, v):
    """/api/top: 라이브 폴링용 (실제 이벤트만)."""
    lh = v["left_home"]
    ev = _fb_events(g, lh) if g["kind"] == "football" else _hk_events(g, lh) if g["kind"] == "hockey" else []
    return {"ev": ev, "period": g.get("period") or ""}

"""상세 상단 미리보기(종목별 그래픽 + 타임라인 + 배당 한 줄). 확인된 실제 데이터만 쓴다. 없으면 해당 칸을 숨긴다."""
import re


def _odds(g, lh):
    try:
        import teamodds
        o = teamodds.odds(g)
    except Exception:
        o = None
    if not o or not o.get("H") or not o.get("A"):
        return None
    mv = o.get("mv") or {}
    L, R = ("H", "A") if lh else ("A", "H")
    cells = [{"k": "1" if lh else "원정", "v": o[L], "m": mv.get(L, 0)}]
    if o.get("D"):
        cells.append({"k": "X", "v": o["D"], "m": mv.get("D", 0)})
    cells.append({"k": "2" if lh else "홈", "v": o[R], "m": mv.get(R, 0)})
    x = o.get("x") or {}
    ex = []
    if x.get("hc"):
        h = x["hc"]; ln = h["ln"] if lh else -h["ln"]
        ex.append(f"핸디 {ln:+g} · {(h['a'] if lh else h['b']):.2f}/{(h['b'] if lh else h['a']):.2f}")
    if x.get("ou"):
        u = x["ou"]
        ex.append(f"기준 {u['ln']:g} · 오버 {u['a']:.2f}/언더 {u['b']:.2f}")
    return {"book": o.get("book"), "bs": o.get("bs"), "cells": cells, "ex": ex, "final": o.get("final"), "at": o.get("at")}


def _rank_form(g, det, lh):
    st = (det or {}).get("standings") or {}
    rows = {r.get("team"): r for r in (st.get("rows") or [])}
    out = {}
    for side, raw, fk in (("L", g["home"] if lh else g["away"], "form_home" if lh else "form_away"),
                          ("R", g["away"] if lh else g["home"], "form_away" if lh else "form_home")):
        r = rows.get(raw) or {}
        f = (det or {}).get(fk) or []
        fm = []
        for x in f[:5]:
            try:
                fm.append("W" if x["me"] > x["op"] else "L" if x["me"] < x["op"] else "D")
            except Exception:
                pass
        rec = None
        if r.get("win") is not None and r.get("lose") is not None:
            rec = f"{r['win']}승" + (f" {r['draw']}무" if r.get("draw") not in (None, 0) or g["kind"] == "football" and r.get("draw") is not None else "") + f" {r['lose']}패"
        out[side] = {"rank": r.get("rank"), "rec": rec, "form": fm}
    return out


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
        m = (tm.get("elapsed") or 0)
        ev.append({"t": t, "m": m, "x": tm.get("extra") or 0, "s": "L" if (e.get("team") or {}).get("id") == lid else "R",
                   "who": (e.get("player") or {}).get("name") or "", "ast": (e.get("assist") or {}).get("name") or "",
                   "lab": f"{m}'" + (f"+{tm['extra']}" if tm.get("extra") else "")})
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
        if e.get("type") not in ("goal", "penalty") or not p.startswith("P") or not p[1:].isdigit():
            continue
        try:
            mm = int(e.get("minute") or 0)
        except ValueError:
            continue
        m = (int(p[1:]) - 1) * 20 + mm
        ev.append({"t": "goal" if e["type"] == "goal" else "pen", "m": m, "s": "L" if (e.get("team") or {}).get("id") == lid else "R",
                   "who": ", ".join(e.get("players") or []), "ast": ", ".join(e.get("assists") or []), "lab": f"{p[1:]}P {mm}'", "c": e.get("comment") or ""})
    return ev


def _min(g):
    m = re.search(r"(\d+)'", str(g.get("period") or ""))
    return int(m.group(1)) if m else None


def build(g, v, det):
    lh = v["left_home"]
    k = g["kind"]
    out = {"kind": k, "state": g["state"], "odds": _odds(g, lh), "rf": _rank_form(g, det, lh), "period": g.get("period") or ""}
    if k == "football":
        out["ev"] = _fb_events(g, lh)
        out["cur"] = _min(g) if g["state"] == "live" else (90 if g["state"] == "final" else None)
        out["span"] = max(90, max([e["m"] for e in out["ev"]] + [out["cur"] or 0]))
    elif k == "hockey":
        out["ev"] = _hk_events(g, lh)
        pm = re.search(r"(\d)", str(g.get("status") or ""))
        out["cur"] = None if g["state"] != "live" else (int(pm.group(1)) - 1) * 20 + 10 if pm else None  # 피리어드 시계가 없어 '해당 피리어드' 위치만
        out["curp"] = int(pm.group(1)) if pm and g["state"] == "live" else None
        out["span"] = 60 if not any(e["m"] > 60 for e in out["ev"]) else 65
    elif k == "baseball":
        import lineup
        try:
            out["field"] = lineup.field(g)
        except Exception:
            out["field"] = None
        if g["state"] == "live":
            try:
                bso = lineup.bso(g) if hasattr(lineup, "bso") else None
            except Exception:
                bso = None
            out["bso"] = bso
        try:
            lu = lineup.get(g)
        except Exception:
            lu = None
        if lu and g["state"] == "scheduled":
            def side(s):
                t = lu.get(s) or {}
                return {"sp": (t.get("pit") or [{}])[0].get("name") if t.get("pit") else None,
                        "era": (t.get("pit") or [{}])[0].get("era") if t.get("pit") else None,
                        "pid": (t.get("pit") or [{}])[0].get("id") if t.get("pit") else None, "top": [{"o": b.get("o"), "n": b.get("name"), "p": b.get("pos"), "a": b.get("avg"), "id": b.get("id")} for b in (t.get("bat") or [])[:3]]}
            a, h = side("away"), side("home")
            out["photo"] = g.get("league") == 1 and all(isinstance((b or {}).get("id"), int) for b in (lu.get("away") or {}).get("bat") or [{}])
            out["pre"] = {"L": h if lh else a, "R": a if lh else h}
    elif k == "basketball":
        if g["state"] != "scheduled":
            import lineup
            try:
                b = lineup.basketball(g)
            except Exception:
                b = None
            if b:
                def top(s):
                    ps = sorted([p for p in b.get(s) or [] if p.get("pts") is not None], key=lambda p: -p["pts"])[:2]
                    return [{"n": p["name"], "pts": p["pts"], "reb": p.get("reb"), "ast": p.get("ast")} for p in ps]
                out["lead"] = {"L": top("home" if lh else "away"), "R": top("away" if lh else "home")}
    elif k == "volleyball":
        ln = g.get("lines") or []
        if g["state"] == "live" and ln:
            lab, hs, as_ = ln[-1]
            out["cset"] = {"lab": lab, "L": hs if lh else as_, "R": as_ if lh else hs}
    try:
        import plus
        w = plus.winprob(g, lh)
        if w and w.get("pts"):
            out["wp"] = {"pts": [[x["p"], x["L"], x.get("D", 0), x["R"]] for x in w["pts"]], "draw": w.get("draw"), "basis": w.get("basis")}
        if g["state"] == "final":
            out["summ"] = (plus.summary(g) or [])[:3]
    except Exception:
        pass
    return out

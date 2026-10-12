"""추가 기능 5종: 추정 승리확률 · 핫한 경기 TOP3 · 예측 리그 · 3줄 경기 요약 · 즐겨찾기 팀 웹 푸시.
원칙: 실제 기록만 사용, 불확실하면 숨김. 배당은 표시용(사전확률)일 뿐 금전과 무관."""
import os, re, json, time, math, base64, hmac, logging, threading
from datetime import datetime, timedelta
from statistics import NormalDist
from flask import Blueprint, request, jsonify, session, render_template, abort
import data, curation, members as M

log = logging.getLogger("plus")
bp = Blueprint("plus", __name__)
_N = NormalDist()


def _today():
    return datetime.now(data.SEOUL).date()


def _find(key, d=None):
    d = d or _today()
    g = data.find_game(key, d)
    if not g and d == _today():
        g = data.find_game(key, d - timedelta(days=1))
    return g


def _day():
    s = request.args.get("d") or ""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return _today()


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# =============== 1) 추정 승리확률 ===============
SIG = {"baseball": 4.3, "basketball": 12.0}
LAM = {"football": 2.7, "hockey": 6.0}


def _prior(g):
    """경기 전 배당 → (홈, 무, 원정) 확률. 없으면 None (반반 가정)."""
    try:
        import teamodds
        o = teamodds.odds(g, True)
    except Exception:
        o = None
    if not o or not o.get("H") or not o.get("A"):
        return None
    ps = [1 / o["H"], 1 / o["D"] if o.get("D") else 0.0, 1 / o["A"]]
    t = sum(ps)
    return [p / t for p in ps]


def _pois(l, k):
    return math.exp(-l) * l ** k / math.factorial(k)


def prob(kind, p, hs, as_, prior, final=False):
    """홈 기준 (승, 무, 패) 추정. p=경기 진행률 0~1."""
    d = hs - as_
    if final:
        return (1.0, 0.0, 0.0) if d > 0 else ((0.0, 0.0, 1.0) if d < 0 else (0.0, 1.0, 0.0))
    p = min(max(p, 0.0), 0.995)
    if kind in SIG:
        s = SIG[kind]
        ph = 0.5
        if prior:
            ph = prior[0] / max(1e-9, prior[0] + prior[2])
        ph = min(max(ph, 0.03), 0.97)
        m0 = s * _N.inv_cdf(ph)
        sr = s * math.sqrt(max(1 - p, 0.012))
        w = _N.cdf((d + m0 * (1 - p)) / sr)
        return (w, 0.0, 1 - w)
    lam = LAM[kind]
    sh = 0.5
    if prior:
        sh = min(max(0.5 + 0.55 * (prior[0] - prior[2]), 0.2), 0.8)
    lh, la = lam * sh * (1 - p), lam * (1 - sh) * (1 - p)
    W = D = L = 0.0
    for i in range(12):
        pi = _pois(lh, i)
        for j in range(12):
            q = pi * _pois(la, j)
            f = d + i - j
            if f > 0:
                W += q
            elif f == 0:
                D += q
            else:
                L += q
    t = W + D + L
    W, D, L = W / t, D / t, L / t
    if kind == "hockey":      # 동점이면 연장/승부치기 → 둘 중 하나가 이김
        W, L, D = W + D * sh, L + D * (1 - sh), 0.0
    return (W, D, L)


def _progress_points(g):
    """[(진행률, 홈점수, 원정점수, 라벨)] 실제 구간 기록으로만. 기록 합이 현재 점수와 다르면 None."""
    k, st = g["kind"], g["state"]
    hs, as_ = _i(g.get("home_score")), _i(g.get("away_score"))
    if hs is None or as_ is None:
        return None
    pts = [(0.0, 0, 0, "시작")]
    if k == "baseball":
        raw = g.get("innings") or {}
        hi, ai = (raw.get("home") or {}).get("inn") or {}, (raw.get("away") or {}).get("inn") or {}
        n = max([0] + [int(x) for x in list(hi) + list(ai) if str(x).isdigit()])
        h = a = 0
        for i in range(1, n + 1):
            av, hv = _i(ai.get(str(i))), _i(hi.get(str(i)))
            if av is None:
                break
            a += av
            pts.append((min((i - 0.5) / 9, 0.97), h, a, f"{i}회초"))
            if hv is None:
                break
            h += hv
            pts.append((min(i / 9, 0.985), h, a, f"{i}회말"))
        if (h, a) != (hs, as_) or len(pts) < 2:
            return None
    elif k in ("basketball", "hockey"):
        reg = 4 if k == "basketball" else 3
        lines = g.get("lines") or []
        if not lines:
            return None
        h = a = 0
        for idx, l in enumerate(lines):
            lh, la = _i(l[1]), _i(l[2])
            if lh is None or la is None:
                return None
            h += lh; a += la
            last = idx == len(lines) - 1
            pr = (idx + 1) / reg if idx < reg else 0.99
            if last and st == "live":
                pr = (idx + 0.5) / reg if idx < reg else 0.99
            lab = str(l[0])
            lab = (lab + ("Q" if k == "basketball" else "P")) if lab.isdigit() else lab
            pts.append((min(pr, 0.99), h, a, lab + (" 진행 중" if last and st == "live" else "")))
        if (h, a) != (hs, as_):
            return None
    elif k == "football":
        import plays
        gl = plays.goals(g)
        if not gl or gl.get("missing"):
            return None
        h = a = 0
        for hf in gl["halves"]:
            if hf["lab"] == "승부차기":
                continue
            for x in hf["items"]:
                m = re.match(r"(\d+)", str(x.get("min") or ""))
                if not m:
                    return None
                mn = int(m.group(1))
                if x["side"] == "home":
                    h += 1
                else:
                    a += 1
                pts.append((min(mn / 90, 0.99), h, a, f"{mn}' {x.get('who') or '득점'}"))
        if (h, a) != (hs, as_):
            return None
        if st == "live":
            m = re.search(r"(\d+)'", str(g.get("period") or ""))
            if not m:
                return None
            pts.append((min(int(m.group(1)) / 90, 0.99), h, a, f"{m.group(1)}' 현재"))
    else:
        return None
    if st == "final":
        pts.append((1.0, hs, as_, "종료"))
    return pts


def winprob(g, lh):
    if g.get("kind") not in ("baseball", "basketball", "hockey", "football") or g.get("state") not in ("live", "final"):
        return None
    if g.get("other"):
        return None
    try:
        pts = _progress_points(g)
    except Exception:
        log.exception("wp")
        return None
    if not pts or len(pts) < 3:
        return None
    pr = _prior(g)
    out = []
    for i, (p, h, a, lab) in enumerate(pts):
        w, dr, l = prob(g["kind"], p, h, a, pr, final=(g["state"] == "final" and i == len(pts) - 1))
        L, R = (w, l) if lh else (l, w)
        out.append({"p": round(p, 3), "L": round(L * 100), "D": round(dr * 100), "R": round(R * 100), "t": lab})
    return {"pts": out, "draw": g["kind"] == "football", "prior": bool(pr), "live": g["state"] == "live",
            "basis": "점수·진행 상황" + (" + 경기 전 배당" if pr else "") + " 기반 단순 모델"}


@bp.get("/api/wp/<path:key>")
def api_wp(key):
    g = _find(key, _day())
    w = winprob(g, g["kind"] != "baseball") if g else None
    r = jsonify({"ok": bool(w), **(w or {})})
    r.headers["Cache-Control"] = "public, max-age=30"
    return r


def progress(g):
    """핫 경기·알림용 현재 진행률 (모르면 None)."""
    k, stc = g["kind"], str(g.get("status") or "")
    if k == "baseball":
        m = re.match(r"IN(\d+)", stc)
        return min(int(m.group(1)) / 9, 1.0) if m else None
    if k == "basketball":
        return {"Q1": .12, "Q2": .37, "HT": .5, "BT": .5, "Q3": .62, "Q4": .87, "OT": .98}.get(stc)
    if k == "hockey":
        return {"P1": .17, "P2": .5, "P3": .83, "BT": .5, "OT": .98, "PT": .99}.get(stc)
    if k == "football":
        m = re.search(r"(\d+)'", str(g.get("period") or ""))
        if m:
            return min(int(m.group(1)) / 90, 1.0)
        return {"HT": .5, "ET": .98, "P": .99}.get(stc)
    if k == "volleyball":
        m = re.match(r"S(\d)", stc)
        return min(int(m.group(1)) / 4, 1.0) if m else None
    return None


# =============== 3) 지금 핫한 경기 TOP 3 ===============
SCALE = {"baseball": 4, "basketball": 12, "football": 2, "hockey": 2, "volleyball": 2}


def _chat_heat(key):
    try:
        import chat
        room = "game-" + str(key).replace(":", "-")
        now = time.time()
        msgs = [m for m in list(chat._rooms.get(room) or []) if now - m.get("ts", 0) < 600]
        on = len([1 for t in (chat._online.get(room) or {}).values() if now - t < 40])
        return len(msgs), on
    except Exception:
        return 0, 0


_hotc = [0, None]


@bp.get("/api/hot")
def api_hot():
    if time.time() - _hotc[0] < 20 and _hotc[1] is not None:
        return jsonify(_hotc[1])
    import app as A
    d = _today()
    games, _f = data.games_for(d)
    if datetime.now(data.SEOUL).hour < 6:
        prev, _ = data.games_for(d - timedelta(days=1))
        games = [g for g in prev if g["state"] == "live"] + games
    now = datetime.now(data.SEOUL)
    cand = []
    for g in games:
        if g["state"] != "live" or curation.hidden(g, now, True):
            continue
        hs, as_ = _i(g.get("home_score")), _i(g.get("away_score"))
        p = progress(g)
        if hs is None or as_ is None or p is None:
            continue
        diff = abs(hs - as_)
        close = max(0.0, 1 - diff / SCALE.get(g["kind"], 3))
        if close <= 0:
            continue
        msgs, on = _chat_heat(g["key"])
        heat = min(1.0, (msgs + on) / 15)
        score = 0.45 * close + 0.35 * p + 0.2 * heat
        v = A.view(g)
        tags = ["동점" if diff == 0 else f"{diff}{'세트' if g['kind'] == 'volleyball' else ('골' if g['kind'] in ('football', 'hockey') else '점')}차"]
        if msgs + on >= 3:
            tags.append(f"💬 {msgs + on}")
        cand.append((score, {"k": v["key"], "lg": v["league"], "e": v["emoji"], "L": v["L"]["name"], "R": v["R"]["name"],
                             "ls": v["L"]["score"], "rs": v["R"]["score"], "b": v["badge"], "tags": tags}))
    cand.sort(key=lambda x: -x[0])
    out = {"games": [c[1] for c in cand[:3]]}
    _hotc[:] = [time.time(), out]
    return jsonify(out)


# =============== 5) 3줄 경기 요약 ===============
def _winner(g):
    hs, as_ = _i(g.get("home_score")), _i(g.get("away_score"))
    if hs is None or as_ is None:
        return None, hs, as_
    return ("home" if hs > as_ else ("away" if as_ > hs else None)), hs, as_


def _ip(s):
    m = re.match(r"^(\d+)\.([12])$", str(s))
    if not m:
        return str(s)
    f = "1/3" if m.group(2) == "1" else "2/3"
    return f if m.group(1) == "0" else f"{m.group(1)} {f}"


def summary(g):
    """종료 경기 3줄 요약 (실제 기록만). 2줄 미만이면 None. 텔레그램 소식 포스터도 이 함수를 그대로 쓰면 돼요."""
    if not g or g.get("state") != "final":
        return None
    w, hs, as_ = _winner(g)
    if hs is None:
        return None
    H, A_ = g["home"], g["away"]
    k = g["kind"]
    sc = f"{A_} {as_} : {hs} {H}" if k == "baseball" else f"{H} {hs} : {as_} {A_}"
    lines = [f"{sc} — " + (f"{H if w == 'home' else A_} 승리" if w else "무승부")]
    try:
        if k == "football":
            import plays
            gl = plays.goals(g)
            if gl and not gl.get("missing"):
                its = [x for hf in gl["halves"] if hf["lab"] != "승부차기" for x in hf["items"]]
                if its:
                    names = {}
                    for x in its:
                        nm = (x["who"] or "득점") + (" (자책골)" if "자책" in str(x.get("kind") or "") else "")
                        names.setdefault(nm, []).append(str(x["min"]))
                    if len(its) <= 4:
                        lines.append("득점: " + ", ".join(f"{n} {'·'.join(m)}" for n, m in names.items()))
                    else:
                        top = sorted(names.items(), key=lambda kv: -len(kv[1]))
                        lines.append("득점: " + ", ".join(f"{n}" + (f" {len(m)}골" if len(m) > 1 else "") for n, m in top))
                    if w:   # 결승골: 승리팀의 (상대 최종 득점 + 1)번째 골
                        lose_n = as_ if w == "home" else hs
                        mine = [x for x in its if x["side"] == w]
                        if len(mine) > lose_n:
                            dec = mine[lose_n]
                            lines.append(f"결승골: {dec['who'] or '득점'}" + (" (자책골)" if "자책" in str(dec.get("kind") or "") else "") + f" {dec['min']}")
        elif k == "baseball":
            raw = g.get("innings") or {}
            if w:
                inn = (raw.get(w) or {}).get("inn") or {}
                best = max(((int(i), _i(r) or 0) for i, r in inn.items() if str(i).isdigit()), key=lambda x: x[1], default=None)
                if best and best[1] >= 2:
                    lines.append(f"빅이닝: {best[0]}회 {H if w == 'home' else A_} {best[1]}득점")
            import lineup
            lu = lineup.get(g)
            if lu:
                top = []
                for sd, tn in (("away", A_), ("home", H)):
                    for b in (lu.get(sd) or {}).get("bat") or []:
                        hh, rbi, hr = _i(b.get("h")) or 0, _i(b.get("rbi")) or 0, _i(b.get("hr")) or 0
                        if hh or rbi:
                            top.append((rbi * 2 + hh + hr * 2, b.get("name"), hh, rbi, hr, _i(b.get("ab"))))
                top.sort(key=lambda x: -x[0])
                if top and top[0][3] >= 2 or (top and top[0][2] >= 3):
                    t = top[0]
                    lines.append(f"수훈: {t[1]} " + (f"{t[5]}타수 " if t[5] else "") + f"{t[2]}안타" + (f" {t[4]}홈런" if t[4] else "") + (f" {t[3]}타점" if t[3] else ""))
                if len(lines) < 3:
                    for sd, tn in (("away", A_), ("home", H)):
                        for p_ in (lu.get(sd) or {}).get("pit") or []:
                            if p_.get("dec") in ("승", "W") and p_.get("ip"):
                                lines.append(f"승리투수: {p_['name']} {_ip(p_['ip'])}이닝 {p_.get('er') or 0}자책" + (f" {p_['so']}탈삼진" if p_.get("so") else ""))
                                break
            if len(lines) < 3:
                hh, ah = (raw.get("home") or {}).get("H"), (raw.get("away") or {}).get("H")
                if hh is not None and ah is not None:
                    lines.append(f"안타 {A_} {ah} · {H} {hh}")
        else:
            lines_ = g.get("lines") or []
            if lines_ and w:
                diffs = [((_i(l[1]) or 0) - (_i(l[2]) or 0)) * (1 if w == "home" else -1) for l in lines_]
                i = max(range(len(diffs)), key=lambda j: diffs[j])
                if diffs[i] > 0:
                    lab = str(lines_[i][0])
                    lab = lab + {"basketball": "쿼터", "volleyball": "세트", "hockey": "피리어드"}.get(k, "") if lab.isdigit() else lab
                    unit = {"volleyball": "점", "hockey": "골"}.get(k, "점")
                    lines.append(f"가장 크게 앞선 구간: {lab} {H if w == 'home' else A_} +{diffs[i]}{unit}")
            if k == "basketball":
                import lineup
                lu = lineup.basketball(g)
                if lu:
                    best = None
                    for sd, tn in (("home", H), ("away", A_)):
                        for x in lu.get(sd) or []:
                            pt = _i(x.get("pts"))
                            if pt is not None and (best is None or pt > best[0]):
                                best = (pt, x.get("name"), tn, _i(x.get("reb")), _i(x.get("ast")))
                    if best and best[0] >= 10:
                        lines.append(f"최다 득점: {best[1]}({best[2]}) {best[0]}점" + (f" {best[3]}리바운드" if best[3] else "") + (f" {best[4]}어시스트" if best[4] else ""))
    except Exception:
        log.exception("summary")
    lines = lines[:3]
    return lines if len(lines) >= 2 else None


def summary_text(key, d=None):
    """텔레그램 등 외부용 평문. 채널 자동 게시는 켜지 않았어요 (호출하는 쪽에서 결정)."""
    g = _find(key, d)
    s = summary(g)
    return "\n".join(s) if s else None


@bp.get("/api/summary/<path:key>")
def api_summary(key):
    g = _find(key, _day())
    s = summary(g) if g else None
    r = jsonify({"ok": bool(s), "lines": s or []})
    r.headers["Cache-Control"] = "public, max-age=600"
    return r


# =============== 4) 예측 리그 ===============
PRED_WIN, PRED_EXACT = 5, 5
_pok = [False]
_plk = threading.Lock()


def init_db():
    if not M.enabled():
        return
    try:
        M.q("""CREATE TABLE IF NOT EXISTS pred(member_id BIGINT NOT NULL, gkey TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
            pick TEXT NOT NULL, ph INTEGER, pa INTEGER, ts BIGINT NOT NULL, season TEXT NOT NULL, res TEXT, pts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(member_id, gkey))""", fetch=False)
        M.q("CREATE INDEX IF NOT EXISTS pred_open ON pred(res)", fetch=False)
        M.q("""CREATE TABLE IF NOT EXISTS push_sub(ep TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL, teams TEXT NOT NULL DEFAULT '',
            ts BIGINT NOT NULL)""", fetch=False)
        _pok[0] = True
    except Exception:
        log.exception("plus init")


def _csrf_ok():
    t = request.headers.get("X-CSRF", "")
    return bool(t) and hmac.compare_digest(t, session.get("_csrf", ""))


def _counts(key):
    rows = M.q("SELECT pick, COUNT(*) FROM pred WHERE gkey=? GROUP BY pick", (key,)) or []
    return {r[0]: int(r[1]) for r in rows}


@bp.get("/api/pred/<path:key>")
def api_pred_get(key):
    if not _pok[0]:
        return jsonify({"ok": False})
    me = M.current()
    mine = None
    if me:
        r = M.q("SELECT pick,ph,pa,res,pts FROM pred WHERE member_id=? AND gkey=?", (me["id"], key[:80]), one=True)
        if r:
            mine = {"pick": r[0], "ph": r[1], "pa": r[2], "res": r[3], "pts": r[4]}
    return jsonify({"ok": True, "login": bool(me), "mine": mine, "counts": _counts(key[:80])})


@bp.post("/api/pred")
def api_pred_post():
    me = M.current()
    if not _pok[0] or not me:
        return jsonify({"ok": False, "error": "로그인 후 참여할 수 있어요."}), 401
    if not _csrf_ok():
        return jsonify({"ok": False, "error": "새로고침 후 다시 시도해 주세요."}), 400
    b = request.get_json(silent=True) or {}
    key, pick = str(b.get("k") or "")[:80], b.get("pick")
    d = _day() if not b.get("d") else (datetime.strptime(str(b["d"])[:10], "%Y-%m-%d").date() if re.match(r"^\d{4}-\d\d-\d\d$", str(b["d"])[:10]) else _today())
    g = _find(key, d)
    if not g or pick not in ("H", "D", "A") or (pick == "D" and g["kind"] != "football"):
        return jsonify({"ok": False, "error": "잘못된 요청이에요."}), 400
    if g["state"] != "scheduled" or datetime.now(data.SEOUL) >= g["start"]:
        return jsonify({"ok": False, "error": "경기가 시작돼 예측이 마감됐어요."}), 400
    ph, pa = _i(b.get("ph")), _i(b.get("pa"))
    if ph is None or pa is None or not (0 <= ph <= 99 and 0 <= pa <= 99) or (ph > pa) != (pick == "H") or (ph == pa) != (pick == "D"):
        ph = pa = None    # 스코어는 선택. 승패와 맞지 않으면 버림
    with _plk:
        M.q("DELETE FROM pred WHERE member_id=? AND gkey=? AND res IS NULL", (me["id"], key), fetch=False)
        if M.q("SELECT 1 FROM pred WHERE member_id=? AND gkey=?", (me["id"], key), one=True):
            return jsonify({"ok": False, "error": "이미 정산된 예측이에요."}), 400
        M.q("INSERT INTO pred(member_id,gkey,day,kind,pick,ph,pa,ts,season) VALUES(?,?,?,?,?,?,?,?,?)",
            (me["id"], key, g["start"].date().isoformat(), g["kind"], pick, ph, pa, int(time.time()), str(g["start"].year)), fetch=False)
    return jsonify({"ok": True, "counts": _counts(key)})


def settle_once():
    if not _pok[0]:
        return 0
    import levels
    rows = M.q("SELECT DISTINCT gkey, day FROM pred WHERE res IS NULL") or []
    n = 0
    for key, day in rows[:200]:
        try:
            g = data.find_game(key, datetime.strptime(day, "%Y-%m-%d").date())
        except Exception:
            g = None
        if not g:
            continue
        if g["state"] in ("cancelled", "postponed"):
            M.q("UPDATE pred SET res='X' WHERE gkey=? AND res IS NULL", (key,), fetch=False)
            continue
        if g["state"] != "final":
            continue
        hs, as_ = _i(g.get("home_score")), _i(g.get("away_score"))
        if hs is None or as_ is None:
            continue
        out = "H" if hs > as_ else ("A" if as_ > hs else "D")
        with _plk:
            for mid, pick, ph, pa in M.q("SELECT member_id,pick,ph,pa FROM pred WHERE gkey=? AND res IS NULL", (key,)) or []:
                pts = (PRED_WIN if pick == out else 0) + (PRED_EXACT if pick == out and ph == hs and pa == as_ else 0)
                M.q("UPDATE pred SET res=?, pts=? WHERE member_id=? AND gkey=? AND res IS NULL",
                    ("W" if pick == out else "L", pts, mid, key), fetch=False)
                if pts:
                    levels.add_pts(mid, pts)
                n += 1
    return n


@bp.get("/predict")
def predict_page():
    season = str(_today().year)
    board, mine, me = [], [], M.current()
    if _pok[0]:
        board = M.q("""SELECT m.nick, SUM(p.pts) s, SUM(CASE WHEN p.res='W' THEN 1 ELSE 0 END) w, COUNT(*) n
                       FROM pred p JOIN members m ON m.id=p.member_id WHERE p.season=? AND p.res IN ('W','L')
                       GROUP BY m.nick HAVING SUM(p.pts)>0 ORDER BY s DESC, w DESC, n ASC LIMIT 30""", (season,)) or []
        if me:
            mine = M.q("SELECT gkey,day,pick,ph,pa,res,pts FROM pred WHERE member_id=? ORDER BY ts DESC LIMIT 15", (me["id"],)) or []
    my = []
    for k, day, pick, ph, pa, res, pts in mine:
        g = None
        try:
            g = data.find_game(k, datetime.strptime(day, "%Y-%m-%d").date())
        except Exception:
            pass
        nm = f"{g['home']} vs {g['away']}" if g else k
        pk = {"H": (g or {}).get("home", "홈") + " 승", "A": (g or {}).get("away", "원정") + " 승", "D": "무승부"}[pick]
        my.append({"k": k, "d": day, "nm": nm, "pick": pk + (f" ({ph}:{pa})" if ph is not None else ""), "res": res, "pts": pts})
    return render_template("predict.html", page="predict", board=board, my=my, season=season, win=PRED_WIN, exact=PRED_EXACT)


# =============== 2) 즐겨찾기 팀 웹 푸시 ===============
def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def vapid_pub():
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def push_on():
    return bool(vapid_pub() and os.environ.get("VAPID_PRIVATE_KEY", "").strip())


def encrypt(payload, p256dh, auth):
    """RFC 8291 (aes128gcm) Web Push 암호화."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua = _b64d(p256dh); au = _b64d(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua)
    sk = ec.generate_private_key(ec.SECP256R1())
    asp = sk.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    sec = sk.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(hashes.SHA256(), 32, au, b"WebPush: info\x00" + ua + asp).derive(sec)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(asp)]) + asp + ct


def _vapid_header(endpoint):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives import hashes
    from urllib.parse import urlparse
    u = urlparse(endpoint)
    d = int.from_bytes(_b64d(os.environ["VAPID_PRIVATE_KEY"].strip()), "big")
    key = ec.derive_private_key(d, ec.SECP256R1())
    h = _b64e(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    c = _b64e(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                          "sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@twowinscore.com")}).encode())
    r, s = decode_dss_signature(key.sign(f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={h}.{c}.{_b64e(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={vapid_pub()}"


def send(sub, msg):
    import urllib.request, urllib.error
    body = encrypt(json.dumps(msg, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["ep"], data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "600", "Urgency": "high",
        "Authorization": _vapid_header(sub["ep"])})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            M.q("DELETE FROM push_sub WHERE ep=?", (sub["ep"],), fetch=False)
        else:
            log.warning("push %s", e.code)
    except Exception as e:
        log.warning("push err %s", type(e).__name__)
    return False


_EP_OK = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[\x21-\x7e]{1,900}$")


@bp.get("/api/push/key")
def api_push_key():
    return jsonify({"ok": push_on() and _pok[0], "key": vapid_pub() if push_on() else ""})


@bp.post("/api/push/sub")
def api_push_sub():
    if not push_on() or not _pok[0]:
        return jsonify({"ok": False, "error": "알림 서버가 아직 준비되지 않았어요."}), 503
    b = request.get_json(silent=True) or {}
    s = b.get("sub") or {}
    ep, ks = str(s.get("endpoint") or ""), s.get("keys") or {}
    p, a = str(ks.get("p256dh") or ""), str(ks.get("auth") or "")
    teams = [t for t in (b.get("teams") or []) if isinstance(t, str) and re.match(r"^[a-z]{4,10}:\d{1,9}$", t)][:60]
    if not _EP_OK.match(ep) or not re.match(r"^[A-Za-z0-9_-]{80,100}$", p) or not re.match(r"^[A-Za-z0-9_-]{16,30}$", a):
        return jsonify({"ok": False, "error": "잘못된 요청이에요."}), 400
    with _plk:
        M.q("DELETE FROM push_sub WHERE ep=?", (ep,), fetch=False)
        M.q("INSERT INTO push_sub(ep,p256dh,auth,teams,ts) VALUES(?,?,?,?,?)", (ep, p, a, "," + ",".join(teams) + ",", int(time.time())), fetch=False)
    return jsonify({"ok": True, "n": len(teams)})


@bp.post("/api/push/unsub")
def api_push_unsub():
    b = request.get_json(silent=True) or {}
    ep = str(b.get("endpoint") or "")[:1000]
    if _pok[0] and ep:
        M.q("DELETE FROM push_sub WHERE ep=?", (ep,), fetch=False)
    return jsonify({"ok": True})


_seen = {}       # key -> (hs, as, leader, late_sent)
LATE = {"baseball": (8 / 9, 1), "basketball": (0.85, 5), "football": (80 / 90, 1), "hockey": (0.8, 1), "volleyball": (0.99, 0)}


def _events(g, first):
    k = str(g["key"])
    hs, as_ = _i(g.get("home_score")), _i(g.get("away_score"))
    if hs is None or as_ is None or g["state"] != "live":
        return []
    lead = "h" if hs > as_ else ("a" if as_ > hs else "")
    prev = _seen.get(k)
    p = progress(g)
    late_now = p is not None and p >= LATE.get(g["kind"], (2, 0))[0] and abs(hs - as_) <= LATE.get(g["kind"], (2, 0))[1]
    _seen[k] = (hs, as_, lead, (prev[3] if prev else False) or late_now)
    if first or not prev:
        return []
    ev = []
    sc = f"{g['away']} {as_}:{hs} {g['home']}" if g["kind"] == "baseball" else f"{g['home']} {hs}:{as_} {g['away']}"
    if g["kind"] != "basketball" and (hs, as_) != prev[:2] and hs >= prev[0] and as_ >= prev[1]:
        who = g["home"] if hs > prev[0] else g["away"]
        if prev[2] and lead and lead != prev[2]:
            ev.append(("역전!", f"{who} 역전 · {sc}"))
        else:
            ev.append(("득점", f"{who} 득점 · {sc}"))
    elif g["kind"] == "basketball" and prev[2] and lead and lead != prev[2] and (p or 0) >= 0.75:
        ev.append(("역전!", f"{g['home'] if lead == 'h' else g['away']} 역전 · {sc}"))
    if late_now and not prev[3]:
        ev.append(("막판 접전", f"{g.get('period') or ''} {sc}".strip()))
    return ev


def _push_loop():
    first = True
    while True:
        try:
            if push_on() and _pok[0]:
                gs, _ = data.games_for(_today())
                subs = None
                for g in gs:
                    for title, body in _events(g, first):
                        if subs is None:
                            subs = [{"ep": r[0], "p256dh": r[1], "auth": r[2], "teams": r[3]} for r in (M.q("SELECT ep,p256dh,auth,teams FROM push_sub") or [])]
                        tk = {f",{g['kind']}:{g.get('home_id')},", f",{g['kind']}:{g.get('away_id')},"}
                        for s in subs:
                            if any(t in s["teams"] for t in tk):
                                send(s, {"title": f"{title} · {g.get('site_league') or ''}".strip(" ·"), "body": body,
                                         "url": f"/game/{g['key']}?d={g['start'].date().isoformat()}", "tag": str(g["key"])})
                first = False
                if len(_seen) > 3000:
                    _seen.clear(); first = True
        except Exception:
            log.exception("push loop")
        time.sleep(30)


def _settle_loop():
    while True:
        time.sleep(300)
        try:
            settle_once()
        except Exception:
            log.exception("settle")


def start():
    if os.environ.get("WARMER", "1") == "0":
        return
    threading.Thread(target=_push_loop, daemon=True, name="push").start()
    threading.Thread(target=_settle_loop, daemon=True, name="settle").start()

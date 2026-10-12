"""추가 기능: 추정 승리확률 · 3줄 경기 요약.
원칙: 실제 기록만 사용, 불확실하면 숨김. 배당은 표시용(사전확률)일 뿐 금전과 무관."""
import re, math, logging
from datetime import datetime, timedelta
from statistics import NormalDist
from flask import Blueprint, request, jsonify
import data

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
        try:
            gl = plays.goals(g)
        except Exception:
            gl = None
        if not gl or gl.get("missing") or sum(len(hf["items"]) for hf in gl["halves"] if hf["lab"] != "승부차기") != hs + as_:
            return _fb_coarse(g, hs, as_)
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
            return _fb_coarse(g, hs, as_)
        if st == "live":
            mn = _fb_minute(g)
            if mn is None:
                return None
            pts.append((min(mn / 90, 0.99), h, a, "하프타임" if str(g.get("status")) == "HT" else f"{mn}' 현재"))
    else:
        return None
    if st == "final" and pts[-1][3] != "종료":
        pts.append((1.0, hs, as_, "종료"))
    return pts


def _fb_minute(g):
    m = re.search(r"(\d+)'", str(g.get("period") or ""))
    if m:
        return int(m.group(1))
    return {"HT": 45}.get(str(g.get("status") or ""))


def _fb_coarse(g, hs, as_):
    """골 시각 기록이 없을 때: 시작 → (전반 종료 점수, 기록 있을 때만) → 현재/종료 점수. 골 시각은 만들지 않아요."""
    pts = [(0.0, 0, 0, "시작")]
    ht = {l[0]: (_i(l[1]), _i(l[2])) for l in g.get("lines") or []}.get("전반")
    mn = _fb_minute(g) if g["state"] == "live" else None
    if g["state"] == "live" and mn is None:
        return None
    if ht and None not in ht and ht[0] <= hs and ht[1] <= as_ and (mn is None or mn >= 45):
        pts.append((0.5, ht[0], ht[1], "전반 종료"))
    if g["state"] == "live":
        if mn > 45 or not (len(pts) > 1):
            pts.append((min(mn / 90, 0.99), hs, as_, f"{mn}' 현재"))
    else:
        pts.append((1.0, hs, as_, "종료"))
    return pts


def winprob(g, lh):
    if g.get("kind") not in ("baseball", "basketball", "hockey", "football") or g.get("state") not in ("live", "final"):
        return None
    try:
        pts = _progress_points(g)
    except Exception:
        log.exception("wp")
        return None
    if not pts or len(pts) < 2:
        return None
    pr = _prior(g) if not g.get("other") else None
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

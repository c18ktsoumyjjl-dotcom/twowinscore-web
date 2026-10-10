"""주목 경기 선정, AI 경기 포인트(규칙 기반 문장), 팬 응원 투표. 예측·추천 없음, 기록만."""
import os, time, sqlite3, threading
from datetime import datetime
import data

TOP = {"KBO", "MLB", "NPB", "EPL", "라리가", "세리에A", "분데스리가", "리그1", "챔피언스리그", "NBA", "K리그1", "V리그 남자", "V리그 여자", "KBL", "NHL", "유로파리그"}
RIVAL = [("LG", "두산", "잠실 라이벌전"), ("레알 마드리드", "바르셀로나", "엘 클라시코"), ("맨체스터 유나이티드", "맨체스터 시티", "맨체스터 더비"),
         ("맨유", "맨시티", "맨체스터 더비"), ("아스널", "토트넘", "북런던 더비"), ("리버풀", "에버턴", "머지사이드 더비"),
         ("리버풀", "맨체스터 유나이티드", "노스웨스트 더비"), ("리버풀", "맨유", "노스웨스트 더비"), ("인테르", "AC 밀란", "밀라노 더비"),
         ("레알 마드리드", "아틀레티코", "마드리드 더비"), ("도르트문트", "샬케", "레비어 더비"), ("바이에른", "도르트문트", "데어 클라시커"),
         ("요미우리", "한신", "전통의 라이벌전"), ("양키스", "레드삭스", "전통의 라이벌전"), ("다저스", "자이언츠", "전통의 라이벌전"),
         ("레이커스", "셀틱스", "전통의 라이벌전"), ("FC 서울", "수원 삼성", "슈퍼매치"), ("울산", "포항", "동해안 더비")]


def josa(w, a, b):
    """받침 있으면 a, 없으면 b (은/는, 이/가, 과/와)."""
    c = (w or "").strip()[-1:] or "a"
    if "가" <= c <= "힣":
        return w + (a if (ord(c) - 0xAC00) % 28 else b)
    return w + b


def _streak(form):
    f = (form or "").upper()
    if not f:
        return None, 0
    last, n = f[-1], 0
    for ch in reversed(f):
        if ch != last:
            break
        n += 1
    return last, n


def _stand_rows(kind, league):
    slug = next((s for s, v in data.STANDING_SLUGS.items() if v == (kind, league)), None)
    if not slug:
        return {}
    groups, _s, _ok = data.standings(slug)    # 30분 캐시
    out = {}
    for sec, rows in groups:
        for r in rows:
            out[r["team"]] = dict(r, section=sec, n=len(rows))
    return out


_fc, _fl = {}, threading.Lock()


_busy = set()


def featured(games, views, day):
    """규칙 기반 주목 경기 3~5개. 하루 단위 5분 캐시(진행 중이면 2분). 계산(순위 조회)은 백그라운드라 요청을 막지 않는다.
    반환 (목록, 준비 중 여부)."""
    live = any(g["state"] == "live" for g in games)
    ck = day.isoformat()
    c = _fc.get(ck)
    if c and time.time() - c[0] < (120 if live else 300):
        return c[1], False
    if ck not in _busy:
        _busy.add(ck)
        def run():
            try:
                _featured(games, views, day)
            except Exception:
                pass
            finally:
                _busy.discard(ck)
        threading.Thread(target=run, daemon=True).start()
    return (c[1] if c else []), not c


def _featured(games, views, day):
    ck = day.isoformat()
    with _fl:
        stands, cand = {}, []
        for g, v in zip(games, views):
            if g["state"] in ("cancelled", "postponed"):
                continue
            lk = (g["kind"], g["league"])
            if lk not in stands:
                try:
                    stands[lk] = _stand_rows(*lk)
                except Exception:
                    stands[lk] = {}
            st = stands[lk]
            sc, tags = 0, []
            top = v["league"] in TOP
            if top:
                sc += 2
            a, b = st.get(g["home"]), st.get(g["away"])
            if a and b and a.get("section") == b.get("section") and a.get("rank") and b.get("rank"):
                r1, r2 = sorted([a["rank"], b["rank"]])
                if r2 <= 3:
                    tags.append(f"{r1}·{r2}위 맞대결"); sc += 6 if r2 == 2 else 5
                elif r2 <= 5 and r2 - r1 <= 2:
                    tags.append(f"상위권 맞대결 ({r1}·{r2}위)"); sc += 3
                elif r1 == 1:
                    lead = g["home"] if a["rank"] == 1 else g["away"]
                    tags.append(f"선두 {lead}"); sc += 2
            for nm, row in ((g["home"], a), (g["away"], b)):
                if not row:
                    continue
                k, n = _streak(row.get("form"))
                if k == "W" and n >= 3:
                    tags.append(f"{nm} {n}연승 중"); sc += n - 1
                elif k == "L" and n >= 4:
                    tags.append(f"{nm} {n}연패 중"); sc += n - 2
            for x, y, lab in RIVAL:
                if (x in g["home"] and y in g["away"]) or (y in g["home"] and x in g["away"]):
                    tags.append(lab); sc += 4; break
            if g["state"] == "live" and g.get("home_score") is not None and g.get("away_score") is not None:
                d = abs(g["home_score"] - g["away_score"])
                if d == 0:
                    tags.append("동점 진행 중"); sc += 3
                elif d == 1 and g["kind"] != "basketball":
                    tags.append("1점 차 접전 중"); sc += 3
                elif g["kind"] == "basketball" and d <= 5:
                    tags.append(f"{d}점 차 접전 중"); sc += 3
            if g["state"] == "final":
                sc -= 3
            if sc > 0:
                cand.append((sc, top, -v["lorder"], v, tags))
        cand.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        out = []
        for sc, top, _o, v, tags in cand:
            if not tags:
                if len(out) >= 3 or not top:
                    continue
                tags = [f"{v['league']} 주요 경기"]
            out.append(dict(v, tags=tags[:2]))
            if len(out) >= 5:
                break
        _fc[ck] = (time.time(), out)
        if len(_fc) > 30:
            _fc.pop(next(iter(_fc)))
        return out


def _wl(rows):
    w = sum(1 for r in rows if r["r"] == "W"); l = sum(1 for r in rows if r["r"] == "L"); d = sum(1 for r in rows if r["r"] == "D")
    return f"{w}승 {d}무 {l}패" if d else f"{w}승 {l}패"


def points(g, det, v=None):
    """기록 기반 2~3문장. 어느 쪽이 이긴다/추천 같은 말은 만들지 않는다."""
    H, A = g["home"], g["away"]
    S = []
    k = g["kind"]
    if g["state"] in ("live", "final") and g.get("home_score") is not None:
        hs, as_ = g["home_score"], g["away_score"]
        L, R, ls, rs = (A, H, as_, hs) if k == "baseball" else (H, A, hs, as_)
        if g["state"] == "live":
            S.append(f"현재 {g.get('period') or '경기 중'}, {L} {ls} : {rs} {R}로 진행되고 있어요.")
        else:
            S.append(f"경기는 {L} {ls} : {rs} {R}로 끝났어요.")
    st = (det.get("standings") or {}).get("rows") or []
    rk = {r["team"]: r for r in st}
    a, b = rk.get(H), rk.get(A)
    if a and b and a.get("rank") and b.get("rank"):
        sec = (det.get("standings") or {}).get("section") or ""
        S.append(f"{(sec + ' ') if sec else ''}순위는 {josa(H, '이', '가')} {a['rank']}위, {josa(A, '이', '가')} {b['rank']}위예요.")
    fh, fa = det.get("form_home") or [], det.get("form_away") or []
    if fh and fa:
        s = f"최근 {len(fh)}경기 {H} {_wl(fh)}, {A} {_wl(fa)}"
        extra = []
        for nm, rows in ((H, fh), (A, fa)):
            kk, n = _streak("".join(r["r"] for r in reversed(rows)))
            if n >= 3 and kk in "WL":
                extra.append(f"{nm} {n}연{'승' if kk == 'W' else '패'}")
        S.append(s + (f"이고, {' · '.join(extra)} 흐름이에요." if extra else "를 기록했어요."))
    h2 = det.get("h2h") or []
    if h2:
        hw = sum(1 for x in h2 if (x["home"] == H and x["hs"] > x["as"]) or (x["away"] == H and x["as"] > x["hs"]))
        aw = sum(1 for x in h2 if (x["home"] == A and x["hs"] > x["as"]) or (x["away"] == A and x["as"] > x["hs"]))
        dr = len(h2) - hw - aw
        S.append(f"최근 맞대결 {len(h2)}경기는 {H} {hw}승, {A} {aw}승{f', 무승부 {dr}번' if dr else ''}이었어요.")
    sp = det.get("starters") or {}
    if k == "baseball" and (sp.get("home") or sp.get("away")):
        def p(t, x):
            return f"{t} {x['name']}{'(ERA ' + str(x['era']) + ')' if x.get('era') else ''}" if x else f"{t} 미발표"
        S.append(f"선발 투수는 {p(A, sp.get('away'))}, {p(H, sp.get('home'))}예요.")
    inj = [x for x in (det.get("injuries") or []) if x.get("rows")]
    if inj and len(S) < 3:
        S.append("결장 선수는 " + ", ".join(f"{x['team']} {len(x['rows']) + (x.get('more') or 0)}명" for x in inj) + "이에요.")
    return S[:3]


# ---------- 팬 응원 투표 ----------
DB = os.path.join(data.CACHE, "votes.sqlite")
_vl = threading.Lock()


def _db():
    c = sqlite3.connect(DB, timeout=5)
    c.execute("create table if not exists v(k text, side text, n integer, primary key(k, side))")
    return c


def counts(keys):
    keys = [k for k in keys if k][:30]
    out = {k: {"L": 0, "R": 0, "D": 0} for k in keys}
    if not keys:
        return out
    with _vl:
        c = _db()
        try:
            for k, s, n in c.execute(f"select k, side, n from v where k in ({','.join('?' * len(keys))})", keys):
                out[k][s] = n
        finally:
            c.close()
    return out


def add(key, side):
    with _vl:
        c = _db()
        try:
            c.execute("insert into v values(?,?,1) on conflict(k, side) do update set n = n + 1", (key, side))
            c.commit()
        finally:
            c.close()

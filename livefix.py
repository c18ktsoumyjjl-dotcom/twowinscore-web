"""실시간 상태 보정 (모든 종목). API-Sports 가 킥오프 5분이 지나도 NS/TBD 로 멈춰 있을 때만 동작.

규칙: 네이버와 ESPN 이 같은 경기(양 팀 이름, 홈/원정 방향까지)로 맞춰지고, 두 곳의 상태(진행/하프타임/종료)·
피리어드(전후반·쿼터·이닝 초말)·분(축구 ±2분)·점수가 모두 같을 때만 그 값을 덮는다. 한 곳이라도 없거나 다르면 그대로.
API-Sports 가 NS/TBD 를 벗어나면(따라잡으면) 즉시 덮지 않는다. 덮은 경기는 g["live_src"]="naver+espn".
요청 경로를 막지 않도록 출처 응답은 30초 캐시 + 뒤에서 갱신(첫 호출은 덮지 않고 받아오기만 함).
배구(ESPN 없음)는 두 출처가 갖춰지지 않아 절대 덮지 않는다. NHL·MLB 는 네이버 이중 출처 보정이 어렵거나(NHL) API 가 이닝 점수에 늦게 따라와서, NBA 와 같이 ESPN 단독 보정(_nhl·_mlb)으로 API-Sports 점수 지연을 막는다.
"""
import re, threading, time
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import timefix as tf

SEOUL = ZoneInfo("Asia/Seoul")
TTL, MIN_AGE, MAX_AGE = 30, 5 * 60, 30 * 3600
STALE_MAX = 120          # 이보다 오래된 출처 캐시는 덮는 데 쓰지 않음(한동안 요청이 없다가 첫 요청 때 옛 점수로 되돌리는 것 방지)
LOG = deque(maxlen=50)
_c, _lk, _busy = {}, threading.Lock(), set()


KEEP_WARM = 15 * 60      # 최근 15분 안에 쓰인 출처는 뒤에서 계속 갱신(워커가 한동안 요청을 못 받아도 첫 응답부터 보정되게)
_want, _warm_on = {}, [False]


def _keep_warm():
    while True:
        time.sleep(20)
        try:
            now = time.time()
            with _lk:
                todo = [(k, f) for k, (t, f) in list(_want.items()) if now - t < KEEP_WARM]
                for k in [k for k, (t, f) in _want.items() if now - t >= KEEP_WARM]:
                    _want.pop(k, None)
            for k, f in todo:
                _bg(k, f, touch=False)
        except Exception:
            pass


def _bg(key, fn, touch=True):
    """캐시값(없으면 None) 즉시 반환, 만료면 뒤에서 갱신. STALE_MAX 보다 오래된 값은 None(덮지 않음)."""
    with _lk:
        if touch:
            _want[key] = (time.time(), fn)
            if not _warm_on[0]:
                _warm_on[0] = True
                threading.Thread(target=_keep_warm, daemon=True).start()
        hit = _c.get(key)
        fresh = hit and time.time() - hit[0] < TTL
        usable = hit and time.time() - hit[0] < STALE_MAX
        if not fresh and key not in _busy:
            _busy.add(key)
            def run():
                try:
                    v = fn()
                except Exception as e:
                    tf.log(f"livefix {key} 실패: {str(e)[:100]}"); v = None
                with _lk:
                    if len(_c) > 200:
                        _c.clear()
                    _c[key] = (time.time(), v)
                    _busy.discard(key)
            threading.Thread(target=run, daemon=True).start()
    return hit[1] if usable else None


def _naver(up, day):
    return _bg(("n", up, day), lambda: (tf._j(
        f"https://api-gw.sports.naver.com/schedule/games?fields=basic&upperCategoryId={up}&fromDate={day}&toDate={day}&size=500",
        tf.NH).get("result") or {}).get("games") or [])


def _espn(slug, ymd):
    return _bg(("e", slug, ymd), lambda: tf._j(
        f"https://site.api.espn.com/apis/site/v2/sports/{slug}/scoreboard?dates={ymd}&limit=500").get("events") or [])


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# 정규화 상태: (phase, n, half, minute)  phase: live / break / final
def _st_naver(kind, x):
    code, info = str(x.get("statusCode") or ""), str(x.get("statusInfo") or "").replace(" ", "")
    if code == "RESULT":
        return ("final", None, None, None) if "종료" in info else None
    if code != "STARTED" or x.get("suspended") or x.get("cancel"):
        return None
    if kind == "football":
        if info in ("하프타임", "전반종료"):
            return ("break", 1, None, None)
        m = re.fullmatch(r"(전반|후반)(\d+)(?:\+\d+)?'?", info)
        if not m:
            return None
        n, mi = (1 if m.group(1) == "전반" else 2), int(m.group(2))
        if n == 2 and mi <= 45:              # 네이버는 후반을 0분부터 셈(후반 4' = 49') → ESPN 누적 분으로 맞춤
            mi += 45
        return ("live", n, None, mi)
    if kind == "basketball":
        if info in ("하프타임",):
            return ("break", 2, None, None)
        m = re.fullmatch(r"(\d)쿼터", info)
        return ("live", int(m.group(1)), None, None) if m else None
    if kind == "baseball":
        m = re.fullmatch(r"(\d+)회(초|말)", info)
        return ("live", int(m.group(1)), m.group(2), None) if m else None
    return None


def _st_espn(kind, e):
    s = e.get("status") or {}
    t = s.get("type") or {}
    name, per = str(t.get("name") or ""), _int(s.get("period"))
    if t.get("completed") or t.get("state") == "post":
        return ("final", None, None, None) if name in ("STATUS_FINAL", "STATUS_FULL_TIME") else None
    if t.get("state") != "in":
        return None
    if kind == "football":
        if name == "STATUS_HALFTIME":
            return ("break", 1, None, None)
        m = re.match(r"(\d+)'", str(s.get("displayClock") or ""))
        if name in ("STATUS_FIRST_HALF", "STATUS_SECOND_HALF") and m:
            return ("live", 1 if name == "STATUS_FIRST_HALF" else 2, None, int(m.group(1)))
        return None
    if kind == "basketball":
        if name == "STATUS_HALFTIME":
            return ("break", 2, None, None)
        return ("live", per, None, None) if name == "STATUS_IN_PROGRESS" and per and per <= 4 else None
    if kind == "baseball":
        d = str(t.get("shortDetail") or t.get("detail") or "").lower()
        half = "초" if d.startswith("top") else "말" if d.startswith("bot") else None
        return ("live", per, half, None) if name == "STATUS_IN_PROGRESS" and per and half else None
    return None


def _same(a, b, kind):
    if not a or not b or a[:3] != b[:3]:
        return False
    if kind == "football" and a[0] == "live":
        return abs(a[3] - b[3]) <= 2
    return True


def _find_naver(kind, g, st):
    """(상태, 홈점수, 원정점수) 우리 홈/원정 기준. 양 팀 한글명이 정확히 같고 후보가 하나일 때만."""
    hk, ak, hits = tf._ko(g.get("home")), tf._ko(g.get("away")), {}
    for up in tf.NAVER_UP.get(kind, ()):
        for day in {(st + timedelta(hours=dh)).astimezone(SEOUL).strftime("%Y-%m-%d") for dh in (-6, 0, 6)}:
            for x in _naver(up, day) or []:
                nh, na = tf._ko(x.get("homeTeamName")), tf._ko(x.get("awayTeamName"))
                if x.get("reversedHomeAway") or not nh or not na:
                    continue
                try:
                    t = datetime.fromisoformat(x["gameDateTime"]).replace(tzinfo=SEOUL)
                except Exception:
                    continue
                if abs((t - st).total_seconds()) > 3 * 3600:
                    continue
                if (nh, na) == (hk, ak):
                    hits[x.get("gameId")] = (x, False)
                elif (nh, na) == (ak, hk):
                    hits[x.get("gameId")] = (x, True)
    if len(hits) != 1:
        return None
    x, sw = next(iter(hits.values()))
    h, a = _int(x.get("homeTeamScore")), _int(x.get("awayTeamScore"))
    s = _st_naver(kind, x)
    if s is None or h is None or a is None:
        return None
    return (s, a, h) if sw else (s, h, a)


def _find_espn(kind, g, st):
    he, ae, hits = g.get("home_en") or g.get("home"), g.get("away_en") or g.get("away"), {}
    u = st.astimezone(timezone.utc)
    for slug in tf.ESPN.get(kind, ()):
        for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in (-6, 0, 6)}:
            for e in _espn(slug, d) or []:
                try:
                    cs = e["competitions"][0]["competitors"]
                    h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                    t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if abs((t - st).total_seconds()) > 3 * 3600:
                    continue
                hn, an = tf._tnames(h), tf._tnames(a)
                if tf._en_eq(he, hn) and tf._en_eq(ae, an):
                    hits[e.get("id")] = (e, _int(h.get("score")), _int(a.get("score")))
                elif tf._en_eq(he, an) and tf._en_eq(ae, hn):
                    hits[e.get("id")] = (e, _int(a.get("score")), _int(h.get("score")))
    if len(hits) != 1:
        return None
    e, hs, as_ = next(iter(hits.values()))
    s = _st_espn(kind, e)
    if s is None or hs is None or as_ is None:
        return None
    return (s, hs, as_)


def _status(kind, s):
    """정규화 상태 → 사이트가 쓰는 API-Sports 코드와 표시 문구."""
    ph, n, half, mi = s
    if kind == "football":
        if ph == "final":
            return "FT", "종료"
        if ph == "break":
            return "HT", "하프타임"
        return ("1H" if n == 1 else "2H"), f"{'전반' if n == 1 else '후반'} {mi}'"
    if kind == "basketball":
        if ph == "final":
            return "FT", "종료"
        if ph == "break":
            return "HT", "하프타임"
        return f"Q{n}", f"{n}Q"
    if kind == "baseball":
        if ph == "final":
            return "FT", "종료"
        return f"IN{n}", f"{n}회{half}"
    return None, None


def _one(kind, g, now):
    if g.get("status") not in ("NS", "TBD"):
        return False                         # API-Sports 가 따라잡음 → 덮지 않음
    st = g.get("start")
    st = datetime.fromisoformat(st) if isinstance(st, str) else st
    if st is None or st.tzinfo is None:
        return False
    age = (now - st).total_seconds()
    if not (MIN_AGE <= age <= MAX_AGE):
        return False
    n = _find_naver(kind, g, st)
    e = _find_espn(kind, g, st)
    if not n or not e or n[1:] != e[1:] or not _same(n[0], e[0], kind):
        return False
    code, per = _status(kind, n[0])
    if not code:
        return False
    if n[0][0] == "live" and kind == "football":   # 분은 둘 중 작은 값(앞서 나가지 않게)
        code, per = _status(kind, (n[0][0], n[0][1], None, min(n[0][3], e[0][3])))
    g.update(status=code, period=per, home_score=n[1], away_score=n[2],
             status_api=g.get("status"), live_src="naver+espn", status_long=None)
    k = (g.get("key"), code, n[1], n[2])
    if not LOG or LOG[-1][1:] != k:
        LOG.append((time.time(),) + k)
        tf.log(f"livefix {g.get('key')} NS → {code} {n[1]}-{n[2]} (네이버·ESPN 일치)")
    return True


_TEN = None


def _team_en(kind, tid):
    global _TEN
    if _TEN is None:
        import json, os
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_en.json"), encoding="utf-8") as f:
                _TEN = json.load(f)
        except Exception:
            _TEN = {}
    return _TEN.get(f"{kind}:{tid}")


NBA_LEAGUE = 12
_ESPN_NBA = {"Los Angeles Clippers": "LA Clippers"}   # API-Sports 영문명 → ESPN displayName


_PST = {"POST", "PST"}
_FIN_API = {"FT", "AOT", "AP", "AET"}
HALT_LAB = {"INTR": "경기 중단", "SUSP": "일시 중단"}


def _unpostpone(g, espn_name, tag):
    """API-Sports 가 '연기(POST)'로 잘못 내보냈는데 ESPN 은 정상 예정(STATUS_SCHEDULED)이면 예정으로 되돌린다.
    ESPN 도 연기·취소면(STATUS_POSTPONED 등) 그대로 둔다. 점수는 만들지 않는다."""
    if str(g.get("status") or "") not in _PST or espn_name != "STATUS_SCHEDULED":
        return False
    old = g.get("status")
    g.update(status="NS", period=None, home_score=None, away_score=None, status_api=old,
             live_src=f"espn-{tag.lower()}", status_long=None, halt_reason=None)
    k = (g.get("key"), "NS", None, None)
    if not LOG or LOG[-1][1:] != k:
        LOG.append((time.time(),) + k)
        tf.log(f"livefix {tag} {g.get('key')} {old} → NS (ESPN 정상 예정, API 연기 표시 무시)")
    return True


def _nba(g, now):
    """NBA 전용: API-Sports 점수가 뒤집히거나 늦을 때 ESPN 으로 덮는다.
    양 팀 영문 정식명(team_en.json)이 ESPN displayName 과 정확히 같고, 홈/원정 방향도 같고, 후보가 하나일 때만."""
    if g.get("kind") != "basketball" or g.get("league") != NBA_LEAGUE:
        return False
    st = g.get("start")
    st = datetime.fromisoformat(st) if isinstance(st, str) else st
    if st is None or st.tzinfo is None:
        return False
    age = (now - st).total_seconds()
    lo = -12 * 3600 if str(g.get("status") or "") in _PST else -15 * 60   # API '연기' 표시는 경기 전에도 ESPN 으로 확인
    if not (lo <= age <= 30 * 3600):   # 종료 경기도 그날(KST) 내내 ESPN 과 맞춤(API-Sports 점수 뒤바뀜 보정)
        return False
    he, ae = _team_en("basketball", g.get("home_id")), _team_en("basketball", g.get("away_id"))
    he, ae = _ESPN_NBA.get(he, he), _ESPN_NBA.get(ae, ae)   # ESPN 표기가 다른 팀(클리퍼스)
    if not he or not ae or he == ae:
        return False
    u, hits = st.astimezone(timezone.utc), {}
    for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in (-6, 0, 6)}:
        for e in _espn("basketball/nba", d) or []:
            try:
                cs = e["competitions"][0]["competitors"]
                h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((t - st).total_seconds()) > 3 * 3600:
                continue
            hn, an = (h.get("team") or {}).get("displayName"), (a.get("team") or {}).get("displayName")
            if {hn, an} & {he, ae} and (hn, an) != (he, ae):
                return False                  # 방향이 다르거나 한 팀만 일치 → 불확실, 덮지 않음
            if (hn, an) == (he, ae):
                hits[e.get("id")] = (e, h, a)
    if len(hits) != 1:
        return False
    e, h, a = next(iter(hits.values()))
    hs, as_ = _int(h.get("score")), _int(a.get("score"))
    s = e.get("status") or {}
    t = s.get("type") or {}
    name, per = str(t.get("name") or ""), _int(s.get("period")) or 0
    if hs is None or as_ is None:
        return False
    if t.get("state") == "post":
        if name != "STATUS_FINAL":
            return False
        code, lab = ("AOT", "연장 종료") if per > 4 else ("FT", "종료")
    elif t.get("state") == "in":
        if name == "STATUS_HALFTIME":
            code, lab = "HT", "하프타임"
        elif name == "STATUS_END_PERIOD" and 1 <= per <= 4 and per != 2:
            code, lab = "BT", "휴식"
        elif per > 4:
            code, lab = "OT", "OT"
        elif 1 <= per <= 4:
            code, lab = f"Q{per}", f"{per}Q"
        else:
            return False
    elif t.get("state") == "pre":
        return _unpostpone(g, name, "NBA")
    else:
        return False
    lines = []
    try:
        hl, al = h.get("linescores") or [], a.get("linescores") or []
        for i, (x, y) in enumerate(zip(hl, al)):
            lines.append([f"{i + 1}Q" if i < 4 else "OT", int(float(x.get("value"))), int(float(y.get("value")))])
    except Exception:
        lines = None
    if lines and (sum(l[1] for l in lines) != hs or sum(l[2] for l in lines) != as_):
        lines = [l for l in lines[:-1]] if (sum(l[1] for l in lines[:-1]) <= hs and sum(l[2] for l in lines[:-1]) <= as_) else []
    old = (g.get("status"), g.get("home_score"), g.get("away_score"))
    if old == (code, hs, as_):
        return False
    oh, oa = _int(g.get("home_score")), _int(g.get("away_score"))
    if code not in ("FT", "AOT") and oh is not None and oa is not None and oh >= hs and oa >= as_ and oh + oa > hs + as_:
        return False                          # API-Sports 가 양 팀 모두 앞서 있음(ESPN 이 늦음) → 되돌리지 않음. 한쪽만 크면 뒤집힘 → ESPN
    g.update(status=code, period=lab, home_score=hs, away_score=as_, status_api=g.get("status"),
             live_src="espn-nba", status_long=None)
    if lines is not None:
        g["lines"] = lines
    k = (g.get("key"), code, hs, as_)
    if not LOG or LOG[-1][1:] != k:
        LOG.append((time.time(),) + k)
        tf.log(f"livefix NBA {g.get('key')} {old} → {code} {hs}-{as_} (ESPN)")
    return True


NHL_LEAGUE = 57


def _nhl(g, now):
    """NHL 전용: API-Sports 점수가 늦을 때 ESPN 으로 덮는다.
    양 팀 영문 정식명(team_en.json)이 ESPN displayName 과 정확히 같고, 홈/원정 방향도 같고, 후보가 하나일 때만."""
    if g.get("kind") != "hockey" or g.get("league") != NHL_LEAGUE:
        return False
    st = g.get("start")
    st = datetime.fromisoformat(st) if isinstance(st, str) else st
    if st is None or st.tzinfo is None:
        return False
    age = (now - st).total_seconds()
    lo = -12 * 3600 if str(g.get("status") or "") in _PST else -15 * 60   # API '연기' 표시는 경기 전에도 ESPN 으로 확인
    if not (lo <= age <= 30 * 3600):   # 종료 경기도 그날(KST) 내내 ESPN 과 맞춤(API-Sports 점수 뒤바뀜 보정)
        return False
    he, ae = _team_en("hockey", g.get("home_id")), _team_en("hockey", g.get("away_id"))
    if not he or not ae or he == ae:
        return False
    u, hits = st.astimezone(timezone.utc), {}
    for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in (-6, 0, 6)}:
        for e in _espn("hockey/nhl", d) or []:
            try:
                cs = e["competitions"][0]["competitors"]
                h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((t - st).total_seconds()) > 3 * 3600:
                continue
            hn, an = (h.get("team") or {}).get("displayName"), (a.get("team") or {}).get("displayName")
            if {hn, an} & {he, ae} and (hn, an) != (he, ae):
                return False                  # 방향이 다르거나 한 팀만 일치 → 불확실, 덮지 않음
            if (hn, an) == (he, ae):
                hits[e.get("id")] = (e, h, a)
    if len(hits) != 1:
        return False
    e, h, a = next(iter(hits.values()))
    hs, as_ = _int(h.get("score")), _int(a.get("score"))
    s = e.get("status") or {}
    t = s.get("type") or {}
    name, per = str(t.get("name") or ""), _int(s.get("period")) or 0
    if hs is None or as_ is None:
        return False
    if t.get("state") == "post":
        if name != "STATUS_FINAL":
            return False
        if per > 3:
            # ESPN 은 연장·슛아웃 모두 period>3 인 경우가 많아 AOT 로 두고, 슛아웃 전용 AP 는 shortDetail 로만 구분
            detail = str(t.get("shortDetail") or t.get("detail") or "").lower()
            code, lab = ("AP", "슛아웃 종료") if "so" in detail or "shootout" in detail else ("AOT", "연장 종료")
        else:
            code, lab = "FT", "종료"
    elif t.get("state") == "in":
        if name == "STATUS_END_PERIOD" and 1 <= per <= 3:
            code, lab = "BT", "휴식"
        elif per > 3:
            detail = str(t.get("shortDetail") or t.get("detail") or "").lower()
            code, lab = ("PT", "슛아웃") if "so" in detail or "shootout" in detail else ("OT", "연장")
        elif name == "STATUS_IN_PROGRESS" and 1 <= per <= 3:
            code, lab = f"P{per}", f"{per}피리어드"
        else:
            return False
    elif t.get("state") == "pre":
        return _unpostpone(g, name, "NHL")
    else:
        return False
    lines = []
    try:
        hl, al = h.get("linescores") or [], a.get("linescores") or []
        for i, (x, y) in enumerate(zip(hl, al)):
            lab_i = f"{i + 1}P" if i < 3 else ("OT" if i == 3 else "SO")
            lines.append([lab_i, int(float(x.get("value"))), int(float(y.get("value")))])
    except Exception:
        lines = None
    if lines and (sum(l[1] for l in lines) != hs or sum(l[2] for l in lines) != as_):
        lines = [l for l in lines[:-1]] if (sum(l[1] for l in lines[:-1]) <= hs and sum(l[2] for l in lines[:-1]) <= as_) else []
    old = (g.get("status"), g.get("home_score"), g.get("away_score"))
    if old == (code, hs, as_):
        return False
    oh, oa = _int(g.get("home_score")), _int(g.get("away_score"))
    if code not in ("FT", "AOT", "AP") and oh is not None and oa is not None and oh >= hs and oa >= as_ and oh + oa > hs + as_:
        return False                          # API-Sports 가 양 팀 모두 앞서 있음(ESPN 이 늦음) → 되돌리지 않음. 한쪽만 크면 뒤집힘 → ESPN
    g.update(status=code, period=lab, home_score=hs, away_score=as_, status_api=g.get("status"),
             live_src="espn-nhl", status_long=None)
    if lines is not None:
        g["lines"] = lines
    k = (g.get("key"), code, hs, as_)
    if not LOG or LOG[-1][1:] != k:
        LOG.append((time.time(),) + k)
        tf.log(f"livefix NHL {g.get('key')} {old} → {code} {hs}-{as_} (ESPN)")
    return True



MLB_LEAGUE = 1


def _mlb(g, now):
    """MLB 전용: API-Sports 이닝 점수가 늦을 때 ESPN 으로 덮는다.
    양 팀 영문 정식명(team_en.json)이 ESPN displayName 과 정확히 같고, 홈/원정 방향도 같고, 후보가 하나일 때만."""
    if g.get("kind") != "baseball" or g.get("league") != MLB_LEAGUE:
        return False
    st = g.get("start")
    st = datetime.fromisoformat(st) if isinstance(st, str) else st
    if st is None or st.tzinfo is None:
        return False
    age = (now - st).total_seconds()
    lo = -12 * 3600 if str(g.get("status") or "") in _PST else -15 * 60
    if not (lo <= age <= 30 * 3600):   # 종료 경기도 그날(KST) 내내 ESPN 과 맞춤(API-Sports 점수 뒤바뀜 보정)
        return False
    he, ae = _team_en("baseball", g.get("home_id")), _team_en("baseball", g.get("away_id"))
    if not he or not ae or he == ae:
        return False
    u, hits = st.astimezone(timezone.utc), {}
    for d in {(u + timedelta(hours=dh)).strftime("%Y%m%d") for dh in (-6, 0, 6)}:
        for e in _espn("baseball/mlb", d) or []:
            try:
                cs = e["competitions"][0]["competitors"]
                h = next(c for c in cs if c.get("homeAway") == "home"); a = next(c for c in cs if c.get("homeAway") == "away")
                t = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((t - st).total_seconds()) > 3 * 3600:
                continue
            hn, an = (h.get("team") or {}).get("displayName"), (a.get("team") or {}).get("displayName")
            if {hn, an} & {he, ae} and (hn, an) != (he, ae):
                return False
            if (hn, an) == (he, ae):
                hits[e.get("id")] = (e, h, a)
    if len(hits) != 1:
        return False
    e, h, a = next(iter(hits.values()))
    hs, as_ = _int(h.get("score")), _int(a.get("score"))
    s = e.get("status") or {}
    t = s.get("type") or {}
    name, per = str(t.get("name") or ""), _int(s.get("period")) or 0
    if hs is None or as_ is None:
        return False
    detail = str(t.get("shortDetail") or t.get("detail") or "").lower()
    if t.get("state") == "post" and name in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED"):
        # ESPN '연기/취소'인데 API-Sports 가 점수 없이 FT(종료)로 내보낸 경우 → 연기/취소로(점수는 만들지 않음)
        if str(g.get("status") or "") in _FIN_API and g.get("home_score") is None and g.get("away_score") is None:
            old = g.get("status")
            new = "POST" if "POSTPONED" in name else "CANC"
            g.update(status=new, period=None, status_api=old, live_src="espn-mlb", status_long=None, halt_reason=None)
            tf.log(f"livefix MLB {g.get('key')} {old}(점수 없음) → {new} (ESPN {name})")
            return True
        return False
    if t.get("state") == "post":
        if name != "STATUS_FINAL":
            return False
        code, lab = ("AOT", "연장 종료") if per > 9 else ("FT", "종료")
    elif t.get("state") == "in" and ("DELAY" in name or "SUSPEND" in name):
        # ESPN '지연/서스펜디드'(예: "Delayed, Top 1st"): API-Sports 가 점수 없이 FT 로 내보내도 종료로 두지 않고 중단으로.
        last = detail.split(",")[-1].strip()
        half = "초" if last.startswith(("top", "mid")) else "말" if last.startswith(("bot", "end")) else None
        code = "SUSP" if "SUSPEND" in name else "INTR"
        lab = HALT_LAB[code]
        g["halt_reason"] = ("서스펜디드" if code == "SUSP" else "경기 지연") + (f" ({per}회{half})" if per and half else "")
    elif t.get("state") == "in":
        if not per:
            return False
        if detail.startswith("top") or detail.startswith("mid"):
            half = "초"
        elif detail.startswith("bot") or detail.startswith("end"):
            half = "말"
        else:
            return False
        code, lab = f"IN{per}", f"{per}회{half}"
    elif t.get("state") == "pre":
        if str(g.get("status") or "") in _FIN_API and g.get("home_score") is None and g.get("away_score") is None:
            # API-Sports 가 시작 전 경기를 점수 없이 FT 로 내보낸 경우 → ESPN 기준 예정으로 되돌림(점수는 만들지 않음)
            old = g.get("status")
            g.update(status="NS", status_api=old, live_src="espn-mlb", status_long=None)
            tf.log(f"livefix MLB {g.get('key')} {old}(점수 없음) → NS (ESPN {name})")
            return True
        return _unpostpone(g, name, "MLB")
    else:
        return False
    # 이닝표·안타·실책(표시용). 점수 합과 안 맞으면 마지막 이닝만 잘라 ESPN 총점과 맞춤.
    inn = {"home": {"inn": {}, "H": _int(h.get("hits")), "E": _int(h.get("errors"))},
           "away": {"inn": {}, "H": _int(a.get("hits")), "E": _int(a.get("errors"))}}
    try:
        for side, node in (("home", h), ("away", a)):
            for i, ls in enumerate(node.get("linescores") or []):
                inn[side]["inn"][str(i + 1)] = int(float(ls.get("value")))
        sh = sum(inn["home"]["inn"].values())
        sa = sum(inn["away"]["inn"].values())
        if sh != hs or sa != as_:
            # 진행 중 이닝이 아직 총점에 덜 반영된 경우 등 → 이닝표만 버리고 총점은 ESPN 유지
            if sh > hs or sa > as_:
                inn = None
    except Exception:
        inn = None
    old = (g.get("status"), g.get("home_score"), g.get("away_score"))
    if old == (code, hs, as_):
        return False
    oh, oa = _int(g.get("home_score")), _int(g.get("away_score"))
    if code not in ("FT", "AOT") and oh is not None and oa is not None and oh >= hs and oa >= as_ and oh + oa > hs + as_:
        return False
    g.update(status=code, period=lab, home_score=hs, away_score=as_, status_api=g.get("status"),
             live_src="espn-mlb", status_long=None)
    if inn is not None:
        g["innings"] = inn
    k = (g.get("key"), code, hs, as_)
    if not LOG or LOG[-1][1:] != k:
        LOG.append((time.time(),) + k)
        tf.log(f"livefix MLB {g.get('key')} {old} → {code} {hs}-{as_} (ESPN)")
    return True


# 리그 공식 발표로 연기됐는데 API-Sports 가 아직 예정(NS/TBD)으로 내보내는 경기. 원래 킥오프(ts)가 그대로일 때만 '연기'로 바꾼다
# (API 가 새 날짜로 옮기거나 상태를 바꾸면 자동으로 손 뗌). 출처 URL 필수, 추측으로 넣지 않는다.
_SPL_MW9 = "https://www.spl.com.sa/en/news/spl-reschedules-three-fixtures-mw9"
OFFICIAL_PST = {
    "football:307:1603044": (1792087200, "리그 공식 일정 변경 (2027.3.6 개최)", _SPL_MW9),   # 알아흘리–알나스르
    "football:307:1603051": (1792162800, "리그 공식 일정 변경 (2026.12.19 개최)", _SPL_MW9),  # 알리야드–알힐랄
    "football:307:1603048": (1792173600, "리그 공식 일정 변경 (2026.12.19 개최)", _SPL_MW9),  # 알이티하드–알샤바브
}


def _official_pst(g):
    o = OFFICIAL_PST.get(str(g.get("key")))
    if not o or str(g.get("status") or "") not in ("NS", "TBD"):
        return False
    try:
        st = g["start"] if isinstance(g["start"], datetime) else datetime.fromisoformat(str(g["start"]))
        if abs(st.timestamp() - o[0]) > 60:
            return False
    except Exception:
        return False
    g.update(status="PST", status_api=g.get("status"), halt_reason=o[1], live_src="official")
    return True


def apply(kind, games):
    for g in games:
        try:
            _official_pst(g)
        except Exception:
            pass
    if kind == "basketball":
        now = datetime.now(SEOUL)
        for g in games:
            try:
                _nba(g, now)
            except Exception as ex:
                tf.log(f"livefix NBA {g.get('key')} 오류: {str(ex)[:100]}")
    if kind == "hockey":
        now = datetime.now(SEOUL)
        for g in games:
            try:
                _nhl(g, now)
            except Exception as ex:
                tf.log(f"livefix NHL {g.get('key')} 오류: {str(ex)[:100]}")
    if kind == "baseball":
        now = datetime.now(SEOUL)
        for g in games:
            try:
                _mlb(g, now)
            except Exception as ex:
                tf.log(f"livefix MLB {g.get('key')} 오류: {str(ex)[:100]}")
    if not tf.ESPN.get(kind) or not tf.NAVER_UP.get(kind):
        return games
    now = datetime.now(SEOUL)
    for g in games:
        try:
            _one(kind, g, now)
        except Exception as ex:
            tf.log(f"livefix {g.get('key')} 오류: {str(ex)[:100]}")
    return games


def status():
    return {"overlaid": [{"t": t, "key": k, "status": c, "score": f"{h}-{a}"} for t, k, c, h, a in LOG]}

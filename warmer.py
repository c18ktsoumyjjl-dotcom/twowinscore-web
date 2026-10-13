"""경기 상세 미리 받기(워머).
오늘(KST) 주 목록·기타 리그 전 경기 + 내일 새벽(06시 전) 경기의 상세·요약·승률·중계·라인업·배당을 미리 캐시해서 경기 화면 첫 방문도 바로 열리게 해요.
- 우선순위: 진행 중 → 3시간 안에 시작 → 나머지 예정 → 끝난 경기(각각 주 목록 먼저). 종목별 하루 한도 25% 넘으면 그 종목 쉼(/status).
- 진행 중: 상세 TTL(30분)마다 갱신 · 예정: 캐시 없거나 3시간 안이면 TTL(15분)마다 · 끝난 경기: 한 번만
- 속도 제한: 워머 자신은 분당 최대 WARM_PER_MIN 회 API, 경기 사이 최소 GAP 초. 전체 API 호출이 분당 GLOBAL_SOFT 를 넘으면 쉼(라이브 갱신 우선).
- gunicorn 워커가 여러 개여도 파일 잠금으로 하나만 돌아요."""
import os, json, time, fcntl, threading, logging, urllib.request
from datetime import datetime, timedelta
from collections import deque
import data

log = logging.getLogger("warmer")
WARM_PER_MIN = int(os.environ.get("WARM_PER_MIN", "30"))
GLOBAL_SOFT = int(os.environ.get("WARM_GLOBAL_SOFT", "120"))
GAP = 2.0
LOOP = 60
STATUS = os.path.join(data.CACHE, "warmer_status.json")

# ---- api-sports 호출 수 세기 (프로세스 전체 / 워머 몫) ----
_tl = threading.local()
_calls_all, _calls_warm = deque(), deque()
_tot = {"all": 0, "warm": 0, "since": time.time()}
_orig = urllib.request.urlopen


def _counting_urlopen(req, *a, **k):
    try:
        u = req.full_url if hasattr(req, "full_url") else str(req)
        if "api-sports.io" in u and "media.api-sports.io" not in u:
            now = time.time()
            _calls_all.append(now); _tot["all"] += 1
    except Exception:
        pass
    return _orig(req, *a, **k)


def _per_min(dq):
    cut = time.time() - 60
    while dq and dq[0] < cut:
        dq.popleft()
    return len(dq)


_done = {}      # key -> 마지막으로 데운 시각
_stat = {"warmed": 0, "errors": 0, "last": None, "queue": 0, "day_warm": 0, "day": ""}


QUOTA_CAP = float(os.environ.get("WARM_QUOTA_CAP", "0.25"))   # 종목별 하루 한도의 25% 넘으면 그 종목은 미리 받기 쉼
SOON = 3 * 3600


def _secs_to_start(g):
    try:
        return (g["start"] - datetime.now(data.SEOUL)).total_seconds()
    except Exception:
        return 10 ** 9


def _tier(g):
    """0=진행 중, 1=곧 시작(3시간 안), 2=나머지 예정, 3=끝남"""
    st = g.get("state")
    if st == "live":
        return 0
    if st == "scheduled":
        return 1 if _secs_to_start(g) < SOON else 2
    return 3


# 다시 데우는 간격(초). 각 함수가 자기 캐시 TTL 을 갖고 있어서, 신선하면 API 를 안 부름.
REWARM = {0: 10 * 60, 1: 15 * 60, 2: 60 * 60, 3: None}


def _due(g, now):
    last = _done.get(g["key"])
    if last is None:
        return True
    iv = REWARM[_tier(g)]
    return iv is not None and now - last > iv


def _games():
    """오늘(KST) 주 목록 + 기타 리그 전부 + 내일 새벽(06시 전) 경기."""
    now = datetime.now(data.SEOUL)
    t = now.date()
    gs = list(data.games_for(t)[0]) + list(data.others_for(t, refresh=False))
    try:
        t2 = t + timedelta(days=1)
        lim = datetime.combine(t2, datetime.min.time(), tzinfo=data.SEOUL) + timedelta(hours=6)
        g2 = list(data.games_for(t2)[0]) + list(data.others_for(t2, refresh=False))
        gs += [g for g in g2 if g.get("start") and g["start"] < lim]
    except Exception:
        pass
    seen, out = set(), []
    for g in gs:
        if g["key"] in seen:
            continue
        seen.add(g["key"]); out.append(g)
    return out


_qstate = {}


def _quota_ok(kind):
    """/status(할당량 미포함, 10분 캐시)로 확인. 25% 넘으면 False. 확인 실패하면 보수적으로 라이브만 허용."""
    try:
        q = data.quota(kind)
    except Exception:
        q = None
    if not q or not q[1]:
        _qstate[kind] = None
        return None
    r = q[0] / q[1]
    _qstate[kind] = round(r * 100, 2)
    return r < QUOTA_CAP


def _warm_one(g):
    """경기 상세 페이지(/game)와 그 페이지가 부르는 API 가 쓰는 캐시를 전부 채움."""
    import plus, plays, teamodds
    lh = g["kind"] != "baseball"
    data.detail(g)
    for fn in (lambda: plus.summary(g), lambda: plus.winprob(g, lh), lambda: plays.commentary(g),
               lambda: teamodds.odds(g), lambda: teamodds.odds(g, True), lambda: _lineup(g)):
        try:
            fn()
        except Exception as e:
            log.debug("warm part %s: %s", g["key"], e)
        time.sleep(0.3)                    # 한 경기 안에서도 쉬어서 손님 요청이 먼저 처리되게


def _lineup(g):
    import lineup
    k = g["kind"]
    if k == "baseball":
        return lineup.get(g)
    if k == "basketball":
        return lineup.basketball(g)
    if k == "football":
        return lineup.football(g)


def _save():
    try:
        s = dict(_stat, calls_all_min=_per_min(_calls_all), calls_warm_min=_per_min(_calls_warm),
                 calls_all=_tot["all"], calls_warm=_tot["warm"], since=_tot["since"], pid=os.getpid(), ts=time.time())
        tmp = STATUS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, default=str)
        os.replace(tmp, STATUS)
    except Exception:
        pass


def _loop(order):
    time.sleep(20)                         # 시작 직후 첫 요청들 먼저
    while True:
        t0 = time.time()
        try:
            day = datetime.now(data.SEOUL).strftime("%Y-%m-%d")
            if _stat["day"] != day:
                _stat.update(day=day, day_warm=0)
                _done.clear()
            now = time.time()
            ok = {}
            gs = []
            for g in _games():
                if not _due(g, now):
                    continue
                k = g["kind"]
                if k not in ok:
                    ok[k] = _quota_ok(k)
                # 한도 25% 넘음: 그 종목은 쉼. 확인 실패(None): 진행 중/곧 시작만.
                if ok[k] is False or (ok[k] is None and _tier(g) > 1):
                    continue
                gs.append(g)
            gs.sort(key=lambda g: (_tier(g), 1 if g.get("other") else 0, order(g.get("site_league"), g.get("site_order")),
                                   g.get("start") or datetime.max.replace(tzinfo=data.SEOUL)))
            _stat["queue"] = len(gs); _stat["quota_pct"] = dict(_qstate)
            for g in gs:
                if time.time() - t0 > LOOP * 5:
                    break
                while _per_min(_calls_warm) >= WARM_PER_MIN or _per_min(_calls_all) >= GLOBAL_SOFT:
                    time.sleep(5)
                before = _tot["all"]
                try:
                    _warm_one(g)
                    _stat["warmed"] += 1; _stat["day_warm"] += 1; _done[g["key"]] = time.time()
                except Exception as e:
                    _stat["errors"] += 1; _done[g["key"]] = time.time(); log.warning("warm %s: %s", g["key"], e)
                finally:
                    n = _tot["all"] - before
                    tnow = time.time()
                    _calls_warm.extend([tnow] * n); _tot["warm"] += n
                _stat["queue"] -= 1; _stat["last"] = datetime.now(data.SEOUL).strftime("%H:%M:%S")
                _save()
                time.sleep(GAP if n else 0.5)
        except Exception as e:
            log.warning("warmer loop: %s", e)
        _save()
        time.sleep(max(5, LOOP - (time.time() - t0)))


_od_tried = {}


def _odds_loop():
    """경기 시작 전 배당을 미리 받아 디스크 스냅샷으로 남겨요(아무도 안 열어본 경기도 종료 후 배당 표시)."""
    import teamodds, curation
    time.sleep(60)
    n = 0
    while True:
        try:
            now = datetime.now(data.SEOUL)
            t = now.date()
            gs = list(data.games_for(t)[0]) + list(data.others_for(t, refresh=False))
            try:
                gs += list(data.games_for(t + timedelta(days=1))[0]) + list(data.others_for(t + timedelta(days=1), refresh=False))
            except Exception:
                pass
            cnt = 0
            # 오늘·내일 경기 전 전부(가까운 경기부터). 첫 화면 HTML에 배당을 같이 넣으려면 디스크 스냅샷에 미리 있어야 해서요.
            gs = sorted((g for g in gs if g.get("state") == "scheduled" and g.get("id") and g.get("start")), key=lambda g: g["start"])
            for g in gs:
                mins = (g["start"] - now).total_seconds() / 60
                if not (0 < mins < 2880) or curation.hidden(g, now, g["start"].date() == t or mins < 1440):
                    continue
                sv = teamodds.snap_get(g["kind"], g["id"])
                age = 40 * 60 if mins < 360 else 120 * 60   # 6시간 안: 40분, 그 뒤: 2시간마다
                if sv and time.time() - sv.get("saved", 0) < age:
                    continue
                tk = (g["kind"], g["id"])
                if time.time() - _od_tried.get(tk, 0) < age:   # 제공처에 배당 없음 → 같은 간격 동안 다시 안 물어요
                    continue
                _od_tried[tk] = time.time()
                teamodds.odds(g)
                cnt += 1
                if cnt >= 80:
                    break
                time.sleep(1.5)
            n += 1
            if n % 50 == 1:
                teamodds.snap_prune()
        except Exception as e:
            log.warning("odds prefetch: %s", e)
        time.sleep(300)


_lockf = [None]


def start(order):
    urllib.request.urlopen = _counting_urlopen
    if os.environ.get("WARMER", "1") == "0":
        return False
    try:
        os.makedirs(data.CACHE, exist_ok=True)
        f = open(os.path.join(data.CACHE, "warmer.lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False                       # 다른 워커가 이미 돌리는 중
    _lockf[0] = f
    threading.Thread(target=_loop, args=(order,), daemon=True, name="warmer").start()
    threading.Thread(target=_odds_loop, daemon=True, name="odds-prefetch").start()
    log.info("warmer started pid=%s", os.getpid())
    return True


def status():
    try:
        with open(STATUS) as f:
            return json.load(f)
    except Exception:
        return None

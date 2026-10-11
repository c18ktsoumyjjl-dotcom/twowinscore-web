"""경기 상세 미리 받기(워머).
오늘(KST) 경기 + 내일 새벽(06시 전) 경기의 상세 자료를 미리 캐시해서 경기 화면 첫 방문도 바로 열리게 해요.
- 우선순위: 진행 중 / 3시간 안에 시작 → 인기 리그(LEAGUE_POP) → 시작 시간
- 진행 중: 상세 TTL(30분)마다 갱신 · 예정: 캐시 없거나 3시간 안이면 TTL(15분)마다 · 끝난 경기: 한 번만
- 속도 제한: 워머 자신은 분당 최대 WARM_PER_MIN 회 API, 경기 사이 최소 GAP 초. 전체 API 호출이 분당 GLOBAL_SOFT 를 넘으면 쉼(라이브 갱신 우선).
- gunicorn 워커가 여러 개여도 파일 잠금으로 하나만 돌아요."""
import os, json, time, fcntl, threading, logging, urllib.request
from datetime import datetime, timedelta
from collections import deque
import data

log = logging.getLogger("warmer")
WARM_PER_MIN = int(os.environ.get("WARM_PER_MIN", "20"))
GLOBAL_SOFT = int(os.environ.get("WARM_GLOBAL_SOFT", "120"))
GAP = 3.0
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


def _ttl(g):
    return 30 * 60 if g["state"] != "scheduled" else 15 * 60


def _due(g, now):
    name = "detail_" + str(g["key"]).replace(":", "_") + ".json"
    c = data._rd(name)
    age = now - c["ts"] if c else None
    soon = g["state"] == "scheduled" and g.get("start") and (g["start"] - datetime.now(data.SEOUL)).total_seconds() < 3 * 3600
    if c is None:
        return True
    if g["state"] == "live":
        return age > _ttl(g)
    if g["state"] == "finished":
        return False                      # 끝난 경기는 한 번만
    return bool(soon) and age > _ttl(g)


def _games():
    now = datetime.now(data.SEOUL)
    t = now.date()
    gs, _ = data.games_for(t)
    try:
        g2, _ = data.games_for(t + timedelta(days=1))
        lim = datetime.combine(t + timedelta(days=1), datetime.min.time(), tzinfo=data.SEOUL) + timedelta(hours=6)
        gs += [g for g in g2 if g.get("start") and g["start"] < lim]
    except Exception:
        pass
    return gs


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
            now = time.time()
            gs = [g for g in _games() if _due(g, now)]
            def pri(g):
                hot = g["state"] == "live" or (g["state"] == "scheduled" and g.get("start") and (g["start"] - datetime.now(data.SEOUL)).total_seconds() < 3 * 3600)
                return (0 if hot else 1, order(g.get("site_league"), g.get("site_order")), g.get("start") or datetime.max.replace(tzinfo=data.SEOUL))
            gs.sort(key=pri)
            _stat["queue"] = len(gs)
            for g in gs:
                if time.time() - t0 > LOOP * 5:
                    break
                while _per_min(_calls_warm) >= WARM_PER_MIN or _per_min(_calls_all) >= GLOBAL_SOFT:
                    time.sleep(5)
                before = _tot["all"]
                try:
                    with data._flight("detail:" + str(g["key"])):
                        data._detail_fetch(g)
                    _stat["warmed"] += 1; _stat["day_warm"] += 1; _done[g["key"]] = time.time()
                except Exception as e:
                    _stat["errors"] += 1; log.warning("warm %s: %s", g["key"], e)
                finally:
                    n = _tot["all"] - before          # 이 경기에 쓴 API 호출(같은 시간 다른 요청이 섞이면 조금 많게 잡힐 수 있음)
                    tnow = time.time()
                    _calls_warm.extend([tnow] * n); _tot["warm"] += n
                _stat["queue"] -= 1; _stat["last"] = datetime.now(data.SEOUL).strftime("%H:%M:%S")
                _save()
                time.sleep(GAP)
        except Exception as e:
            log.warning("warmer loop: %s", e)
        _save()
        time.sleep(max(5, LOOP - (time.time() - t0)))


_lockf = [None]


def start(order):
    urllib.request.urlopen = _counting_urlopen
    if os.environ.get("WARMER", "1") == "0":
        return False
    try:
        f = open(os.path.join(data.CACHE, "warmer.lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False                       # 다른 워커가 이미 돌리는 중
    _lockf[0] = f
    threading.Thread(target=_loop, args=(order,), daemon=True, name="warmer").start()
    log.info("warmer started pid=%s", os.getpid())
    return True


def status():
    try:
        with open(STATUS) as f:
            return json.load(f)
    except Exception:
        return None

"""API-Sports 분당 한도 보호 (계정 전체 1200회/분, x-ratelimit-limit 기준. 모든 종목 호스트가 같은 한도를 나눠 씀).

import 만 하면 urllib.request.urlopen 을 감싸서 *.api-sports.io (media 제외) 요청에만 적용:
- 프로세스별 토큰 버킷(API_RPM, 기본 300회/분, 버스트 8). 서비스 3개(score_bot/score_search/web) 합 900 < 1200.
- 진행 중 경기 조회(date=/live=/id=)는 우선. 그 밖(순위, 팀 경기, 맞대결 등)은 토큰 3개를 남겨 두고만 씀.
- 같은 URL 은 짧게 파일 캐시(/tmp/apisports_cache): 같은 컨테이너의 score_bot 과 score_search 가 결과를 공유.
  경기 목록 8초, 그 밖 120초. errors 가 있는 응답은 캐시하지 않음.
- 429 또는 errors.rateLimit: 짧게 쉬고(2,4,8초, Retry-After 우선) 그 요청만 최대 3번 다시. 프로세스 전체도 잠시 멈춤.
- x-ratelimit-remaining 이 120 아래면 다음 분까지 저우선 요청을 늦춤.
"""
import os, io, json, time, random, hashlib, threading, urllib.request, urllib.error, urllib.parse
from email.message import Message

RPM = float(os.environ.get("API_RPM", "300"))
BURST = float(os.environ.get("API_BURST", "8"))
RESERVE = 3.0
CACHE_DIR = os.environ.get("API_CACHE_DIR", "/tmp/apisports_cache")
TTL_HOT, TTL_COLD = 8, 120

_orig = urllib.request.urlopen
_lock = threading.Lock()
_tokens = BURST
_last = time.monotonic()
_pause_until = 0.0
_low_until = 0.0
stats = {"calls": 0, "cache": 0, "r429": 0}


def _is_api(url):
    h = urllib.parse.urlsplit(url).hostname or ""
    return h.endswith(".api-sports.io") and not h.startswith("media")


def _hot(url):
    q = urllib.parse.urlsplit(url).query
    return any(p in q for p in ("date=", "live=", "id=", "ids=")) or url.rstrip("/").endswith("/status")


def _take(hot):
    global _tokens, _last
    while True:
        with _lock:
            now = time.monotonic()
            _tokens = min(BURST, _tokens + (now - _last) * RPM / 60.0)
            _last = now
            need = 1.0 if hot else 1.0 + RESERVE
            wait = max(0.0, _pause_until - now)
            if not hot:
                wait = max(wait, _low_until - now)
            if wait <= 0 and _tokens >= need:
                _tokens -= 1.0
                return
            if wait <= 0:
                wait = (need - _tokens) * 60.0 / RPM
        time.sleep(min(wait, 5.0) + random.uniform(0, 0.05))


class _Resp(io.BytesIO):
    def __init__(self, body, url, status=200):
        super().__init__(body)
        self.status = self.code = status
        self.url = url
        self.headers = Message()
    def getcode(self): return self.status
    def geturl(self): return self.url
    def info(self): return self.headers


def _cpath(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")


def _cache_get(url, ttl):
    p = _cpath(url)
    try:
        if time.time() - os.path.getmtime(p) < ttl:
            with open(p, "rb") as f:
                return f.read()
    except OSError:
        pass
    return None


def _cache_put(url, body):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        p = _cpath(url)
        tmp = f"{p}.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, p)
    except OSError:
        pass


def _ratelimited_body(body):
    try:
        e = json.loads(body.decode()).get("errors")
    except Exception:
        return False
    return isinstance(e, dict) and ("rateLimit" in e or "requests" in str(e).lower() and "minute" in str(e).lower())


def _has_errors(body):
    try:
        e = json.loads(body.decode()).get("errors")
    except Exception:
        return True
    return bool(e)


def _backoff(sec):
    global _pause_until
    with _lock:
        _pause_until = max(_pause_until, time.monotonic() + sec)
    stats["r429"] += 1
    time.sleep(sec + random.uniform(0, 0.5))


def urlopen(url, data=None, timeout=None, *a, **kw):
    global _low_until
    u = url.full_url if isinstance(url, urllib.request.Request) else str(url)
    method = url.get_method() if isinstance(url, urllib.request.Request) else ("POST" if data else "GET")
    if not _is_api(u) or method != "GET":
        return _orig(url, data, timeout, *a, **kw) if timeout is not None else _orig(url, data, *a, **kw)
    hot = _hot(u)
    ttl = TTL_HOT if hot else TTL_COLD
    body = _cache_get(u, ttl)
    if body is not None:
        stats["cache"] += 1
        return _Resp(body, u)
    for attempt in range(4):
        _take(hot)
        stats["calls"] += 1
        try:
            with (_orig(url, data, timeout, *a, **kw) if timeout is not None else _orig(url, data, *a, **kw)) as r:
                body = r.read()
                rem = r.headers.get("x-ratelimit-remaining")
                status = getattr(r, "status", 200)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                ra = e.headers.get("Retry-After") if e.headers else None
                _backoff(float(ra) if ra and ra.isdigit() else 2 ** (attempt + 1))
                continue
            raise
        try:
            if rem is not None and int(rem) < 120:
                with _lock:
                    _low_until = max(_low_until, time.monotonic() + 60 - time.time() % 60)
        except ValueError:
            pass
        if _ratelimited_body(body) and attempt < 3:
            _backoff(2 ** (attempt + 1))
            continue
        if not _has_errors(body):
            _cache_put(u, body)
        return _Resp(body, u, status)
    return _Resp(body, u, status)


if getattr(urllib.request.urlopen, "__module__", "") != __name__:
    urllib.request.urlopen = urlopen

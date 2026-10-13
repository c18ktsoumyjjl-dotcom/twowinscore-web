"""팀 로고 프록시: api-sports 원본 PNG(100KB 안팎)를 96px WebP(2~5KB)로 줄여 디스크에 캐시하고 오래 캐시되게 보내요."""
import os, io, re, threading, logging, urllib.request
from flask import Blueprint, Response, abort, redirect
import members as M

log = logging.getLogger("logos")
bp = Blueprint("logos", __name__)
DIR = os.path.join(M.DATA_DIR, "logos")
SPORTS = {"football", "baseball", "basketball", "hockey", "volley", "handball", "rugby", "american-football"}
RX = re.compile(r"^https://media\.api-sports\.io/([a-z-]+)/teams/(\d+)\.png$")
_mem, _lk, _fail = {}, threading.Lock(), {}


def url(u):
    """원본 로고 주소 → 우리 주소. 모르는 형식은 그대로."""
    m = RX.match(u or "")
    if m and m.group(1) in SPORTS:
        return f"/lg/{m.group(1)}/{m.group(2)}.webp"
    return u


def _make(sport, tid):
    raw = urllib.request.urlopen(urllib.request.Request(f"https://media.api-sports.io/{sport}/teams/{tid}.png", headers={"User-Agent": "Mozilla/5.0"}), timeout=8).read()
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    im.thumbnail((96, 96), Image.LANCZOS)
    out = io.BytesIO(); im.save(out, "WEBP", quality=82, method=6)
    return out.getvalue()


_mk_sem = __import__("threading").BoundedSemaphore(4)


@bp.route("/lg/<sport>/<int:tid>.webp")
def logo(sport, tid):
    if sport not in SPORTS or tid > 10**8:
        abort(404)
    k = f"{sport}_{tid}"
    with _lk:
        b = _mem.get(k)
    if b is None:
        p = os.path.join(DIR, k + ".webp")
        if os.path.exists(p):
            b = open(p, "rb").read()
        else:
            import time
            if time.time() - _fail.get(k, 0) < 600:
                return redirect(f"https://media.api-sports.io/{sport}/teams/{tid}.png")
            if not _mk_sem.acquire(timeout=4):   # 동시에 만드는 건 4개까지, 나머지는 잠깐 기다려요(100KB 원본으로 넘기지 않게)
                return redirect(f"https://media.api-sports.io/{sport}/teams/{tid}.png")
            try:
                b = _make(sport, tid)
                os.makedirs(DIR, exist_ok=True)
                tmp = p + ".tmp"; open(tmp, "wb").write(b); os.replace(tmp, p)
            except Exception as e:
                log.warning("logo %s: %s", k, e); _fail[k] = time.time()
                return redirect(f"https://media.api-sports.io/{sport}/teams/{tid}.png")
            finally:
                _mk_sem.release()
        with _lk:
            if len(_mem) > 3000:
                _mem.clear()
            _mem[k] = b
    return Response(b, mimetype="image/webp", headers={"Cache-Control": "public, max-age=2592000, immutable"})


_wq, _wset = [], set()


def _wloop():
    import time
    while True:
        with _lk:
            k = _wq.pop(0) if _wq else None
            if k is None:
                _wset.discard("_t"); return
        sport, tid = k.split("_", 1)
        p = os.path.join(DIR, k + ".webp")
        if os.path.exists(p) or time.time() - _fail.get(k, 0) < 600:
            continue
        try:
            b = _make(sport, int(tid)); os.makedirs(DIR, exist_ok=True)
            tmp = p + ".tmp"; open(tmp, "wb").write(b); os.replace(tmp, p)
        except Exception as e:
            log.warning("warm %s: %s", k, e); _fail[k] = time.time()


def warm(urls):
    """첫 화면 로고를 서버에서 미리 WebP로 만들어 둬요. 안 만든 로고는 100KB 원본으로 넘어가 늦게 떠서요."""
    add = []
    for u in urls:
        m = re.match(r"^/lg/([a-z-]+)/(\d+)\.webp$", u or "")
        if m and not os.path.exists(os.path.join(DIR, f"{m.group(1)}_{m.group(2)}.webp")):
            add.append(f"{m.group(1)}_{m.group(2)}")
    if not add:
        return
    with _lk:
        for k in add:
            if k not in _wset:
                _wset.add(k); _wq.append(k)
        if "_t" in _wset:
            return
        _wset.add("_t")
    threading.Thread(target=_wloop, daemon=True).start()


_inl = {}


def inline(u, px=60):
    """첫 화면용: 디스크에 있는 로고를 표시 크기×2(60px) 작은 WebP data URI로. 없으면 None."""
    m = re.match(r"^/lg/([a-z-]+)/(\d+)\.webp$", u or "")
    if not m:
        return None
    k = f"{m.group(1)}_{m.group(2)}"
    with _lk:
        if k in _inl:
            return _inl[k]
    p = os.path.join(DIR, k + ".webp")
    if not os.path.exists(p):
        return None
    try:
        import base64
        from PIL import Image
        im = Image.open(p).convert("RGBA"); im.thumbnail((px, px), Image.LANCZOS)
        out = io.BytesIO(); im.save(out, "WEBP", quality=80, method=6)
        v = "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()
    except Exception as e:
        log.warning("inline %s: %s", k, e); return None
    with _lk:
        if len(_inl) > 4000:
            _inl.clear()
        _inl[k] = v
    return v


def start_prefetch(get_urls, every=600):
    """시작할 때와 10분마다 오늘·내일 모든 경기 로고를 미리 WebP로 디스크에 만들어 둬요(재시작해도 남음)."""
    import time
    def loop():
        time.sleep(5)
        while True:
            try:
                urls = [url(u) for u in get_urls()]
                miss = [u for u in dict.fromkeys(urls) if u and u.startswith("/lg/")]
                warm(miss)
                for u in miss[:400]:
                    inline(u)
                log.info("logo prefetch: %d urls", len(miss))
            except Exception as e:
                log.warning("logo prefetch: %s", e)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name="logo-prefetch").start()

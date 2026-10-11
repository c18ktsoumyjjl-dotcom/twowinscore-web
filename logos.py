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
            try:
                b = _make(sport, tid)
                os.makedirs(DIR, exist_ok=True)
                tmp = p + ".tmp"; open(tmp, "wb").write(b); os.replace(tmp, p)
            except Exception as e:
                log.warning("logo %s: %s", k, e); _fail[k] = time.time()
                return redirect(f"https://media.api-sports.io/{sport}/teams/{tid}.png")
        with _lk:
            if len(_mem) > 3000:
                _mem.clear()
            _mem[k] = b
    return Response(b, mimetype="image/webp", headers={"Cache-Control": "public, max-age=2592000, immutable"})

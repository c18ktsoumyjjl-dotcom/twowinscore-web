"""관리자 비밀 주소.
- 실제 주소는 저장소에 평문으로 두지 않아요. 환경변수 ADMIN_PATH 가 있으면 그것을 쓰고,
  없으면 아래 PBKDF2 해시(솔트+2만 번)와 맞는 주소만 관리자 화면으로 통과시켜요.
- 내부 라우트는 그대로 /admin/... 이고, 비밀 주소 → /admin 으로 바꿔서 전달해요.
- /admin 으로 직접 들어오면 일반 404 와 똑같이 응답해요(리다이렉트 없음).
- 관리자 응답의 링크·리다이렉트(Location)는 다시 비밀 주소로 바꿔서 내보내요."""
import os, re, hmac, hashlib, threading

SALT = bytes.fromhex("8a2343989207616a68eec41ee1c02416")
HASH = bytes.fromhex("f84407fd3abdb2f60b4d6a127fb0977c3b28775adb7d3c145da82abe9b78313c")
ENV = os.environ.get("ADMIN_PATH", "").strip().strip("/")
_ok, _bad, _lk = set(), {}, threading.Lock()
SEG = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


def _match(seg):
    if ENV:
        return hmac.compare_digest(seg, ENV)
    if not SEG.match(seg):
        return False
    with _lk:
        if seg in _ok:
            return True
        if seg in _bad:
            return False
    ok = hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", seg.encode(), SALT, 20000), HASH)
    with _lk:
        if ok:
            _ok.add(seg)
        else:
            if len(_bad) > 5000:
                _bad.clear()
            _bad[seg] = 1
    return ok


class Middleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, env, start):
        p = env.get("PATH_INFO", "") or "/"
        seg, _, rest = p[1:].partition("/")
        if p == "/admin" or p.startswith("/admin/"):
            env["tw.adm_direct"] = True             # → 404 (before_request)
        elif seg and seg not in ("static", "api", "media", "game", "news", "shop", "me", "login", "signup", "standings") and _match(seg):
            env["tw.adm_prefix"] = "/" + seg
            env["PATH_INFO"] = "/admin" + ("/" + rest if rest else "")
        return self.app(env, start)


_LINK = re.compile(r"""(["'(=\s])/admin(?=[/"'?#)\s]|$)""")


def install(app):
    from flask import request, abort
    app.wsgi_app = Middleware(app.wsgi_app)

    @app.before_request
    def _adm_gate():
        if request.environ.get("tw.adm_direct"):
            abort(404)

    @app.after_request
    def _adm_out(resp):
        pre = request.environ.get("tw.adm_prefix")
        if not pre:
            return resp
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        loc = resp.headers.get("Location")
        if loc and (loc == "/admin" or loc.startswith(("/admin/", "/admin?"))):
            resp.headers["Location"] = pre + loc[6:]
        if resp.mimetype in ("text/html", "application/json", "text/csv") and not resp.direct_passthrough:
            try:
                b = resp.get_data(as_text=True)
                if resp.mimetype == "text/html" and "<head>" in b and 'name="robots"' not in b:
                    b = b.replace("<head>", '<head><meta name="robots" content="noindex,nofollow">', 1)
                resp.set_data(_LINK.sub(lambda m: m.group(1) + pre, b))
            except Exception:
                pass
        return resp

"""관리자 확장: 회원 메모 · 방문자 통계 · 봇 상태(하트비트) · 사이트 설정(공지 배너 · 메인 이미지).
새 메뉴를 넣으려면 MENU 에 (키, 이름, 경로) 를 추가하고 라우트를 만들면 된다."""
import os, io, re, json, time, hmac, hashlib, threading, logging
from datetime import datetime, timedelta
from flask import current_app, Blueprint, render_template, request, redirect, abort, flash, session, Response, jsonify
import members as M
from members import q, admin_required, alog, KST, PG

log = logging.getLogger("admin_ext")
bp = Blueprint("admin_ext", __name__)

MENU = [("members", "회원", "/admin"), ("stats", "통계", "/admin/stats"), ("bots", "봇 상태", "/admin/bots"),
        ("settings", "설정", "/admin/settings"), ("log", "접근 기록", "/admin/log"), ("otp", "OTP 재설정", "/admin/otp")]

BOTS = [("score", "@kr_twowin_bot", "채널 알림 · 그룹방 · 스코어 검색"),
        ("cscenter", "@twowinscore_cs_bot", "투윈스코어 고객센터"),
        ("cs", "@member_inquiry_cs_bot", "회원 문의 CS")]
HB_STALE = 180  # 초

_SCHEMA = """CREATE TABLE IF NOT EXISTS member_memo(id {pk}, member_id BIGINT NOT NULL, body TEXT NOT NULL, admin TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS member_memo_mid ON member_memo(member_id);
CREATE TABLE IF NOT EXISTS visits(day TEXT NOT NULL, h TEXT NOT NULL, PRIMARY KEY(day, h));
CREATE TABLE IF NOT EXISTS site_kv(k TEXT PRIMARY KEY, v TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS site_media(name TEXT PRIMARY KEY, mime TEXT NOT NULL, data {blob} NOT NULL, etag TEXT NOT NULL, updated_at TEXT)"""
_ok = [False]


def init_db():
    if not M.enabled():
        return
    try:
        pk = "BIGSERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for s in _SCHEMA.format(pk=pk, blob="BYTEA" if PG else "BLOB").split(";"):
            q(s, fetch=False)
        _ok[0] = True
    except Exception:
        log.exception("admin_ext init failed")


@bp.app_context_processor
def _ctx():
    return {"adm_menu": MENU, "site_banner": banner() if _ok[0] else None, "hero_v": hero_ver() if _ok[0] else None}


# ---------- key/value 설정 (프로세스 캐시) ----------
_kv, _kvl = {}, threading.Lock()


def kv_get(k, default=None):
    with _kvl:
        if k in _kv and time.time() - _kv[k][0] < 60:
            return _kv[k][1]
    try:
        r = q("SELECT v FROM site_kv WHERE k=?", (k,), one=True)
        v = json.loads(r[0]) if r else default
    except Exception:
        v = default
    with _kvl:
        _kv[k] = (time.time(), v)
    return v


def kv_set(k, v):
    s = json.dumps(v, ensure_ascii=False)
    q("INSERT INTO site_kv(k,v,updated_at) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
      (k, s, M.now_s()), fetch=False)
    with _kvl:
        _kv[k] = (time.time(), v)


# ---------- 방문자 ----------
BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|curl|wget|python|httpx|go-http|java/|headless|lighthouse|monitor|uptime|render", re.I)
_seen, _seen_day = set(), [""]


@bp.before_app_request
def _count_visit():
    if not _ok[0] or request.method != "GET":
        return
    p = request.path
    if p.startswith(("/static", "/api", "/admin", "/media", "/favicon", "/manifest", "/sw", "/robots", "/sitemap")) or "." in p.rsplit("/", 1)[-1]:
        return
    ua = request.headers.get("User-Agent", "")
    if not ua or BOT_RE.search(ua) or session.get("adm_id"):
        return
    day = datetime.now(KST).strftime("%Y-%m-%d")
    h = hmac.new(current_app.secret_key.encode(), f"{day}|{M.ip()}|{ua}".encode(), hashlib.sha256).hexdigest()[:32]
    if _seen_day[0] != day:
        _seen.clear(); _seen_day[0] = day
    if h in _seen:
        return
    _seen.add(h)
    try:
        q("INSERT INTO visits(day,h) VALUES(?,?) ON CONFLICT DO NOTHING", (day, h), fetch=False)
    except Exception:
        log.exception("visit insert")


def visit_stats():
    today = datetime.now(KST).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    rows = dict(q("SELECT day, COUNT(*) FROM visits WHERE day>=? GROUP BY day", (days[0],)))
    series = [(d, rows.get(d, 0)) for d in days]
    return {"today": series[-1][1], "yday": series[-2][1], "d7": sum(c for _, c in series[-7:]),
            "d30": sum(c for _, c in series), "series": series, "max": max([c for _, c in series] + [1])}


# ---------- 회원 메모 ----------
@bp.route("/admin/member/<int:mid>")
@admin_required
def member_page(mid):
    r = q("SELECT id,login_id,nick,tg,status,created_at,last_login FROM members WHERE id=?", (mid,), one=True)
    if not r:
        abort(404)
    m = {"id": r[0], "login_id": r[1], "nick": r[2], "tg": r[3], "status": r[4], "created": r[5][:16], "last": (r[6] or "")[:16]}
    import levels
    m["lv"] = levels.info(mid)
    memos = q("SELECT id, body, admin, created_at FROM member_memo WHERE member_id=? ORDER BY id DESC", (mid,))
    return render_template("admin.html", mode="member", sec="members", m=m, memos=memos)


@bp.post("/admin/member/<int:mid>/memo")
@admin_required
def memo_add(mid):
    body = (request.form.get("body") or "").strip()[:2000]
    if not q("SELECT id FROM members WHERE id=?", (mid,), one=True):
        abort(404)
    if body:
        from flask import g
        q("INSERT INTO member_memo(member_id,body,admin,created_at) VALUES(?,?,?,?)", (mid, body, g.admin["username"], M.now_s()), fetch=False)
        alog("memo_add", mid)
    return redirect(f"/admin/member/{mid}")


@bp.post("/admin/memo/<int:nid>/delete")
@admin_required
def memo_del(nid):
    r = q("SELECT member_id FROM member_memo WHERE id=?", (nid,), one=True)
    if not r:
        abort(404)
    q("DELETE FROM member_memo WHERE id=?", (nid,), fetch=False)
    alog("memo_delete", f"{r[0]}#{nid}")
    return redirect(f"/admin/member/{r[0]}")


def memo_counts(ids):
    if not ids or not _ok[0]:
        return {}
    ph = ",".join("?" * len(ids))
    return dict(q(f"SELECT member_id, COUNT(*) FROM member_memo WHERE member_id IN ({ph}) GROUP BY member_id", list(ids)))


# ---------- 통계 ----------
@bp.route("/admin/stats")
@admin_required
def stats_page():
    return render_template("admin.html", mode="stats", sec="stats", v=visit_stats())


# ---------- 봇 상태 ----------
@bp.post("/api/bots/heartbeat")
def heartbeat():
    tok = os.environ.get("BRIDGE_TOKEN", "")
    given = request.headers.get("X-Bridge-Token", "")
    if len(tok) < 32 or not given or not hmac.compare_digest(tok, given) or not _ok[0]:
        abort(404)
    body = request.get_json(silent=True) or {}
    known = {b[0] for b in BOTS}
    for b in (body.get("bots") or [])[:10]:
        if not isinstance(b, dict) or b.get("key") not in known:
            continue
        kv_set("hb:" + b["key"], {"ts": time.time(), "alive": bool(b.get("alive")), "getme": b.get("getme"),
                                  "username": str(b.get("username") or "")[:40], "procs": {str(k)[:30]: bool(v) for k, v in (b.get("procs") or {}).items()},
                                  "err": str(b.get("err") or "")[:200]})
    return jsonify({"ok": True})


def bot_status():
    out, now = [], time.time()
    for key, handle, desc in BOTS:
        hb = kv_get("hb:" + key) or {}
        ts = hb.get("ts")
        fresh = bool(ts and now - ts < HB_STALE)
        ok = fresh and hb.get("alive") and hb.get("getme") is not False
        if not ts: why = "하트비트 기록 없음"
        elif not fresh: why = f"{int((now - ts) // 60)}분째 응답 없음"
        elif not hb.get("alive"): why = "프로세스 재시작 중"
        elif hb.get("getme") is False: why = "텔레그램 getMe 실패 " + hb.get("err", "")
        else: why = "정상"
        out.append({"key": key, "handle": handle, "desc": desc, "ok": bool(ok), "why": why, "procs": hb.get("procs") or {},
                    "last": datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d %H:%M:%S") if ts else "-",
                    "ago": (f"{int(now - ts)}초 전" if now - ts < 120 else f"{int((now - ts) // 60)}분 전") if ts else ""})
    return out


@bp.route("/admin/bots")
@admin_required
def bots_page():
    return render_template("admin.html", mode="bots", sec="bots", bots=bot_status())


# ---------- 설정: 공지 배너 / 메인 이미지 ----------
COLORS = {"orange": "#ff7a1a", "navy": "#14264f", "red": "#d63031", "green": "#1e9e5a", "blue": "#2d6cdf"}


def banner():
    b = kv_get("banner")
    return b if b and b.get("on") and b.get("text") else None


def hero_ver():
    return kv_get("hero_v")


MAX_IMG = 5 * 1024 * 1024


@bp.route("/admin/settings")
@admin_required
def settings_page():
    return render_template("admin.html", mode="settings", sec="settings", b=kv_get("banner") or {}, colors=COLORS, hv=hero_ver())


@bp.post("/admin/settings/banner")
@admin_required
def banner_save():
    f = request.form
    text = re.sub(r"\s+", " ", f.get("text") or "").strip()[:200]
    link = (f.get("link") or "").strip()[:300]
    if link and not re.match(r"^(https?://|/)[^\s<>\"']*$", link):
        flash("링크는 https:// 또는 / 로 시작해야 해요."); return redirect("/admin/settings")
    color = f.get("color") if f.get("color") in COLORS else "orange"
    on = f.get("on") == "1"
    if on and not text:
        flash("공지 문구를 넣어 주세요."); return redirect("/admin/settings")
    kv_set("banner", {"text": text, "link": link, "color": color, "on": on})
    alog("banner_" + ("on" if on else "off"), text[:40])
    flash("공지 배너를 저장했어요.")
    return redirect("/admin/settings")


@bp.post("/admin/settings/hero")
@admin_required
def hero_upload():
    fs = request.files.get("img")
    if not fs or not fs.filename:
        flash("이미지 파일을 골라 주세요."); return redirect("/admin/settings")
    raw = fs.read(MAX_IMG + 1)
    if len(raw) > MAX_IMG:
        flash("5MB 이하 이미지만 올릴 수 있어요."); return redirect("/admin/settings")
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError(im.format)
        im.load(); im = ImageOps.exif_transpose(im)
        if im.width * im.height > 40_000_000:
            raise ValueError("too big")
        if im.width > 2560:
            im = im.resize((2560, round(im.height * 2560 / im.width)), Image.LANCZOS)
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info) else im.convert("RGB")
        out = io.BytesIO(); im.save(out, "WEBP", quality=86, method=4)  # 새로 인코딩 → EXIF·메타데이터 제거
        data = out.getvalue()
    except Exception as e:
        log.warning("hero upload reject: %s", e)
        flash("JPG·PNG·WEBP 이미지만 올릴 수 있어요."); return redirect("/admin/settings")
    etag = hashlib.sha256(data).hexdigest()[:16]
    q("DELETE FROM site_media WHERE name='hero'", fetch=False)
    q("INSERT INTO site_media(name,mime,data,etag,updated_at) VALUES(?,?,?,?,?)", ("hero", "image/webp", data, etag, M.now_s()), fetch=False)
    kv_set("hero_v", etag)
    alog("hero_upload", f"{im.width}x{im.height} {len(data)//1024}KB")
    flash("메인 이미지를 바꿨어요.")
    return redirect("/admin/settings")


@bp.post("/admin/settings/hero/reset")
@admin_required
def hero_reset():
    q("DELETE FROM site_media WHERE name='hero'", fetch=False)
    kv_set("hero_v", None)
    alog("hero_reset")
    flash("메인 이미지를 기본으로 되돌렸어요.")
    return redirect("/admin/settings")


@bp.route("/media/hero.webp")
def hero_img():
    r = q("SELECT data, mime, etag FROM site_media WHERE name='hero'", one=True) if _ok[0] else None
    if not r:
        return redirect("/static/band_1x.webp")
    etag = r[2]
    if request.headers.get("If-None-Match", "").strip('"') == etag:
        return Response(status=304, headers={"ETag": f'"{etag}"'})
    cc = "public, max-age=31536000, immutable" if request.args.get("v") == etag else "public, max-age=300"
    return Response(bytes(r[0]), mimetype=r[1], headers={"ETag": f'"{etag}"', "Cache-Control": cc})

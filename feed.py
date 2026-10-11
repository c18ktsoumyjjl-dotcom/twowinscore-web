"""회원 피드(인스타그램형). 프로필(/u/<닉네임>)로 접근. 로그인 회원은 모두 열람(차단 관계 제외), 게시는 프로 등급부터.
저장소: R2_* 환경변수가 모두 있고 boto3 가 있으면 Cloudflare R2, 아니면 DB(Postgres bytea / SQLite BLOB)."""
import io, os, re, time, logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, abort, Response, flash
import members as M
from members import q, admin_required, KST
import social as S

log = logging.getLogger("feed")
bp = Blueprint("feed", __name__)
_ok = [False]
MAX_IMG, MAX_BYTES, MAX_CAP, DAY_LIMIT = 5, 10 * 1024 * 1024, 500, 10
FULL, THUMB, BLUR = 1440, 400, 40
# 업로드 권한(운영자 결정용): 최소 등급 index(0=아마추어=전원), VIP 전용 여부
POST_MIN_TIER = int(os.environ.get("FEED_MIN_TIER", "2") or 0)  # 2=프로
POST_VIP_ONLY = os.environ.get("FEED_VIP_ONLY") == "1"
LOCKED = "볼 수 없는 게시물이에요."

SCHEMA = """CREATE TABLE IF NOT EXISTS feed_post(id {pk}, member_id BIGINT NOT NULL, body TEXT NOT NULL DEFAULT '', n INTEGER NOT NULL DEFAULT 0, ts BIGINT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, del_reason TEXT, likes INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS feed_post_m ON feed_post(member_id,id);
CREATE TABLE IF NOT EXISTS feed_img(post_id BIGINT NOT NULL, idx INTEGER NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL, data {blob}, r2key TEXT, PRIMARY KEY(post_id,idx,kind));
CREATE TABLE IF NOT EXISTS feed_like(post_id BIGINT NOT NULL, member_id BIGINT NOT NULL, PRIMARY KEY(post_id,member_id));
CREATE TABLE IF NOT EXISTS feed_cmt(id {pk}, post_id BIGINT NOT NULL, member_id BIGINT NOT NULL, body TEXT NOT NULL, ts BIGINT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS feed_cmt_p ON feed_cmt(post_id,id);
CREATE TABLE IF NOT EXISTS feed_report(id {pk}, ts TEXT NOT NULL, reporter BIGINT NOT NULL, post_id BIGINT NOT NULL, reason TEXT, status TEXT NOT NULL DEFAULT 'open')"""


def init_db():
    if not M.enabled():
        return
    try:
        pk = "BIGSERIAL PRIMARY KEY" if M.PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for s in SCHEMA.format(pk=pk, blob="BYTEA" if M.PG else "BLOB").split(";"):
            q(s, fetch=False)
        for a in ("ALTER TABLE members ADD COLUMN feed_until TEXT", "ALTER TABLE feed_report ADD COLUMN cmt_id BIGINT", "ALTER TABLE feed_post ADD COLUMN ncmt INTEGER NOT NULL DEFAULT 0"):
            try:
                q(a, fetch=False)
            except Exception:
                pass
        _ok[0] = True
        log.info("feed storage: %s", storage_desc())
    except Exception:
        log.exception("feed init failed")


# ---------- 저장소 ----------
_R2 = [None]


def _r2():
    if _R2[0] is None:
        env = [os.environ.get(k, "").strip() for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")]
        try:
            import boto3
            _R2[0] = (boto3.client("s3", endpoint_url=f"https://{env[0]}.r2.cloudflarestorage.com", aws_access_key_id=env[1],
                                   aws_secret_access_key=env[2], region_name="auto"), env[3]) if all(env) else False
        except Exception:
            _R2[0] = False
    return _R2[0]


def storage_desc():
    return "Cloudflare R2" if _r2() else ("Postgres bytea" if M.PG else "SQLite BLOB")


def _put(pid, idx, kind, mime, data):
    r = _r2()
    if r:
        key = f"feed/{pid}/{idx}{kind}-{os.urandom(8).hex()}"
        r[0].put_object(Bucket=r[1], Key=key, Body=data, ContentType=mime)
        q("INSERT INTO feed_img(post_id,idx,kind,mime,data,r2key) VALUES(?,?,?,?,?,?)", (pid, idx, kind, mime, None, key), fetch=False)
    else:
        q("INSERT INTO feed_img(post_id,idx,kind,mime,data,r2key) VALUES(?,?,?,?,?,?)", (pid, idx, kind, mime, data, None), fetch=False)


def _get(pid, idx, kind):
    row = q("SELECT mime,data,r2key FROM feed_img WHERE post_id=? AND idx=? AND kind=?", (pid, idx, kind), one=True)
    if not row:
        return None
    if row[2]:
        r = _r2()
        if not r:
            return None
        return row[0], r[0].get_object(Bucket=r[1], Key=row[2])["Body"].read()
    return row[0], bytes(row[1])


def _drop_files(pid):
    r = _r2()
    if r:
        for (k,) in q("SELECT r2key FROM feed_img WHERE post_id=? AND r2key IS NOT NULL", (pid,)):
            try:
                r[0].delete_object(Bucket=r[1], Key=k)
            except Exception:
                log.exception("r2 delete")
    q("DELETE FROM feed_img WHERE post_id=?", (pid,), fetch=False)


# ---------- 이미지 처리 ----------
def _process(raw):
    """원본 bytes -> [(kind,mime,bytes)] 원본(≤1440 webp)·썸네일(400 정사각 webp)·흐림(40px jpeg). EXIF/GPS 제거."""
    from PIL import Image, ImageOps, ImageFilter
    Image.MAX_IMAGE_PIXELS = 50_000_000
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    im = Image.open(io.BytesIO(raw))
    if im.format not in ("JPEG", "PNG", "WEBP", "HEIF", "MPO"):
        raise ValueError("fmt")
    im = ImageOps.exif_transpose(im)
    im = im.convert("RGBA") if im.mode in ("P", "LA") else im
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[3]); im = bg
    im = im.convert("RGB")
    out = []
    f = im.copy(); f.thumbnail((FULL, FULL), Image.LANCZOS)
    b = io.BytesIO(); f.save(b, "WEBP", quality=84, method=4); out.append(("o", "image/webp", b.getvalue()))
    t = ImageOps.fit(im, (THUMB, THUMB), Image.LANCZOS)
    b = io.BytesIO(); t.save(b, "WEBP", quality=80, method=4); out.append(("t", "image/webp", b.getvalue()))
    s = ImageOps.fit(im, (BLUR, BLUR), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4))
    b = io.BytesIO(); s.save(b, "JPEG", quality=45); out.append(("b", "image/jpeg", b.getvalue()))
    return out


# ---------- 공통 ----------
def _can_see(me, owner):
    if not me:
        return False
    if me == owner:
        return True
    return not S._blocked(me, owner)  # 로그인 회원은 모두 열람 (차단 관계만 제외)


def _feed_banned(mid):
    r = q("SELECT feed_until FROM members WHERE id=?", (mid,), one=True)
    u = r and r[0]
    return u if u and (u == "perm" or u > M.now_s()) else None


def _ago(ts):
    d = int(time.time()) - int(ts)
    if d < 60:
        return "방금"
    if d < 3600:
        return f"{d // 60}분 전"
    if d < 86400:
        return f"{d // 3600}시간 전"
    if d < 86400 * 7:
        return f"{d // 86400}일 전"
    return datetime.fromtimestamp(ts, KST).strftime("%Y.%m.%d")


CMT_MAX = 300


def _counts(mid):
    np = q("SELECT COUNT(*) FROM feed_post WHERE member_id=? AND hidden=0", (mid,), one=True)[0]
    return int(np), S.follow_counts(mid)


def can_post(mid):
    """(가능 여부, 포인트, 프로까지 필요 점수, 진행률%)."""
    import levels, vip
    pts = levels.many([mid]).get(mid, 0)
    goal = levels.TIERS[min(POST_MIN_TIER, len(levels.TIERS) - 1)][1]
    ok = levels.tier_of(pts) >= POST_MIN_TIER and not (POST_VIP_ONLY and not vip.many([mid]).get(mid, {}).get("vip"))
    return ok, pts, max(0, goal - pts), min(100, int(pts * 100 / goal)) if goal else 100


def _cmts(pid, me, owner):
    rows = q("SELECT id,member_id,body,ts FROM feed_cmt WHERE post_id=? AND hidden=0 ORDER BY id DESC LIMIT 200", (pid,))[::-1]
    ids = list({r[1] for r in rows})
    cards = {}
    if ids:
        ph = ",".join("?" * len(ids))
        cards = {c["id"]: c for c in S._cards(q(f"SELECT id,nick,0 FROM members WHERE id IN ({ph})", ids))}
    return [{"id": r[0], "body": r[2], "ago": _ago(r[3]), "who": cards.get(r[1], {"id": r[1], "nick": "회원", "lv": None, "vip": 0}),
             "del": r[1] == me or owner == me, "mine": r[1] == me} for r in rows]


def _need():
    m = M.current()
    if not m or not _ok[0]:
        abort(401)
    S.touch(m["id"])
    return m


# ---------- 페이지 ----------
@bp.route("/u/<path:nick>")
def profile(nick):
    m = M.current()
    if not m:
        return redirect("/login?next=" + request.path)
    if not _ok[0]:
        abort(404)
    r = S._member(nick=nick[:12])
    if not r or (r[0] != m["id"] and S._blocked(m["id"], r[0])):
        return render_template("feed.html", missing=True, page="feed"), 404
    S.touch(m["id"])
    card = S._cards([(r[0], r[1], r[3])])[0]
    rel = "self" if r[0] == m["id"] else S._rel(m["id"], r[0])
    np, (ners, ning) = _counts(r[0])
    cp = can_post(m["id"]) if rel == "self" else (True, 0, 0, 100)
    import levels
    return render_template("feed.html", missing=False, page="feed", p=card, rel=rel, np=np, ners=ners, ning=ning, can=_can_see(m["id"], r[0]),
                           cp=cp, goal_name=levels.TIERS[POST_MIN_TIER][0], goal_pts=levels.TIERS[POST_MIN_TIER][1],
                           on=1 if (S.online(r[0]) and not r[3] and rel == "friend") else 0, maxcap=MAX_CAP, maxn=MAX_IMG,
                           ban=_feed_banned(m["id"]) if rel == "self" else None, pid=request.args.get("p", type=int) or 0)


@bp.get("/api/feed/<int:mid>/posts")
def posts(mid):
    m = _need()
    r = S._member(mid=mid)
    if not r or (mid != m["id"] and S._blocked(m["id"], mid)):
        return jsonify({"ok": False}), 404
    see = _can_see(m["id"], mid)
    before = request.args.get("before", type=int) or 2 ** 62
    rows = q("SELECT id,body,n,ts,likes FROM feed_post WHERE member_id=? AND hidden=0 AND id<? ORDER BY id DESC LIMIT 30", (mid, before))
    items = []
    for p in rows:
        it = {"id": p[0], "n": p[2]}
        if see:
            it.update(t=p[1][:80] if not p[2] else "", likes=p[4], img=f"/feed/img/{p[0]}/0/t" if p[2] else "")
        else:
            it.update(img=f"/feed/img/{p[0]}/0/b" if p[2] else "")
        items.append(it)
    return jsonify({"ok": True, "see": see, "items": items, "more": len(rows) == 30})


@bp.get("/api/feed/post/<int:pid>")
def post(pid):
    m = _need()
    p = q("SELECT id,member_id,body,n,ts,likes FROM feed_post WHERE id=? AND hidden=0", (pid,), one=True)
    if not p or not _can_see(m["id"], p[1]):
        return jsonify({"ok": False, "error": LOCKED}), 403
    liked = q("SELECT 1 FROM feed_like WHERE post_id=? AND member_id=?", (pid, m["id"]), one=True) is not None
    card = S._cards([(p[1], (q("SELECT nick FROM members WHERE id=?", (p[1],), one=True) or ("?",))[0], 0)])[0]
    return jsonify({"ok": True, "cmts": _cmts(pid, m["id"], p[1]), "p": {"id": p[0], "body": p[2], "imgs": [f"/feed/img/{p[0]}/{i}/o" for i in range(p[3])], "ago": _ago(p[4]),
                    "at": datetime.fromtimestamp(p[4], KST).strftime("%Y.%m.%d %H:%M"), "likes": p[5], "liked": liked, "mine": p[1] == m["id"], "who": card}})


@bp.get("/feed/img/<int:pid>/<int:idx>/<kind>")
def img(pid, idx, kind):
    m = M.current()
    if not m or kind not in ("o", "t", "b") or not _ok[0]:
        abort(404)
    p = q("SELECT member_id,hidden FROM feed_post WHERE id=?", (pid,), one=True)
    if not p or p[1]:
        abort(404)
    if kind != "b" and not _can_see(m["id"], p[0]):
        abort(404)
    if kind == "b" and m["id"] != p[0] and S._blocked(m["id"], p[0]):
        abort(404)
    g = _get(pid, idx, kind)
    if not g:
        abort(404)
    r = Response(g[1], mimetype=g[0])
    r.headers["Cache-Control"] = "private, max-age=86400"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@bp.post("/api/feed/post")
def create():
    m = _need(); S._csrf()
    if _feed_banned(m["id"]):
        return jsonify({"ok": False, "error": "피드 이용이 제한된 상태예요."}), 403
    if not can_post(m["id"])[0]:
        return jsonify({"ok": False, "error": "게시물은 프로 등급부터 올릴 수 있어요."}), 403
    n24 = q("SELECT COUNT(*) FROM feed_post WHERE member_id=? AND ts>?", (m["id"], int(time.time()) - 86400), one=True)[0]
    if n24 >= DAY_LIMIT:
        return jsonify({"ok": False, "error": f"게시물은 하루 {DAY_LIMIT}개까지 올릴 수 있어요."}), 429
    body = (request.form.get("body") or "").replace("\r", "").strip()
    if len(body) > MAX_CAP:
        return jsonify({"ok": False, "error": f"글은 {MAX_CAP}자까지 쓸 수 있어요."}), 400
    files = [f for f in request.files.getlist("img") if f and f.filename][:MAX_IMG + 1]
    if len(files) > MAX_IMG:
        return jsonify({"ok": False, "error": f"사진은 {MAX_IMG}장까지 올릴 수 있어요."}), 400
    if not files and not body:
        return jsonify({"ok": False, "error": "사진이나 글을 넣어 주세요."}), 400
    if body:
        bad, _ = S.check_dm(body)
        if bad:
            return jsonify({"ok": False, "error": bad}), 400
    done = []
    for f in files:
        raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return jsonify({"ok": False, "error": "사진은 한 장에 10MB까지 올릴 수 있어요."}), 400
        try:
            done.append(_process(raw))
        except Exception:
            return jsonify({"ok": False, "error": "지원하지 않는 사진 형식이에요. (JPG·PNG·WEBP)"}), 400
    ts = int(time.time())
    q("INSERT INTO feed_post(member_id,body,n,ts) VALUES(?,?,?,?)", (m["id"], body, len(done), ts), fetch=False)
    pid = q("SELECT MAX(id) FROM feed_post WHERE member_id=? AND ts=?", (m["id"], ts), one=True)[0]
    try:
        for i, parts in enumerate(done):
            for kind, mime, data in parts:
                _put(pid, i, kind, mime, data)
    except Exception:
        log.exception("feed store")
        _drop_files(pid); q("DELETE FROM feed_post WHERE id=?", (pid,), fetch=False)
        return jsonify({"ok": False, "error": "저장하지 못했어요. 잠시 뒤에 다시 시도해 주세요."}), 500
    return jsonify({"ok": True, "id": pid})


@bp.post("/api/feed/post/<int:pid>/<act>")
def act(pid, act):
    m = _need(); S._csrf()
    p = q("SELECT member_id,hidden FROM feed_post WHERE id=?", (pid,), one=True)
    if not p or p[1]:
        return jsonify({"ok": False, "error": "게시물이 없어요."}), 404
    if act == "del":
        if p[0] != m["id"]:
            abort(403)
        q("UPDATE feed_post SET hidden=2, del_reason='본인 삭제' WHERE id=?", (pid,), fetch=False)
        _drop_files(pid)
        return jsonify({"ok": True})
    if not _can_see(m["id"], p[0]):
        return jsonify({"ok": False, "error": LOCKED}), 403
    if act == "like":
        if q("SELECT 1 FROM feed_like WHERE post_id=? AND member_id=?", (pid, m["id"]), one=True):
            q("DELETE FROM feed_like WHERE post_id=? AND member_id=?", (pid, m["id"]), fetch=False); on = False
        else:
            q("INSERT INTO feed_like(post_id,member_id) VALUES(?,?)", (pid, m["id"]), fetch=False); on = True
        n = q("SELECT COUNT(*) FROM feed_like WHERE post_id=?", (pid,), one=True)[0]
        q("UPDATE feed_post SET likes=? WHERE id=?", (n, pid), fetch=False)
        return jsonify({"ok": True, "liked": on, "likes": n})
    if act == "cmt":
        if _feed_banned(m["id"]):
            return jsonify({"ok": False, "error": "피드 이용이 제한된 상태예요."}), 403
        body = re.sub(r"\s+", " ", ((request.get_json(silent=True) or {}).get("body") or "")).strip()
        if not body:
            return jsonify({"ok": False, "error": "댓글을 입력해 주세요."}), 400
        if len(body) > CMT_MAX:
            return jsonify({"ok": False, "error": f"댓글은 {CMT_MAX}자까지 쓸 수 있어요."}), 400
        if M.limited("fc:" + str(m["id"]), 10, 60) or M.limited("fcd:" + str(m["id"]), 200, 86400):
            return jsonify({"ok": False, "error": "댓글을 너무 빨리 쓰고 있어요. 잠시 후 다시 해 주세요."}), 429
        bad, _ = S.check_dm(body)
        if bad:
            return jsonify({"ok": False, "error": bad}), 400
        q("INSERT INTO feed_cmt(post_id,member_id,body,ts) VALUES(?,?,?,?)", (pid, m["id"], body, int(time.time())), fetch=False)
        q("UPDATE feed_post SET ncmt=(SELECT COUNT(*) FROM feed_cmt WHERE post_id=? AND hidden=0) WHERE id=?", (pid, pid), fetch=False)
        if p[0] != m["id"]:
            S.notify(p[0], "cmt", m["id"], f"{pid}|{body[:60]}")
        return jsonify({"ok": True, "cmts": _cmts(pid, m["id"], p[0])})
    if act == "report":
        if p[0] == m["id"]:
            return jsonify({"ok": False, "error": "내 게시물이에요."}), 400
        if q("SELECT 1 FROM feed_report WHERE post_id=? AND reporter=? AND status='open'", (pid, m["id"]), one=True):
            return jsonify({"ok": True})
        why = ((request.get_json(silent=True) or {}).get("reason") or "")[:100]
        q("INSERT INTO feed_report(ts,reporter,post_id,reason) VALUES(?,?,?,?)", (M.now_s(), m["id"], pid, why), fetch=False)
        return jsonify({"ok": True})
    abort(404)


@bp.post("/api/feed/cmt/<int:cid>/<act>")
def cmt_act(cid, act):
    m = _need(); S._csrf()
    c = q("SELECT c.post_id,c.member_id,p.member_id FROM feed_cmt c JOIN feed_post p ON p.id=c.post_id WHERE c.id=? AND c.hidden=0 AND p.hidden=0", (cid,), one=True)
    if not c or not _can_see(m["id"], c[2]):
        return jsonify({"ok": False, "error": "댓글이 없어요."}), 404
    if act == "del":
        if m["id"] not in (c[1], c[2]):
            abort(403)
        q("UPDATE feed_cmt SET hidden=? WHERE id=?", (2 if m["id"] == c[1] else 3, cid), fetch=False)
        q("UPDATE feed_post SET ncmt=(SELECT COUNT(*) FROM feed_cmt WHERE post_id=? AND hidden=0) WHERE id=?", (c[0], c[0]), fetch=False)
        return jsonify({"ok": True, "cmts": _cmts(c[0], m["id"], c[2])})
    if act == "report":
        if c[1] == m["id"]:
            return jsonify({"ok": False, "error": "내 댓글이에요."}), 400
        if not q("SELECT 1 FROM feed_report WHERE cmt_id=? AND reporter=? AND status='open'", (cid, m["id"]), one=True):
            why = ((request.get_json(silent=True) or {}).get("reason") or "")[:100]
            q("INSERT INTO feed_report(ts,reporter,post_id,reason,cmt_id) VALUES(?,?,?,?,?)", (M.now_s(), m["id"], c[0], why, cid), fetch=False)
        return jsonify({"ok": True})
    abort(404)


# ---------- 관리자 ----------
@bp.route("/admin/feed")
@admin_required
def adm_list():
    tab = request.args.get("tab", "posts")
    s = request.args.get("q", "").strip()[:12]
    d = request.args.get("d", "").strip()[:10]
    w, args = ["p.hidden=0"], []
    if tab == "deleted":
        w = ["p.hidden<>0"]
    if s:
        w.append("m.nick_l LIKE ?"); args.append("%" + s.lower() + "%")
    if d:
        try:
            t0 = int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST).timestamp())
            w.append("p.ts>=? AND p.ts<?"); args += [t0, t0 + 86400]
        except ValueError:
            pass
    if tab == "reports":
        w.append("p.id IN (SELECT post_id FROM feed_report WHERE status='open')")
    rows = q("SELECT p.id,p.member_id,m.nick,p.body,p.n,p.ts,p.likes,p.hidden,p.del_reason,(SELECT COUNT(*) FROM feed_report r WHERE r.post_id=p.id AND r.status='open') "
             "FROM feed_post p JOIN members m ON m.id=p.member_id WHERE " + " AND ".join(w) + " ORDER BY p.id DESC LIMIT 200", args)
    posts = [{"id": r[0], "mid": r[1], "nick": r[2], "body": r[3][:60], "n": r[4], "ts": datetime.fromtimestamp(r[5], KST).strftime("%m-%d %H:%M"),
              "likes": r[6], "hid": r[7], "why": r[8], "rep": int(r[9] or 0)} for r in rows]
    nrep = q("SELECT COUNT(DISTINCT post_id) FROM feed_report WHERE status='open'", one=True)[0]
    S.alog("feed list " + tab + (" q=" + s if s else ""))
    return render_template("admin.html", mode="feed", sec="feed", tab=tab, s=s, d=d, posts=posts, nrep=nrep, store=storage_desc())


@bp.route("/admin/feed/<int:pid>")
@admin_required
def adm_view(pid):
    r = q("SELECT p.id,p.member_id,m.nick,p.body,p.n,p.ts,p.likes,p.hidden,p.del_reason,m.feed_until,m.status FROM feed_post p JOIN members m ON m.id=p.member_id WHERE p.id=?", (pid,), one=True)
    if not r:
        abort(404)
    reps = q("SELECT id,ts,reporter,reason,status,cmt_id FROM feed_report WHERE post_id=? ORDER BY id DESC", (pid,))
    cm = q("SELECT id,member_id,body,ts,hidden FROM feed_cmt WHERE post_id=? ORDER BY id", (pid,))
    nk = S._nicks([x[2] for x in reps] + [x[1] for x in cm])
    rc = {x[5] for x in reps if x[5] and x[4] == "open"}
    p = {"id": r[0], "mid": r[1], "nick": r[2], "body": r[3], "n": r[4], "at": datetime.fromtimestamp(r[5], KST).strftime("%Y-%m-%d %H:%M"), "likes": r[6],
         "hid": r[7], "why": r[8], "fu": r[9], "st": r[10], "np": _counts(r[1])[0],
         "reps": [{"id": x[0], "ts": x[1][5:16], "who": nk.get(x[2], ("?",))[0], "reason": (("[댓글] " if x[5] else "") + (x[3] or "-")), "st": x[4]} for x in reps],
         "cmts": [{"id": x[0], "mid": x[1], "who": nk.get(x[1], ("?",))[0], "body": x[2], "ts": datetime.fromtimestamp(x[3], KST).strftime("%m-%d %H:%M"), "hid": x[4], "rep": x[0] in rc} for x in cm]}
    S.alog("feed view", pid)
    return render_template("_feed_panel.html", p=p)


@bp.get("/admin/feed/img/<int:pid>/<int:idx>/<kind>")
@admin_required
def adm_img(pid, idx, kind):
    g = _get(pid, idx, kind if kind in ("o", "t") else "t")
    if not g:
        abort(404)
    r = Response(g[1], mimetype=g[0]); r.headers["Cache-Control"] = "private, no-store"
    return r


@bp.post("/admin/feed/act")
@admin_required
def adm_act():
    a = request.form.get("act", "")
    pid = request.form.get("pid", type=int)
    mid = request.form.get("mid", type=int)
    why = request.form.get("why", "").strip()[:100] or "-"
    msg = "적용했어요."
    if a == "del" and pid:
        q("UPDATE feed_post SET hidden=1, del_reason=? WHERE id=?", (why, pid), fetch=False)
        q("UPDATE feed_report SET status='done' WHERE post_id=?", (pid,), fetch=False)
        S.alog(f"feed post delete #{pid}: {why}", mid); msg = "게시물을 삭제했어요."
    elif a == "cdel":
        cid = request.form.get("cid", type=int)
        q("UPDATE feed_cmt SET hidden=1 WHERE id=?", (cid,), fetch=False)
        q("UPDATE feed_report SET status='done' WHERE cmt_id=?", (cid,), fetch=False)
        if pid:
            q("UPDATE feed_post SET ncmt=(SELECT COUNT(*) FROM feed_cmt WHERE post_id=? AND hidden=0) WHERE id=?", (pid, pid), fetch=False)
        S.alog(f"feed comment delete #{cid} (post #{pid}): {why}", mid); msg = "댓글을 삭제했어요."
    elif a == "report_done" and pid:
        q("UPDATE feed_report SET status='done' WHERE post_id=?", (pid,), fetch=False)
        S.alog(f"feed reports done #{pid}", mid); msg = "신고를 처리 완료로 표시했어요."
    elif a in ("fb1", "fb7", "fbp", "fb0") and mid:
        v = {"fb1": datetime.now(KST) + timedelta(days=1), "fb7": datetime.now(KST) + timedelta(days=7)}.get(a)
        val = v.strftime("%Y-%m-%d %H:%M:%S") if v else ("perm" if a == "fbp" else None)
        q("UPDATE members SET feed_until=? WHERE id=?", (val, mid), fetch=False)
        S.alog(f"feed ban {a}: {why}", mid); msg = "피드 제한을 " + ("해제했어요." if a == "fb0" else "적용했어요.")
    else:
        return jsonify({"ok": False, "msg": "잘못된 요청이에요."}), 400
    if request.headers.get("X-Fetch") == "1":
        return jsonify({"ok": True, "msg": msg})
    flash(msg)
    return redirect("/admin/feed")

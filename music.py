"""음악관리 — 사이트 BGM 플레이리스트.
업로드한 곡은 DB(site_media, 'bgm:<id>')에 저장해요. Render 디스크는 배포 때마다 지워지므로 static/에 저장하면 사라져요.
기본 5곡(static/bgm/)은 처음 한 번 목록에 등록되고, 끄거나 지울 수 있어요."""
import os, re, io, time, shutil, hashlib, subprocess, tempfile, threading, logging
from flask import Blueprint, render_template, request, redirect, abort, flash, Response
import members as M
from members import q, alog, super_required, PG

log = logging.getLogger("music")
bp = Blueprint("music", __name__)
MAX = 8 * 1024 * 1024
_cache = [None, 0.0]  # 워커가 여러 개여도 30초 안에 반영
_lk = threading.Lock()


def init_db():
    pk = "BIGSERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    q(f"CREATE TABLE IF NOT EXISTS bgm_tracks(id {pk}, title TEXT NOT NULL, ord INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, src TEXT, size INTEGER DEFAULT 0, etag TEXT, created_at TEXT)", fetch=False)
    if not q("SELECT id FROM bgm_tracks LIMIT 1"):
        for n in range(1, 6):
            if os.path.exists(os.path.join(os.path.dirname(__file__), "static", "bgm", f"bgm{n}_v1.mp3")):
                q("INSERT INTO bgm_tracks(title,ord,enabled,src,created_at) VALUES(?,?,?,?,?)", (f"기본 트랙 {n}", n * 10, 1, f"/static/bgm/bgm{n}_v1.mp3", M.now_s()), fetch=False)


def _url(r):
    return r[4] if r[4] else f"/media/bgm/{r[0]}.mp3?v={r[6]}"


def rows():
    return q("SELECT id,title,ord,enabled,src,size,etag,created_at FROM bgm_tracks ORDER BY ord, id")


def playlist():
    with _lk:
        if _cache[0] is None or time.time() - _cache[1] > 30:
            try:
                _cache[1] = time.time()
                _cache[0] = [{"t": r[1], "u": _url(r)} for r in rows() if r[3]]
            except Exception as e:
                log.warning("playlist: %s", e); return []
        return _cache[0]


def _bust():
    with _lk:
        _cache[0] = None


@bp.app_context_processor
def _ctx():
    return {"bgm_list": playlist, "intro_on": intro_on}


def intro_on():
    """입장 효과음(휘슬+함성) — 기본 꺼짐. 관리자가 음악관리에서 켜고 끌 수 있어요."""
    try:
        from admin_ext import kv_get
        return kv_get("intro_on") == "1"
    except Exception:
        return False


def _is_mp3(b):
    if b[:3] == b"ID3":
        return True
    return len(b) > 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0


def _encode(data):
    """ffmpeg 있으면 모바일용 128kbps 스테레오 MP3로 다시 인코딩(메타데이터 제거). 실패하거나 더 크면 원본."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return data
    with tempfile.TemporaryDirectory() as d:
        i, o = os.path.join(d, "in.mp3"), os.path.join(d, "out.mp3")
        open(i, "wb").write(data)
        try:
            subprocess.run([ff, "-v", "error", "-y", "-i", i, "-map", "0:a:0", "-map_metadata", "-1", "-vn", "-ac", "2", "-ar", "44100", "-b:a", "128k", o], timeout=120, check=True)
            out = open(o, "rb").read()
            return out if 0 < len(out) < len(data) else data
        except Exception as e:
            log.warning("ffmpeg: %s", e); return data


@bp.route("/admin/music")
@M.admin_required
@super_required
def page():
    return render_template("admin.html", mode="music", sec="music", tracks=rows(), maxmb=MAX // 1048576)


@bp.post("/admin/music/upload")
@M.admin_required
@super_required
def upload():
    f = request.files.get("file")
    title = (request.form.get("title") or "").strip()[:60]
    if not f or not f.filename:
        flash("MP3 파일을 골라 주세요."); return redirect("/admin/music")
    if not f.filename.lower().endswith(".mp3"):
        flash("MP3 파일만 올릴 수 있어요."); return redirect("/admin/music")
    data = f.read(MAX + 1)
    if len(data) > MAX:
        flash(f"파일이 너무 커요 (최대 {MAX // 1048576}MB)."); return redirect("/admin/music")
    if not _is_mp3(data[:4]):
        flash("올바른 MP3 파일이 아니에요."); return redirect("/admin/music")
    data = _encode(data)
    if not title:
        title = re.sub(r"[^\w가-힣 \-\.\(\)]", "", os.path.splitext(f.filename)[0])[:60] or "새 트랙"
    etag = hashlib.sha256(data).hexdigest()[:16]
    mx = q("SELECT COALESCE(MAX(ord),0) FROM bgm_tracks", one=True)[0] or 0
    q("INSERT INTO bgm_tracks(title,ord,enabled,src,size,etag,created_at) VALUES(?,?,?,?,?,?,?)", (title, int(mx) + 10, 1, None, len(data), etag, M.now_s()), fetch=False)
    tid = q("SELECT MAX(id) FROM bgm_tracks WHERE etag=?", (etag,), one=True)[0]
    q("INSERT INTO site_media(name,mime,data,etag,updated_at) VALUES(?,?,?,?,?)", (f"bgm:{tid}", "audio/mpeg", data, etag, M.now_s()), fetch=False)
    _bust(); alog("bgm upload", f"#{tid} {title} {len(data)//1024}KB")
    flash(f"'{title}' 트랙을 추가했어요 ({len(data)/1048576:.1f}MB)."); return redirect("/admin/music")


@bp.post("/admin/music/intro")
@M.admin_required
@super_required
def intro_toggle():
    from admin_ext import kv_set
    on = request.form.get("on") == "1"
    kv_set("intro_on", "1" if on else None)
    alog("intro " + ("on" if on else "off"))
    flash("입장 효과음을 켰어요." if on else "입장 효과음을 껐어요.")
    return redirect("/admin/music")


@bp.post("/admin/music/save")
@M.admin_required
@super_required
def save():
    n = 0
    for r in rows():
        t = (request.form.get(f"t{r[0]}") or "").strip()[:60]
        o = request.form.get(f"o{r[0]}", type=int)
        e = 1 if request.form.get(f"e{r[0]}") else 0
        if t and o is not None:
            q("UPDATE bgm_tracks SET title=?, ord=?, enabled=? WHERE id=?", (t, max(0, min(o, 100000)), e, r[0]), fetch=False); n += 1
    _bust(); alog("bgm save", str(n))
    if not playlist():
        flash("저장했어요. 켜진 트랙이 없어서 지금은 음악이 나오지 않아요.")
    else:
        flash("플레이리스트를 저장했어요.")
    return redirect("/admin/music")


@bp.post("/admin/music/<int:tid>/delete")
@M.admin_required
@super_required
def delete(tid):
    r = q("SELECT title FROM bgm_tracks WHERE id=?", (tid,), one=True)
    if not r:
        abort(404)
    q("DELETE FROM bgm_tracks WHERE id=?", (tid,), fetch=False)
    q("DELETE FROM site_media WHERE name=?", (f"bgm:{tid}",), fetch=False)
    _bust(); alog("bgm delete", f"#{tid} {r[0]}")
    flash(f"'{r[0]}' 트랙을 지웠어요."); return redirect("/admin/music")


@bp.route("/media/bgm/<int:tid>.mp3")
def media(tid):
    r = q("SELECT data, etag FROM site_media WHERE name=?", (f"bgm:{tid}",), one=True)
    if not r:
        abort(404)
    data = bytes(r[0]); n = len(data)
    h = {"Accept-Ranges": "bytes", "ETag": f'"{r[1]}"', "Cache-Control": "public, max-age=31536000, immutable"}
    if request.headers.get("If-None-Match") == f'"{r[1]}"':
        return Response(status=304, headers=h)
    m = re.match(r"bytes=(\d*)-(\d*)$", request.headers.get("Range", ""))
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            a = int(m.group(1)); b = int(m.group(2)) if m.group(2) else n - 1
        else:
            a = max(0, n - int(m.group(2))); b = n - 1
        b = min(b, n - 1)
        if a > b or a >= n:
            return Response(status=416, headers={"Content-Range": f"bytes */{n}"})
        h["Content-Range"] = f"bytes {a}-{b}/{n}"
        return Response(data[a:b + 1], 206, mimetype="audio/mpeg", headers=h)
    return Response(data, mimetype="audio/mpeg", headers=h)

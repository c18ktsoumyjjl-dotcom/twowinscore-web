"""접속 기록(access_log) + 관리자 '회원활동내역'. 페이지 방문만 기록(정적·API·관리자·봇 제외), 같은 IP+회원+경로는 10분에 1줄, 90일 지나면 삭제."""
import re, time, threading, logging
from datetime import datetime, timedelta
from flask import Blueprint, request, session, render_template, g
import members as M
from members import q, KST

log = logging.getLogger("activity")
bp = Blueprint("activity", __name__)
_ok = [False]
KEEP_DAYS = 90
DEDUP = 600
HOT = 20          # 최근 1시간 이 줄 수 이상이면 강조
PER = 30
MOB_RE = re.compile(r"Mobi|Android|iPhone|iPad|iPod", re.I)
_seen, _lk, _last_clean = {}, threading.Lock(), [""]


def init_db():
    if not M.enabled():
        return
    try:
        pk = "BIGSERIAL PRIMARY KEY" if M.PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        q(f"CREATE TABLE IF NOT EXISTS access_log(id {pk}, ts TEXT NOT NULL, ip TEXT NOT NULL, member_id BIGINT, nick TEXT, device TEXT, ua TEXT, path TEXT)", fetch=False)
        for s in ("CREATE INDEX IF NOT EXISTS access_log_ts ON access_log(ts)", "CREATE INDEX IF NOT EXISTS access_log_ip ON access_log(ip)",
                  "CREATE INDEX IF NOT EXISTS access_log_mid ON access_log(member_id)"):
            q(s, fetch=False)
        for a in ("ALTER TABLE members ADD COLUMN last_ip TEXT",):
            try:
                q(a, fetch=False)
            except Exception:
                pass
        _ok[0] = True
        clean()
    except Exception:
        log.exception("activity init failed")


def clean():
    day = datetime.now(KST).strftime("%Y-%m-%d")
    if _last_clean[0] == day:
        return
    _last_clean[0] = day
    cut = (datetime.now(KST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        q("DELETE FROM access_log WHERE ts<?", (cut,), fetch=False)
    except Exception:
        log.exception("access_log clean")


@bp.before_app_request
def _record():
    if not _ok[0] or request.method != "GET":
        return
    p = request.path
    if p.startswith(("/static", "/api", "/admin", "/media", "/favicon", "/manifest", "/sw", "/robots", "/sitemap")) or "." in p.rsplit("/", 1)[-1]:
        return
    ua = request.headers.get("User-Agent", "")
    import admin_ext
    if not ua or admin_ext.BOT_RE.search(ua) or session.get("adm_id"):
        return
    try:
        ip = M.ip()
        m = M.current()
        mid = m["id"] if m else None
        now = time.time()
        k = (ip, mid, p)
        with _lk:
            if now - _seen.get(k, 0) < DEDUP:
                return
            _seen[k] = now
            if len(_seen) > 50000:
                for kk in [kk for kk, t in _seen.items() if now - t > DEDUP]:
                    _seen.pop(kk, None)
        clean()
        q("INSERT INTO access_log(ts,ip,member_id,nick,device,ua,path) VALUES(?,?,?,?,?,?,?)",
          (M.now_s(), ip[:45], mid, m["nick"] if m else None, "mobile" if MOB_RE.search(ua) else "pc", ua[:120], p[:200]), fetch=False)
        if mid:
            q("UPDATE members SET last_ip=? WHERE id=? AND last_ip IS NULL", (ip[:45], mid), fetch=False)
    except Exception:
        log.exception("access_log insert")


def member_ips(mid, n=20):
    if not _ok[0]:
        return []
    return q("SELECT ip, COUNT(*), MAX(ts), MAX(device) FROM access_log WHERE member_id=? GROUP BY ip ORDER BY MAX(ts) DESC LIMIT " + str(int(n)), (mid,))


@bp.route("/admin/activity")
@M.admin_required
@M.super_required
def page():
    tab = "member" if request.args.get("tab") == "member" else "guest"
    s = (request.args.get("q") or "").strip()[:60]
    pg = max(1, request.args.get("p", 1, type=int))
    where = "member_id IS NOT NULL" if tab == "member" else "member_id IS NULL"
    args = []
    if s:
        like = "%" + s.replace("%", "").replace("_", "\\_") + "%"
        where += " AND (ip LIKE ? ESCAPE '\\' OR nick LIKE ? ESCAPE '\\')"
        args += [like, like]
    total = q(f"SELECT COUNT(*) FROM access_log WHERE {where}", args, one=True)[0]
    rows = q(f"SELECT ts, ip, member_id, nick, device, path, ua FROM access_log WHERE {where} ORDER BY ts DESC, id DESC LIMIT {PER} OFFSET {(pg - 1) * PER}", args)
    h1 = (datetime.now(KST) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    hot = dict(q("SELECT ip, COUNT(*) FROM access_log WHERE ts>=? GROUP BY ip HAVING COUNT(*)>=?", (h1, HOT)))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    import admin_ext
    try:
        vis = admin_ext.visit_stats()["today"]
    except Exception:
        vis = None
    stats = {"today": q("SELECT COUNT(*) FROM members WHERE created_at LIKE ?", (today + "%",), one=True)[0],
             "total": q("SELECT COUNT(*) FROM members", one=True)[0],
             "susp": q("SELECT COUNT(*) FROM members WHERE status='suspended'", one=True)[0], "vis": vis}
    h1c = dict(q("SELECT ip, COUNT(*) FROM access_log WHERE ts>=? GROUP BY ip", (h1,))) if rows else {}
    return render_template("admin.html", mode="activity", sec="activity", tab=tab, rows=rows, s=s, page=pg,
                           pages=max(1, (total + PER - 1) // PER), total=total, hot=hot, h1c=h1c, hot_n=HOT, st=stats)

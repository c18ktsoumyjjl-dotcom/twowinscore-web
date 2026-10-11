"""관리자: 대시보드 · 사이트통계 · 정산통계 · 캐시 내역 · VIP 회원."""
import csv, io, re, threading
from datetime import datetime, timedelta
from flask import Blueprint, request, render_template, Response
import members as M
from members import q, KST

bp = Blueprint("adminstats", __name__)
_cl = threading.Lock()


def _today():
    return datetime.now(KST).date()


# ---------- 채팅 메시지 하루 수 (site_kv 에 날짜별 누적) ----------
def chat_hit():
    try:
        import admin_ext
        k = "chatn:" + _today().isoformat()
        with _cl:
            admin_ext.kv_set(k, int(admin_ext.kv_get(k, 0) or 0) + 1)
    except Exception:
        pass


def _kvs(prefix, days):
    out = {}
    try:
        for k, v in q("SELECT k, v FROM site_kv WHERE k LIKE ?", (prefix + "%",)):
            out[k[len(prefix):]] = int(v)
    except Exception:
        pass
    return [(d, out.get(d, 0)) for d in days]


def _days(n):
    t = _today()
    return [(t - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _series(rows, days):
    d = {str(k): int(v) for k, v in rows}
    s = [(x, d.get(x, 0)) for x in days]
    return {"s": s, "max": max([c for _, c in s] + [1]), "sum": sum(c for _, c in s)}


@bp.route("/admin/stats")
@M.admin_required
def stats():
    import admin_ext
    days = _days(30)
    since = days[0]
    v = admin_ext.visit_stats()
    signup = _series(q("SELECT substr(created_at,1,10) d, COUNT(*) FROM members WHERE created_at>=? GROUP BY d", (since,)), days)
    chat = {"s": _kvs("chatn:", days)}
    chat["max"] = max([c for _, c in chat["s"]] + [1]); chat["sum"] = sum(c for _, c in chat["s"])
    mega = _series(q("SELECT substr(ts,1,10) d, COUNT(*) FROM mega_log WHERE reason LIKE '사용%' AND ts>=? GROUP BY d", (since,)), days)
    a30 = (_today() - timedelta(days=30)).isoformat()
    mem = {"total": q("SELECT COUNT(*) FROM members", one=True)[0],
           "active": q("SELECT COUNT(*) FROM members WHERE last_login>=?", (a30,), one=True)[0],
           "vip": q("SELECT COUNT(*) FROM members WHERE vip_until>?", (datetime.now(KST).strftime("%Y-%m-%d %H:%M"),), one=True)[0]}
    dev = dict(q("SELECT device, COUNT(*) FROM access_log WHERE ts>=? GROUP BY device", (since,)))
    mg = dict(q("SELECT CASE WHEN member_id IS NULL THEN 'g' ELSE 'm' END k, COUNT(*) FROM access_log WHERE ts>=? GROUP BY k", (since,)))
    top = q("SELECT path, COUNT(*) c FROM access_log WHERE ts>=? GROUP BY path ORDER BY c DESC LIMIT 10", (since,))
    hrs = dict((int(h), c) for h, c in q("SELECT substr(ts,12,2) h, COUNT(*) FROM access_log WHERE ts>=? GROUP BY h", (since,)) if h and h.isdigit())
    hours = [(h, hrs.get(h, 0)) for h in range(24)]
    return render_template("admin.html", mode="stats", sec="stats", v=v, signup=signup, chat=chat, mega=mega, mem=mem,
                           dev=dev, mg=mg, top=top, hours=hours, hmax=max([c for _, c in hours] + [1]))


# ---------- 정산통계 ----------
def _range():
    t = _today()
    try:
        f = datetime.strptime(request.args.get("from", ""), "%Y-%m-%d").date()
    except ValueError:
        f = t.replace(day=1)
    try:
        to = datetime.strptime(request.args.get("to", ""), "%Y-%m-%d").date()
    except ValueError:
        to = t
    if f > to:
        f, to = to, f
    return f.isoformat(), to.isoformat()


@bp.route("/admin/settle")
@M.admin_required
@M.super_required
def settle():
    f, to = _range()
    end = to + " 99"
    w, a = "ts>=? AND ts<=?", (f, end)
    def one(sql, args=()):
        r = q(sql, args, one=True); return int(r[0] or 0) if r else 0
    tot = {"paid": one(f"SELECT SUM(delta) FROM cash_log WHERE {w} AND kind='charge'", a),
           "grant": one(f"SELECT SUM(delta) FROM cash_log WHERE {w} AND kind='admin' AND delta>0", a),
           "deduct": -one(f"SELECT SUM(delta) FROM cash_log WHERE {w} AND kind='admin' AND delta<0", a),
           "spent": -one(f"SELECT SUM(delta) FROM cash_log WHERE {w} AND kind='buy'", a),
           "refund": one(f"SELECT SUM(delta) FROM cash_log WHERE {w} AND kind='refund'", a),
           "outstanding": one("SELECT SUM(cash) FROM members"),
           "holders": one("SELECT COUNT(*) FROM members WHERE cash>0")}
    items = q(f"SELECT reason, COUNT(*), -SUM(delta) FROM cash_log WHERE {w} AND kind='buy' GROUP BY reason ORDER BY 3 DESC", a)
    daily = q(f"""SELECT substr(ts,1,10) d, SUM(CASE WHEN kind='charge' THEN delta ELSE 0 END), SUM(CASE WHEN kind='admin' AND delta>0 THEN delta ELSE 0 END),
                 SUM(CASE WHEN kind='admin' AND delta<0 THEN -delta ELSE 0 END), SUM(CASE WHEN kind='buy' THEN -delta ELSE 0 END), COUNT(*)
                 FROM cash_log WHERE {w} GROUP BY d ORDER BY d DESC""", a)
    monthly = q("""SELECT substr(ts,1,7) m, SUM(CASE WHEN kind='charge' THEN delta ELSE 0 END), SUM(CASE WHEN kind='admin' AND delta>0 THEN delta ELSE 0 END),
                 SUM(CASE WHEN kind='admin' AND delta<0 THEN -delta ELSE 0 END), SUM(CASE WHEN kind='buy' THEN -delta ELSE 0 END), COUNT(*)
                 FROM cash_log GROUP BY m ORDER BY m DESC LIMIT 12""")
    topc = q(f"""SELECT c.member_id, m.nick, SUM(c.delta) s, COUNT(*) FROM cash_log c LEFT JOIN members m ON m.id=c.member_id
                WHERE c.ts>=? AND c.ts<=? AND c.delta>0 AND c.kind IN ('charge','admin') GROUP BY c.member_id, m.nick ORDER BY s DESC LIMIT 10""", a)
    if request.args.get("csv"):
        rows = q(f"""SELECT c.ts, c.member_id, m.nick, c.kind, c.delta, c.balance, c.reason, c.admin FROM cash_log c LEFT JOIN members m ON m.id=c.member_id
                    WHERE c.ts>=? AND c.ts<=? ORDER BY c.id""", a)
        buf = io.StringIO(); wr = csv.writer(buf)
        wr.writerow(["시각", "회원ID", "닉네임", "종류", "증감", "잔액", "내용", "관리자"])
        for r in rows:
            wr.writerow([("'" + str(x)) if isinstance(x, str) and x[:1] in "=+-@" else x for x in r])
        M.alog("settle csv %s~%s" % (f, to))
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=settle_{f}_{to}.csv"})
    return render_template("admin.html", mode="settle", sec="settle", f=f, to=to, tot=tot, items=items, daily=daily, monthly=monthly, topc=topc)


# ---------- 상점관리 ----------
@bp.route("/admin/cash")
@M.admin_required
@M.super_required
def cash_page():
    s = (request.args.get("q") or "").strip()[:40]
    pg = max(1, request.args.get("p", 1, type=int)); per = 40
    w, a = "1=1", []
    if s:
        w, a = "m.nick LIKE ? OR m.login_id LIKE ?", ["%" + s + "%"] * 2
    total = q(f"SELECT COUNT(*) FROM cash_log c LEFT JOIN members m ON m.id=c.member_id WHERE {w}", a, one=True)[0]
    rows = q(f"""SELECT c.ts, c.member_id, m.nick, c.kind, c.delta, c.balance, c.reason, c.admin FROM cash_log c LEFT JOIN members m ON m.id=c.member_id
                WHERE {w} ORDER BY c.id DESC LIMIT {per} OFFSET {(pg - 1) * per}""", a)
    return render_template("admin.html", mode="cash", sec="cash", rows=rows, s=s, page=pg, pages=max(1, (total + per - 1) // per), total=total)


@bp.route("/admin/vips")
@M.admin_required
def vips_page():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    rows = q("SELECT id, nick, login_id, vip_until, mega, cash FROM members WHERE vip_until>? ORDER BY vip_until", (now,))
    soon = (datetime.now(KST) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    return render_template("admin.html", mode="vips", sec="vips", rows=rows, soon=soon)


# ---------- 대시보드 ----------
@bp.route("/admin/dash")
@M.admin_required
def dash():
    import admin_ext, vip
    t = _today().isoformat()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    v = admin_ext.visit_stats()
    d = {"vis": v["today"], "vis_y": v["yday"],
         "signup": q("SELECT COUNT(*) FROM members WHERE created_at LIKE ?", (t + "%",), one=True)[0],
         "total": q("SELECT COUNT(*) FROM members", one=True)[0],
         "susp": q("SELECT COUNT(*) FROM members WHERE status='suspended'", one=True)[0],
         "vip": q("SELECT COUNT(*) FROM members WHERE vip_until>?", (now,), one=True)[0],
         "chat": dict(_kvs("chatn:", [t])).get(t, 0),
         "pins": len([p for p in vip.all_pins() if p["pos"] == 0]),
         "mega_today": q("SELECT COUNT(*) FROM mega_log WHERE reason LIKE '사용%' AND ts LIKE ?", (t + "%",), one=True)[0],
         "cash_today": q("SELECT COALESCE(SUM(delta),0) FROM cash_log WHERE delta>0 AND kind IN ('charge','admin') AND ts LIKE ?", (t + "%",), one=True)[0]}
    bots = []
    try:
        bots = admin_ext.bot_status() if hasattr(admin_ext, "bot_status") else []
    except Exception:
        bots = []
    recent = q("SELECT id, nick, created_at FROM members ORDER BY id DESC LIMIT 5")
    return render_template("admin.html", mode="dash", sec="dash", d=d, recent=recent, bots=bots)

"""입금신청 — 회원이 USDT 등으로 보낸 뒤 신청 → 관리자가 확인 후 승인(캐시 지급) / 거절."""
import json, re, time, hmac, threading, logging
from flask import Blueprint, render_template, request, redirect, abort, flash, jsonify, g, session
import members as M
from members import q, alog, PG
import vip

log = logging.getLogger("deposit")
bp = Blueprint("deposit", __name__)
_lk = threading.Lock()
MAX_PENDING = 3
GAP = 60          # 초: 신청 간격
DAY_MAX = 10
ST = {"pending": "대기중", "approved": "완료", "rejected": "거절"}


def init_db():
    pk = "BIGSERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    q(f"""CREATE TABLE IF NOT EXISTS deposit_request(id {pk}, member_id BIGINT NOT NULL, packages TEXT NOT NULL, amount_krw INTEGER NOT NULL,
        cash INTEGER NOT NULL, txid TEXT, memo TEXT, status TEXT NOT NULL DEFAULT 'pending', reason TEXT, admin TEXT,
        created_at TEXT NOT NULL, decided_at TEXT, seen INTEGER NOT NULL DEFAULT 0)""", fetch=False)
    q("CREATE INDEX IF NOT EXISTS deposit_req_st ON deposit_request(status, id)", fetch=False)
    q("CREATE INDEX IF NOT EXISTS deposit_req_m ON deposit_request(member_id, id)", fetch=False)


def mine(mid, n=10):
    out = []
    for r in q("SELECT id, packages, amount_krw, cash, txid, status, reason, created_at, decided_at FROM deposit_request WHERE member_id=? ORDER BY id DESC LIMIT " + str(int(n)), (mid,)):
        try:
            pk = json.loads(r[1])
        except Exception:
            pk = []
        out.append({"id": r[0], "pk": pk, "krw": r[2], "cash": r[3], "txid": r[4], "st": r[5], "stl": ST.get(r[5], r[5]),
                    "reason": r[6], "at": (r[7] or "")[:16], "dec": (r[8] or "")[:16]})
    return out


def _parse(items):
    sel = []
    for part in (items or "").split(",")[:len(vip.CHARGE)]:
        mm = re.match(r"^(\d+)x(\d+)$", part.strip())
        if mm and int(mm.group(1)) in vip.CHARGE and 1 <= int(mm.group(2)) <= vip.QTY_MAX:
            if all(a != int(mm.group(1)) for a, _ in sel):
                sel.append((int(mm.group(1)), int(mm.group(2))))
    return sel


@bp.post("/shop/deposit")
def submit():
    m = M.current()
    if not m:
        return redirect("/login?next=/shop")
    t = request.form.get("_csrf", "")
    if not t or not hmac.compare_digest(t, session.get("_csrf", "")):
        abort(400, "CSRF")
    sel = _parse(request.form.get("items"))
    if not sel:
        flash("충전할 패키지를 골라 주세요."); return redirect("/shop#charge")
    txid = re.sub(r"[^0-9A-Za-z]", "", request.form.get("txid") or "")[:100]
    memo = re.sub(r"[\x00-\x1f<>]", "", request.form.get("memo") or "").strip()[:200]
    total = sum(a * n for a, n in sel)
    with _lk:
        pend = q("SELECT COUNT(*) FROM deposit_request WHERE member_id=? AND status='pending'", (m["id"],), one=True)[0]
        last = q("SELECT MAX(created_at) FROM deposit_request WHERE member_id=?", (m["id"],), one=True)[0]
        today = q("SELECT COUNT(*) FROM deposit_request WHERE member_id=? AND created_at LIKE ?", (m["id"], M.now_s()[:10] + "%"), one=True)[0]
        if pend >= MAX_PENDING:
            flash(f"확인 대기 중인 신청이 {MAX_PENDING}건 있어요. 처리된 뒤 다시 신청해 주세요."); return redirect("/shop#mydep")
        if today >= DAY_MAX:
            flash("오늘은 더 신청할 수 없어요. 고객센터로 문의해 주세요."); return redirect("/shop#mydep")
        if last and M.now_s() < _plus(last, GAP):
            flash("잠시 뒤에 다시 신청해 주세요 (1분 간격)."); return redirect("/shop#mydep")
        if txid and q("SELECT 1 FROM deposit_request WHERE txid=? AND status<>'rejected'", (txid,), one=True):
            flash("이미 신청된 TXID예요."); return redirect("/shop#mydep")
        q("INSERT INTO deposit_request(member_id,packages,amount_krw,cash,txid,memo,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
          (m["id"], json.dumps(sel), total, total, txid or None, memo or None, "pending", M.now_s()), fetch=False)
    flash(f"ok:입금신청을 받았어요 ({total:,}원). 관리자가 입금을 확인하면 캐시가 충전돼요.")
    return redirect("/shop#mydep")


def _plus(ts, sec):
    from datetime import datetime, timedelta
    try:
        return (datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


# ---------- 관리자 ----------
def counts():
    t = M.now_s()[:10] + "%"
    p = q("SELECT COUNT(*), COALESCE(SUM(amount_krw),0) FROM deposit_request WHERE status='pending'", one=True)
    a = q("SELECT COUNT(*), COALESCE(SUM(cash),0) FROM deposit_request WHERE status='approved' AND decided_at LIKE ?", (t,), one=True)
    r = q("SELECT COUNT(*) FROM deposit_request WHERE status='rejected' AND decided_at LIKE ?", (t,), one=True)
    return {"pending": int(p[0]), "pending_krw": int(p[1] or 0), "ok_n": int(a[0]), "ok_sum": int(a[1] or 0), "rej_n": int(r[0])}


@bp.route("/admin/deposits")
@M.admin_required
@M.super_required
def page():
    st = request.args.get("st", "pending")
    if st not in ("pending", "approved", "rejected", "all"):
        st = "pending"
    s = (request.args.get("q") or "").strip()[:40]
    w, a = [], []
    if st != "all":
        w.append("d.status=?"); a.append(st)
    if s:
        w.append("(m.nick LIKE ? OR m.login_id LIKE ? OR d.txid LIKE ?)"); a += ["%" + s + "%"] * 3
    where = ("WHERE " + " AND ".join(w)) if w else ""
    order = "d.id ASC" if st == "pending" else "d.id DESC"
    rows = q(f"""SELECT d.id, d.member_id, m.nick, m.login_id, d.packages, d.amount_krw, d.cash, d.txid, d.memo, d.status, d.reason, d.admin, d.created_at, d.decided_at
                FROM deposit_request d LEFT JOIN members m ON m.id=d.member_id {where} ORDER BY {order} LIMIT 200""", tuple(a))
    items = []
    for r in rows:
        try:
            pk = json.loads(r[4])
        except Exception:
            pk = []
        items.append({"id": r[0], "mid": r[1], "nick": r[2] or ("#%d" % r[1]), "lid": r[3], "pk": pk, "krw": r[5], "cash": r[6], "txid": r[7], "memo": r[8],
                      "st": r[9], "stl": ST.get(r[9], r[9]), "reason": r[10], "admin": r[11], "at": (r[12] or "")[5:16], "dec": (r[13] or "")[5:16]})
    return render_template("admin.html", mode="deposits", sec="deposits", items=items, st=st, s=s, dc=counts())


def _who():
    a = g.get("admin") or {}
    return str(a.get("name") or a.get("username") or a.get("id") or "admin")[:40]


@bp.post("/admin/deposits/<int:did>/approve")
@M.admin_required
@M.super_required
def approve(did):
    with _lk:
        r = q("SELECT member_id, cash, status, amount_krw FROM deposit_request WHERE id=?", (did,), one=True)
        if not r:
            abort(404)
        if r[2] != "pending":
            flash(f"#{did}은 이미 처리된 신청이에요 ({ST.get(r[2], r[2])})."); return redirect("/admin/deposits")
        new = vip.cash_change(r[0], int(r[1]), "charge", f"입금신청 #{did} 승인 ({int(r[3]):,}원)", admin=_who(), ref=f"dep:{did}")
        if new is None:
            flash("캐시 지급에 실패했어요. 회원이 있는지 확인해 주세요."); return redirect("/admin/deposits")
        q("UPDATE deposit_request SET status='approved', admin=?, decided_at=?, seen=0 WHERE id=? AND status='pending'", (_who(), M.now_s(), did), fetch=False)
    alog(f"deposit approve #{did} +{int(r[1])}", r[0])
    flash(f"#{did} 승인 완료 — {int(r[1]):,}캐시 지급 (잔액 {new:,})"); return redirect("/admin/deposits")


@bp.post("/admin/deposits/<int:did>/reject")
@M.admin_required
@M.super_required
def reject(did):
    reason = re.sub(r"[\x00-\x1f<>]", "", request.form.get("reason") or "").strip()[:120]
    with _lk:
        r = q("SELECT member_id, status FROM deposit_request WHERE id=?", (did,), one=True)
        if not r:
            abort(404)
        if r[1] != "pending":
            flash(f"#{did}은 이미 처리된 신청이에요."); return redirect("/admin/deposits")
        q("UPDATE deposit_request SET status='rejected', reason=?, admin=?, decided_at=?, seen=0 WHERE id=? AND status='pending'", (reason or None, _who(), M.now_s(), did), fetch=False)
    alog(f"deposit reject #{did} {reason}", r[0])
    flash(f"#{did} 거절했어요."); return redirect("/admin/deposits")


@bp.route("/admin/deposits/poll")
@M.admin_required
@M.super_required
def poll():
    r = q("SELECT COUNT(*), COALESCE(MAX(id),0) FROM deposit_request WHERE status='pending'", one=True)
    return jsonify(pending=int(r[0]), last=int(r[1]))

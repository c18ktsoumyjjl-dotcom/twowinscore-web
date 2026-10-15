"""VIP 구독 + 확성기(채팅방 상단 고정 메시지). 결제는 아직 없음: 관리자가 직접 지급."""
import time, threading, hmac, logging, re
from collections import deque
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, render_template, redirect, abort, flash
import members as M
from members import q, admin_required, alog, KST

log = logging.getLogger("vip")
bp = Blueprint("vip", __name__)
_ok = [False]
_lk = threading.RLock()
MONTHLY = 50   # VIP 월간 무료 확성기 (이 숫자 하나만 바꾸면 전부 반영)
PIN_SEC = 300
MAX_TEXT = 80
QMAX = 10
SCHEMA = """CREATE TABLE IF NOT EXISTS mega_log(id {pk}, ts TEXT NOT NULL, member_id BIGINT NOT NULL, delta INTEGER NOT NULL, reason TEXT, admin TEXT);
CREATE INDEX IF NOT EXISTS mega_log_mid ON mega_log(member_id);
CREATE TABLE IF NOT EXISTS cash_log(id {pk}, ts TEXT NOT NULL, member_id BIGINT NOT NULL, delta INTEGER NOT NULL, balance INTEGER NOT NULL, kind TEXT NOT NULL, reason TEXT, admin TEXT, ref TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS cash_log_mid ON cash_log(member_id)"""


def init_db():
    if not M.enabled():
        return
    try:
        pk = "BIGSERIAL PRIMARY KEY" if M.PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for s in SCHEMA.format(pk=pk).split(";"):
            q(s, fetch=False)
        for a in ("ALTER TABLE members ADD COLUMN vip_until TEXT",
                  "ALTER TABLE members ADD COLUMN vip_grant_m TEXT",
                  "ALTER TABLE members ADD COLUMN mega INTEGER NOT NULL DEFAULT 0",
                  "ALTER TABLE members ADD COLUMN cash INTEGER NOT NULL DEFAULT 0"):
            try:
                q(a, fetch=False)
            except Exception:
                pass
        _ok[0] = True
    except Exception:
        log.exception("vip init failed")


def _now():
    return datetime.now(KST)


def _fmt(d):
    return d.strftime("%Y-%m-%d %H:%M")


def _mlog(mid, delta, reason, admin=None):
    q("INSERT INTO mega_log(ts,member_id,delta,reason,admin) VALUES(?,?,?,?,?)", (M.now_s(), mid, delta, reason[:100], admin), fetch=False)


def info(mid):
    """{'active','until','mega'} · VIP 이면 이번 달 무료 확성기 MONTHLY개를 자동 지급(한 번만)."""
    if not _ok[0] or not mid:
        return None
    with _lk:
        r = q("SELECT vip_until, vip_grant_m, mega, cash FROM members WHERE id=?", (mid,), one=True)
        if not r:
            return None
        until = r[0]
        active = bool(until) and until > _fmt(_now())
        mega = int(r[2] or 0)
        if active:
            mon = _now().strftime("%Y-%m")
            if r[1] != mon:
                q("UPDATE members SET mega=mega+?, vip_grant_m=? WHERE id=?", (MONTHLY, mon, mid), fetch=False)
                _mlog(mid, MONTHLY, "VIP 월간 무료 지급 " + mon)
                mega += MONTHLY
    return {"active": active, "until": until, "mega": mega, "cash": int(r[3] or 0)}


def is_vip(mid):
    i = info(mid)
    return bool(i and i["active"])


def many(ids):
    if not _ok[0] or not ids:
        return {}
    ph = ",".join("?" * len(ids))
    now = _fmt(_now())
    return {r[0]: {"vip": bool(r[1]) and r[1] > now, "until": r[1], "mega": int(r[2] or 0)}
            for r in q(f"SELECT id, vip_until, mega FROM members WHERE id IN ({ph})", list(ids))}


@bp.app_context_processor
def _ctx():
    try:
        m = M.current()
    except Exception:
        m = None
    return {"vip": info(m["id"]) if m else None, "vip_monthly": MONTHLY}


# ---------- 확성기 고정 ----------
_pins = {}       # room -> deque of dict
_seq = [0]
_last_use = {}   # member_id -> ts


def _tick(room, now):
    dq = _pins.get(room)
    if not dq:
        return None
    while dq and dq[0].get("start") and now - dq[0]["start"] >= dq[0]["dur"]:
        dq.popleft()
    if not dq:
        _pins.pop(room, None)
        return None
    if not dq[0].get("start"):
        dq[0]["start"] = now
    return dq


def state(room, mid=None):
    now = time.time()
    with _lk:
        dq = _tick(room, now)
        if not dq:
            return None
        h = dq[0]
        out = {"id": h["id"], "nick": h["nick"], "text": h["text"], "lv": h.get("lv"), "vip": h.get("vip", 0),
               "left": max(0, int(h["dur"] - (now - h["start"]))), "queue": len(dq) - 1}
        if mid:
            pos = [i for i, x in enumerate(dq) if x["mid"] == mid and i > 0]
            if pos:
                out["mypos"] = pos[0]
        return out


def all_pins():
    now = time.time()
    with _lk:
        res = []
        for room in list(_pins):
            dq = _tick(room, now)
            for i, x in enumerate(dq or []):
                res.append({"room": room, "pos": i, **{k: x[k] for k in ("id", "nick", "text", "mid")},
                            "left": int(x["dur"] - (now - x["start"])) if x.get("start") else None})
        return res


@bp.post("/api/mega/<room>")
def mega_use(room):
    import chat, levels
    if not chat.ROOM_RE.match(room or ""):
        abort(404)
    m = M.current()
    if not m:
        return jsonify({"ok": False, "error": "로그인한 회원만 확성기를 쓸 수 있어요."}), 401
    tok = request.headers.get("X-CSRF", "")
    if not tok or not hmac.compare_digest(tok, session.get("_csrf", "")):
        return jsonify({"ok": False, "error": "페이지를 새로고침한 뒤 다시 시도해 주세요."}), 400
    b = request.get_json(silent=True) or {}
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(b.get("text") or ""))).strip()
    if not text:
        return jsonify({"ok": False, "error": "내용을 입력해 주세요."}), 400
    if len(text) > MAX_TEXT:
        return jsonify({"ok": False, "error": f"확성기는 {MAX_TEXT}자까지 쓸 수 있어요."}), 400
    ip, now = chat._ip(), time.time()
    with chat._lock:
        u = chat._muted(ip, m["nick"], now)
        if u:
            return jsonify({"ok": False, "error": "채팅이 제한된 상태라 확성기를 쓸 수 없어요."}), 403
        bad = chat.check_text(text)
        if bad:
            chat._violation(ip, m["nick"], now)
            return jsonify({"ok": False, "error": bad}), 400
    with _lk:
        if now - _last_use.get(m["id"], 0) < 60:
            return jsonify({"ok": False, "error": "확성기는 1분에 한 번 쓸 수 있어요."}), 429
        dq = _tick(room, now) or deque()
        if len(dq) >= QMAX:
            return jsonify({"ok": False, "error": "지금 대기 중인 확성기가 많아요. 잠시 뒤에 써 주세요."}), 429
        if sum(1 for x in dq if x["mid"] == m["id"]) >= 2:
            return jsonify({"ok": False, "error": "이 방에서는 확성기를 2개까지만 대기시킬 수 있어요."}), 429
        r = q("SELECT mega FROM members WHERE id=?", (m["id"],), one=True)
        if not r or int(r[0] or 0) < 1:
            return jsonify({"ok": False, "code": "no_mega", "error": "확성기가 없어요. 스코어샵에서 확인해 주세요."}), 400
        q("UPDATE members SET mega=mega-1 WHERE id=? AND mega>0", (m["id"],), fetch=False)
        _mlog(m["id"], -1, "사용 " + room)
        li = levels.info(m["id"])
        _seq[0] += 1
        dq.append({"id": _seq[0], "mid": m["id"], "nick": m["nick"], "text": text, "dur": PIN_SEC,
                   "lv": [li["name"], li["color"], li["i"]] if li else None, "vip": 1 if is_vip(m["id"]) else 0})
        _pins[room] = dq
        _last_use[m["id"]] = now
        pos = len(dq) - 1
        left = int(q("SELECT mega FROM members WHERE id=?", (m["id"],), one=True)[0] or 0)
    return jsonify({"ok": True, "pos": pos, "mega": left, "pin": state(room, m["id"])})


# ---------- 관리자 ----------
def _back(mid):
    return redirect(f"/admin/member/{mid}")


@bp.post("/admin/member/<int:mid>/vip")
@admin_required
def admin_vip(mid):
    if not q("SELECT 1 FROM members WHERE id=?", (mid,), one=True):
        abort(404)
    act = request.form.get("act")
    if act == "revoke":
        q("UPDATE members SET vip_until=NULL WHERE id=?", (mid,), fetch=False)
        alog("vip revoke", mid); flash("VIP를 해제했어요.")
    else:
        try:
            days = int(request.form.get("days", "30"))
        except ValueError:
            days = 0
        if not 1 <= days <= 3660:
            flash("일수는 1~3660 사이로 넣어 주세요."); return _back(mid)
        cur = q("SELECT vip_until FROM members WHERE id=?", (mid,), one=True)[0]
        base = _now()
        if cur and cur > _fmt(base):
            base = datetime.strptime(cur, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        nu = _fmt(base + timedelta(days=days))
        q("UPDATE members SET vip_until=? WHERE id=?", (nu, mid), fetch=False)
        alog(f"vip +{days}d -> {nu}", mid); flash(f"VIP {days}일 연장 → {nu}까지")
        info(mid)  # 이번 달 무료 확성기 지급
    return _back(mid)


@bp.post("/admin/member/<int:mid>/mega")
@admin_required
def admin_mega(mid):
    try:
        d = int(request.form.get("delta", "0"))
    except ValueError:
        d = 0
    reason = (request.form.get("reason") or "").strip()[:60]
    with _lk:
        r = q("SELECT mega FROM members WHERE id=?", (mid,), one=True)
        if not r:
            abort(404)
        if not d or not -1000 <= d <= 1000:
            flash("수량은 -1000~1000 사이로 넣어 주세요."); return _back(mid)
        new = max(0, int(r[0] or 0) + d)
        q("UPDATE members SET mega=? WHERE id=?", (new, mid), fetch=False)
        adm = session.get("adm_id")
        _mlog(mid, new - int(r[0] or 0), "관리자 조정" + (": " + reason if reason else ""), str(adm or "관리자"))
    alog(f"mega {d:+d} -> {new}", mid); flash(f"확성기 {d:+d} → {new}개")
    return _back(mid)


def mega_logs(mid, n=30):
    if not _ok[0]:
        return []
    return q("SELECT ts, delta, reason, admin FROM mega_log WHERE member_id=? ORDER BY id DESC LIMIT " + str(int(n)), (mid,))


@bp.route("/admin/mega")
@admin_required
def admin_mega_page():
    return render_template("admin.html", mode="mega", sec="mega", pins=all_pins())


@bp.post("/admin/mega/remove")
@admin_required
def admin_mega_remove():
    room, pid = request.form.get("room", ""), request.form.get("id", type=int)
    with _lk:
        dq = _pins.get(room)
        hit = [x for x in (dq or []) if x["id"] == pid]
        for x in hit:
            dq.remove(x)
        if dq is not None and not dq:
            _pins.pop(room, None)
        elif dq and hit and dq[0].get("start") is None:
            pass
    if hit:
        alog("mega remove " + room + " " + hit[0]["text"][:40], hit[0]["mid"]); flash("확성기를 내렸어요 (환불 없음).")
    return redirect("/admin/mega")


# ---------- 스코어캐시 (유료 재화: 1원 = 1캐시 · 출금/환전/양도/경품 교환 불가) ----------
CHARGE = [5000, 10000, 30000, 50000, 100000]
QTY_MAX = 10
VIP_PLANS = {"vip1": {"m": 1, "days": 30, "price": 200000, "off": 0},
             "vip2": {"m": 2, "days": 60, "price": 360000, "off": 10},
             "vip3": {"m": 3, "days": 90, "price": 480000, "off": 20}}
VIP_PRICE = VIP_PLANS["vip1"]["price"]
VIP_DAYS = 30
ITEMS = {"mega1": ("확성기 1개", 1000, 1), "mega10": ("확성기 10개", 8000, 10), "mega30": ("확성기 30개", 20000, 30)}


def cash_of(mid):
    r = q("SELECT cash FROM members WHERE id=?", (mid,), one=True)
    return int(r[0] or 0) if r else 0


def cash_change(mid, delta, kind, reason="", admin=None, ref=None):
    """잔액 변경 + 원장 기록. 음수 잔액 불가. ref 가 있으면 같은 ref 로 두 번 들어오지 않음(결제 웹훅 중복 방지).
    성공 시 새 잔액, 잔액 부족이면 None."""
    with _lk:
        if ref and q("SELECT 1 FROM cash_log WHERE ref=?", (ref,), one=True):
            return cash_of(mid)
        cur = q("SELECT cash FROM members WHERE id=?", (mid,), one=True)
        if not cur:
            return None
        bal = int(cur[0] or 0)
        if bal + delta < 0:
            return None
        q("UPDATE members SET cash=cash+? WHERE id=? AND cash+?>=0", (delta, mid, delta), fetch=False)
        new = cash_of(mid)
        if new != bal + delta:   # 조건부 UPDATE 가 적용되지 않음
            return None
        q("INSERT INTO cash_log(ts,member_id,delta,balance,kind,reason,admin,ref) VALUES(?,?,?,?,?,?,?,?)",
          (M.now_s(), mid, delta, new, kind, (reason or "")[:100], admin, ref), fetch=False)
        return new


def cash_logs(mid, n=30):
    if not _ok[0]:
        return []
    return q("SELECT ts, delta, balance, kind, reason FROM cash_log WHERE member_id=? ORDER BY id DESC LIMIT " + str(int(n)), (mid,))


@bp.route("/shop")
def shop():
    import payments
    m = M.current()
    return render_template("shop.html", page="shop", items=ITEMS, charge=CHARGE, vip_price=VIP_PRICE, vip_days=VIP_DAYS, vip_plans=VIP_PLANS,
                           cash=cash_of(m["id"]) if m else None, pay_ready=payments.ready(),
                           deps=__import__("deposit").mine(m["id"]) if m else [])


@bp.post("/shop/buy")
def shop_buy():
    m = M.current()
    if not m:
        return redirect("/login?next=/shop")
    t = request.form.get("_csrf", "")
    if not t or not hmac.compare_digest(t, session.get("_csrf", "")):
        abort(400, "CSRF")
    if M.limited("buy:%s" % m["id"], 20, 60):
        flash("잠시 뒤에 다시 시도해 주세요."); return redirect("/shop")
    it = request.form.get("item", "")
    with _lk:
        if it in ITEMS:
            name, price, n = ITEMS[it]
            new = cash_change(m["id"], -price, "buy", name)
            if new is None:
                flash("스코어캐시가 부족해요."); return redirect("/shop")
            q("UPDATE members SET mega=mega+? WHERE id=?", (n, m["id"]), fetch=False)
            _mlog(m["id"], n, "스코어샵 구매 (" + name + ")")
            flash(f"ok:{name} 구매 완료! 남은 캐시 {new:,}")
        elif it in VIP_PLANS:
            pl = VIP_PLANS[it]
            new = cash_change(m["id"], -pl["price"], "buy", f"VIP {pl['m']}개월")
            if new is None:
                flash("스코어캐시가 부족해요."); return redirect("/shop")
            cur = q("SELECT vip_until FROM members WHERE id=?", (m["id"],), one=True)[0]
            base = _now()
            if cur and cur > _fmt(base):
                base = datetime.strptime(cur, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            q("UPDATE members SET vip_until=? WHERE id=?", (_fmt(base + timedelta(days=pl["days"])), m["id"]), fetch=False)
            info(m["id"])
            flash(f"ok:VIP {pl['m']}개월 구매 완료! {_fmt(base + timedelta(days=pl['days']))}까지 · 남은 캐시 {new:,}")
        else:
            abort(400)
    return redirect("/shop")


@bp.post("/shop/charge")
def shop_charge():
    import payments
    m = M.current()
    if not m:
        return redirect("/login?next=/shop")
    t = request.form.get("_csrf", "")
    if not t or not hmac.compare_digest(t, session.get("_csrf", "")):
        abort(400, "CSRF")
    sel = []
    for part in (request.form.get("items") or "").split(",")[:len(CHARGE)]:
        mm = re.match(r"^(\d+)x(\d+)$", part.strip())
        if mm and int(mm.group(1)) in CHARGE and 1 <= int(mm.group(2)) <= QTY_MAX:
            sel.append((int(mm.group(1)), int(mm.group(2))))
    if not sel:
        abort(400)
    amt = sum(a_ * n_ for a_, n_ in sel)
    url = payments.start_charge(m["id"], amt, sel)
    if not url:
        flash("결제 준비 중이에요. 고객센터로 문의해 주세요."); return redirect("/shop")
    return redirect(url)


@bp.post("/admin/member/<int:mid>/cash")
@admin_required
@M.super_required
def admin_cash(mid):
    try:
        d = int(request.form.get("delta", "0"))
    except ValueError:
        d = 0
    reason = (request.form.get("reason") or "").strip()[:60]
    if not q("SELECT 1 FROM members WHERE id=?", (mid,), one=True):
        abort(404)
    if not d or not -10000000 <= d <= 10000000 or not reason:
        flash("금액(±1천만 이내)과 사유를 넣어 주세요."); return _back(mid)
    new = cash_change(mid, d, "admin", reason, str(session.get("adm_id") or "관리자"))
    if new is None:
        flash("잔액보다 많이 뺄 수 없어요."); return _back(mid)
    alog(f"cash {d:+d} -> {new} ({reason})", mid); flash(f"스코어캐시 {d:+,d} → {new:,}")
    return _back(mid)

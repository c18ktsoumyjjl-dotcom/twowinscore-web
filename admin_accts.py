"""관리자 계정 관리(최고관리자 전용), 신규 관리자 첫 로그인 설정, 관리자 회원 직접 생성, 등급 직접 변경."""
import re, time, secrets, logging
from flask import Blueprint, render_template, request, redirect, abort, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash
import members as M

bp = Blueprint("admin_accts", __name__)
log = logging.getLogger("admin_accts")
q = M.q
ROLES = {"owner": "최고관리자", "admin": "일반관리자"}


def _back(default):
    ref = request.referrer or ""
    return redirect(ref if ref.startswith(request.host_url + "admin") else default)


# ---------- 관리자 계정 (최고관리자만) ----------
@bp.route("/admin/admins")
@M.admin_required
@M.super_required
def admins_page():
    rows = q("SELECT id,username,role,status,must_setup,created_at,last_login,created_by FROM admins ORDER BY id")
    ad = [{"id": r[0], "u": r[1], "role": ROLES.get(r[2], r[2]), "owner": r[2] == "owner", "status": r[3], "pending": bool(r[4]),
           "created": (r[5] or "")[:16], "last": (r[6] or "")[:16], "by": r[7] or "", "me": r[0] == g.admin["id"]} for r in rows]
    return render_template("admin.html", mode="admins", sec="admins", ad=ad, roles=ROLES, f={})


@bp.post("/admin/admins/new")
@M.admin_required
@M.super_required
def admin_new():
    u = (request.form.get("username") or "").strip().lower()
    pw, role = request.form.get("pw", ""), request.form.get("role", "admin")
    err = ""
    if role not in ROLES: err = "권한을 골라 주세요."
    elif not M.ADM_RE.match(u): err = "관리자 아이디는 영문 소문자·숫자·_ 4~20자로 해 주세요."
    elif not M.strong_pw(pw): err = "초기 비밀번호는 12자 이상, 대문자·소문자·숫자·특수문자 중 3종류 이상으로 해 주세요."
    elif q("SELECT 1 FROM admins WHERE username=?", (u,), one=True): err = "이미 있는 관리자 아이디예요."
    if err:
        flash(err); return redirect("/admin/admins")
    q("INSERT INTO admins(username,pw,totp_e,last_step,created_at,role,status,must_setup,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
      (u, generate_password_hash(pw), "", 0, M.now_s(), role, "active", 1, g.admin["username"]), fetch=False)
    M.alog("admin_create %s (%s)" % (u, ROLES[role]), u)
    flash(f"관리자 {u} 계정을 만들었어요. 첫 로그인 때 비밀번호 변경과 Google OTP 등록을 하게 돼요.")
    return redirect("/admin/admins")


@bp.post("/admin/admins/<int:aid>/<act>")
@M.admin_required
@M.super_required
def admin_act(aid, act):
    r = q("SELECT username, role, status FROM admins WHERE id=?", (aid,), one=True)
    if not r: abort(404)
    if aid == g.admin["id"]:
        flash("내 계정은 여기서 바꿀 수 없어요."); return redirect("/admin/admins")
    owners = q("SELECT COUNT(*) FROM admins WHERE role='owner' AND status='active'", one=True)[0]
    last_owner = r[1] == "owner" and r[2] == "active" and owners <= 1
    if act == "disable":
        if last_owner: flash("마지막 최고관리자는 중지할 수 없어요."); return redirect("/admin/admins")
        q("UPDATE admins SET status='disabled' WHERE id=?", (aid,), fetch=False)
    elif act == "enable":
        q("UPDATE admins SET status='active' WHERE id=?", (aid,), fetch=False)
    elif act == "delete":
        if last_owner: flash("마지막 최고관리자는 삭제할 수 없어요."); return redirect("/admin/admins")
        q("DELETE FROM admin_backup WHERE admin_id=?", (aid,), fetch=False)
        q("DELETE FROM admins WHERE id=?", (aid,), fetch=False)
    elif act == "reset":  # 비밀번호·OTP 초기화 → 첫 로그인 설정 다시
        pw = request.form.get("pw", "")
        if not M.strong_pw(pw):
            flash("새 초기 비밀번호는 12자 이상, 3종류 이상으로 해 주세요."); return redirect("/admin/admins")
        q("UPDATE admins SET pw=?, totp_e='', last_step=0, must_setup=1 WHERE id=?", (generate_password_hash(pw), aid), fetch=False)
        q("DELETE FROM admin_backup WHERE admin_id=?", (aid,), fetch=False)
    elif act == "role":
        role = request.form.get("role")
        if role not in ROLES: abort(400)
        if last_owner and role != "owner": flash("마지막 최고관리자의 권한은 내릴 수 없어요."); return redirect("/admin/admins")
        q("UPDATE admins SET role=? WHERE id=?", (role, aid), fetch=False)
        act = "role->" + role
    else:
        abort(400)
    M.alog("admin_%s %s" % (act, r[0]), r[0])
    flash(f"{r[0]}: 처리했어요.")
    return redirect("/admin/admins")


# ---------- 새 관리자 첫 로그인: 비밀번호 변경 + OTP 등록 ----------
@bp.route("/admin/first", methods=["GET", "POST"])
def first_login():
    if not M.enabled(): abort(404)
    fs = session.get("adm_first")
    if not fs or time.time() - fs["t"] > 15 * 60:
        session.pop("adm_first", None); M._pdel("fs_tok"); return redirect("/admin/login")
    r = q("SELECT username, pw, status, must_setup FROM admins WHERE id=?", (fs["id"],), one=True)
    if not r or r[2] != "active" or not r[3]:
        session.pop("adm_first", None); return redirect("/admin/login")
    tok, p = M._pget("fs_tok")
    if p and p.get("aid") != fs["id"]:
        M._pdel("fs_tok"); p = None
    errs = []
    if request.method == "POST" and request.form.get("step") == "1":
        pw = request.form.get("pw", "")
        if M.limited("admf|" + M.ip(), 20, 600): errs.append("시도가 너무 많아요. 잠시 뒤에 다시 해 주세요.")
        elif not M.strong_pw(pw): errs.append("비밀번호는 12자 이상, 대문자·소문자·숫자·특수문자 중 3종류 이상으로 해 주세요.")
        elif pw != request.form.get("pw2", ""): errs.append("비밀번호 확인이 일치하지 않아요.")
        elif check_password_hash(r[1], pw): errs.append("받은 초기 비밀번호와 다른 비밀번호를 써 주세요.")
        if not errs:
            import pyotp
            M._pdel("fs_tok"); M._pset("fs_tok", {"aid": fs["id"], "pw": generate_password_hash(pw), "sec": pyotp.random_base32()})
            return redirect("/admin/first")
        return render_template("admin.html", mode="first", errs=errs, u=r[0])
    if p and request.method == "POST" and request.form.get("step") == "2":
        s = M._totp_step(p["sec"], request.form.get("code"))
        if s is None or M.limited("admf2|" + M.ip(), 20, 600):
            errs.append("OTP 코드가 맞지 않아요. 휴대폰 시간이 맞는지 확인하고 새 코드를 넣어 주세요.")
        else:
            q("UPDATE admins SET pw=?, totp_e=?, last_step=?, must_setup=0, last_login=? WHERE id=?",
              (p["pw"], M.enc(p["sec"]), s, M.now_s(), fs["id"]), fetch=False)
            codes = M._new_backups(); M._save_backups(fs["id"], codes)
            M._pdel("fs_tok"); session.pop("adm_first", None)
            M._admin_start(fs["id"])
            M.alog("first_setup_done", r[0])
            return render_template("admin.html", mode="codes", codes=codes, after="reset")
    if p:
        return render_template("admin.html", mode="setup2", errs=errs, qr=M._qr(p["sec"], r[0]), sec=p["sec"], u=r[0], action="/admin/first")
    return render_template("admin.html", mode="first", errs=errs, u=r[0])


# ---------- 회원 직접 만들기 (모든 관리자) ----------
@bp.route("/admin/members/new", methods=["GET", "POST"])
@M.admin_required
def member_new():
    import levels, chat
    f = {k: (request.form.get(k) or "").strip() for k in ("login_id", "nick", "name", "phone", "birth", "tg", "tier")}
    errs = []
    if request.method == "POST":
        lid = f["login_id"].lower(); f["login_id"] = lid
        pw = request.form.get("pw", "")
        if not M.LOGIN_RE.match(lid): errs.append("아이디는 영문 소문자·숫자·_ 4~16자로 해 주세요.")
        if len(pw) < 4 or len(pw) > 64 or not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
            errs.append("비밀번호는 영문과 숫자를 섞어 4자 이상으로 해 주세요.")
        # 관리자 생성 계정: 금칙어·예약어·문자 규칙 생략. 비어 있지 않음·20자 이하·제어문자 없음만 확인 (출력은 이스케이프됨)
        f["nick"] = re.sub(r"\s+", " ", f["nick"]).strip()
        if not f["nick"]: errs.append("닉네임을 입력해 주세요.")
        elif len(f["nick"]) > 20: errs.append("닉네임은 20자 이하로 해 주세요.")
        elif re.search(r"[\x00-\x1f\x7f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]", f["nick"]): errs.append("닉네임에 쓸 수 없는 보이지 않는 문자가 있어요.")
        if f["name"] and (len(f["name"]) > 30 or re.search(r"[<>\d]", f["name"])): errs.append("이름을 정확히 입력해 주세요.")
        ph = M.norm_phone(f["phone"]) if f["phone"] else ""
        if f["phone"] and not ph: errs.append("휴대폰 번호 형식이 올바르지 않아요.")
        b = M.parse_birth(f["birth"]) if f["birth"] else None
        if f["birth"] and not b: errs.append("생년월일은 6자리로 입력해 주세요. (예: 940531)")
        tg = f["tg"].lstrip("@")
        if tg and not M.TG_RE.match(tg): errs.append("텔레그램 아이디 형식이 올바르지 않아요.")
        ti = int(f["tier"]) if f["tier"].isdigit() and int(f["tier"]) < len(levels.TIERS) else 0
        if not errs:
            if q("SELECT 1 FROM members WHERE login_id=?", (lid,), one=True): errs.append("이미 사용 중인 아이디예요.")
            if q("SELECT 1 FROM members WHERE nick_l=?", (f["nick"].lower(),), one=True): errs.append("이미 다른 회원이 쓰는 닉네임이에요. 다른 닉네임을 넣어 주세요.")
            if ph and q("SELECT 1 FROM members WHERE phone_h=?", (M.phone_hash(ph),), one=True): errs.append("이미 가입된 휴대폰 번호예요.")
            if tg and q("SELECT 1 FROM members WHERE tg=?", (tg.lower(),), one=True): errs.append("이미 등록된 텔레그램 아이디예요.")
        if not errs:
            t = M.now_s()
            phh = M.phone_hash(ph) if ph else "admin:" + secrets.token_hex(16)  # 휴대폰 없는 계정: 겹치지 않는 자리표시
            try:
                q("INSERT INTO members(login_id,nick,nick_l,pw,name_e,phone_e,phone_h,birth_e,tg,created_at,agreed_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (lid, f["nick"], f["nick"].lower(), generate_password_hash(pw), M.enc(f["name"] or "-"), M.enc(ph or "-"), phh,
                   M.enc(b.isoformat() if b else "-"), tg.lower() or None, t, t, g.admin["username"]), fetch=False)
            except Exception:
                log.exception("admin member insert"); errs.append("저장하지 못했어요. 다시 확인해 주세요.")
            if not errs:
                mid = q("SELECT id FROM members WHERE login_id=?", (lid,), one=True)[0]
                if ti and levels._ok[0]: levels.admin_set_tier(mid, ti)
                M.alog("member_create %s (%s)" % (lid, levels.TIERS[ti][0]), mid)
                flash(f"회원 {lid} 계정을 만들었어요.")
                return redirect(f"/admin/member/{mid}")
    return render_template("admin.html", mode="mnew", sec="members", f=f, errs=errs, tiers=levels.TIERS)


# ---------- 등급 직접 변경 ----------
@bp.post("/admin/member/<int:mid>/tier")
@M.admin_required
def member_tier(mid):
    import levels
    try:
        i = int(request.form.get("tier", ""))
    except ValueError:
        abort(400)
    if not (0 <= i < len(levels.TIERS)) or not levels._ok[0] or not q("SELECT 1 FROM members WHERE id=?", (mid,), one=True):
        abort(400)
    old, new = levels.admin_set_tier(mid, i)
    M.alog("tier -> %s (%d -> %d점)" % (levels.TIERS[i][0], old, new), mid)
    flash(f"#{mid} 등급을 {levels.TIERS[i][0]}(으)로 바꿨어요. ({old}점 → {new}점)")
    return _back(f"/admin/member/{mid}")

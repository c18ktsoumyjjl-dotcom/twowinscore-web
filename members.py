"""투윈스코어 회원 / 관리자. 금전·포인트 기능 없음.
저장소: DATABASE_URL(Postgres) 있으면 사용, 없으면 SQLite (DATA_DIR/members.db).
개인정보(이름·전화·생년월일)는 Fernet(MEMBER_ENC_KEY)로 암호화, 전화번호 중복 확인은 HMAC 해시."""
import os, re, time, hmac, hashlib, secrets, threading, sqlite3, csv, io, logging
from datetime import datetime, date, timedelta, timezone
from collections import deque
from functools import wraps
from flask import (Blueprint, render_template, request, session, redirect, abort, g, Response, flash, url_for)
from werkzeug.security import generate_password_hash, check_password_hash

log = logging.getLogger("members")
bp = Blueprint("members", __name__)
KST = timezone(timedelta(hours=9))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
ENC_KEY = os.environ.get("MEMBER_ENC_KEY", "").strip()
_ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_HASH = generate_password_hash(_ADMIN_PW) if len(_ADMIN_PW) >= 10 else None
del _ADMIN_PW
ADMIN_TTL = 30 * 60

_fernet = None
if ENC_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(ENC_KEY.encode())
    except Exception as e:  # 잘못된 키
        log.error("MEMBER_ENC_KEY invalid: %s", e)
_HKEY = hashlib.sha256(b"twowin-phone|" + ENC_KEY.encode()).digest()


def enabled():
    return _fernet is not None


def enc(s):
    return _fernet.encrypt(s.encode()).decode()


def dec(s):
    try:
        return _fernet.decrypt(s.encode()).decode()
    except Exception:
        return "(복호화 실패)"


def phone_hash(p):
    return hmac.new(_HKEY, p.encode(), hashlib.sha256).hexdigest()


# ---------- DB ----------
PG = bool(DATABASE_URL)
_dblock = threading.Lock()
SCHEMA = """CREATE TABLE IF NOT EXISTS members(
 id {pk}, login_id TEXT NOT NULL UNIQUE, nick TEXT NOT NULL, nick_l TEXT NOT NULL UNIQUE,
 pw TEXT NOT NULL, name_e TEXT NOT NULL, phone_e TEXT NOT NULL, phone_h TEXT NOT NULL UNIQUE,
 birth_e TEXT NOT NULL, tg TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'active',
 created_at TEXT NOT NULL, agreed_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS admin_log(id {pk}, ts TEXT NOT NULL, ip TEXT, action TEXT NOT NULL, target TEXT)"""


def _connect():
    if PG:
        import psycopg
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg.connect(url, autocommit=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(os.path.join(DATA_DIR, "members.db"), check_same_thread=False, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    return c


_conn = [None]


def q(sql, args=(), one=False, fetch=True):
    if PG:
        sql = sql.replace("?", "%s")
    with _dblock:
        if _conn[0] is None:
            _conn[0] = _connect()
        try:
            cur = _conn[0].cursor()
            cur.execute(sql, args)
        except Exception as e:
            if PG and "closed" in str(e).lower():
                _conn[0] = _connect(); cur = _conn[0].cursor(); cur.execute(sql, args)
            else:
                raise
        if not fetch or cur.description is None:
            return None
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows


def init_db():
    if not enabled():
        log.warning("MEMBER_ENC_KEY 없음: 회원 기능 비활성")
        return
    pk = "BIGSERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    for s in SCHEMA.format(pk=pk).split(";"):
        q(s, fetch=False)
    log.warning("member storage: %s", "postgres" if PG else os.path.join(DATA_DIR, "members.db"))


def storage_desc():
    return "Postgres(DATABASE_URL)" if PG else "SQLite " + os.path.join(DATA_DIR, "members.db")


# ---------- 공통 보안 ----------
def ip():
    import chat
    return chat._ip()


_rl, _rl_lock = {}, threading.Lock()


def limited(key, lim, win):
    now = time.time()
    with _rl_lock:
        dq = _rl.setdefault(key, deque())
        while dq and now - dq[0] > win:
            dq.popleft()
        if len(dq) >= lim:
            return True
        dq.append(now)
        if len(_rl) > 20000:
            for k in [k for k, d in _rl.items() if not d or now - d[-1] > 3600]:
                _rl.pop(k, None)
    return False


def csrf_token():
    t = session.get("_csrf")
    if not t:
        t = session["_csrf"] = secrets.token_urlsafe(24)
    return t


@bp.app_context_processor
def _ctx():
    return {"csrf_token": csrf_token, "me": current()}


@bp.before_app_request
def _csrf_check():
    if request.method == "POST" and (request.path.startswith(("/login", "/signup", "/logout", "/me", "/admin"))):
        t = request.form.get("_csrf", "")
        if not t or not hmac.compare_digest(t, session.get("_csrf", "")):
            abort(400, "CSRF")


def current():
    if "_me" in g:
        return g._me
    g._me = None
    uid = session.get("uid")
    if uid and enabled():
        r = q("SELECT id, login_id, nick, status FROM members WHERE id=?", (uid,), one=True)
        if r and r[3] == "active":
            g._me = {"id": r[0], "login_id": r[1], "nick": r[2]}
        else:
            session.pop("uid", None)
    return g._me


def member_nick_taken(nick):
    if not enabled():
        return False
    return q("SELECT 1 FROM members WHERE nick_l=?", (nick.lower(),), one=True) is not None


# ---------- 검증 ----------
LOGIN_RE = re.compile(r"^[a-z0-9_]{4,16}$")
TG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def norm_phone(p):
    d = re.sub(r"\D", "", p or "")
    return d if re.fullmatch(r"01[016789]\d{7,8}", d) else None


def age(b, today=None):
    t = today or datetime.now(KST).date()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def fmt_phone(d):
    return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"


def mask_phone(d):
    return f"{d[:3]}-****-{d[-4:]}"


def now_s():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


# ---------- 회원 ----------
@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if not enabled():
        return render_template("member.html", page="signup", mode="off")
    if current():
        return redirect("/me")
    f = {k: (request.form.get(k) or "").strip() for k in ("login_id", "nick", "name", "phone", "birth", "tg")}
    errs = []
    if request.method == "POST":
        if limited("su|" + ip(), 5, 3600):
            errs.append("가입 시도가 너무 많아요. 1시간 뒤에 다시 해 주세요.")
        else:
            import chat
            lid = f["login_id"].lower(); f["login_id"] = lid
            pw, pw2 = request.form.get("pw", ""), request.form.get("pw2", "")
            if not LOGIN_RE.match(lid): errs.append("아이디는 영문 소문자·숫자·_ 4~16자로 해 주세요.")
            if len(pw) < 8 or len(pw) > 64 or not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
                errs.append("비밀번호는 영문과 숫자를 섞어 8자 이상으로 해 주세요.")
            elif pw != pw2: errs.append("비밀번호 확인이 일치하지 않아요.")
            ne = chat.check_nick(f["nick"])
            if ne: errs.append(ne if f["nick"] else "닉네임을 입력해 주세요.")
            if not (1 <= len(f["name"]) <= 30) or re.search(r"[<>\d]", f["name"]): errs.append("이름을 정확히 입력해 주세요.")
            ph = norm_phone(f["phone"])
            if not ph: errs.append("휴대폰 번호 형식이 올바르지 않아요. (예: 010-1234-5678)")
            try:
                b = date.fromisoformat(f["birth"])
                if b.year < 1900 or b > datetime.now(KST).date(): raise ValueError
                if age(b) < 14: errs.append("만 14세 미만은 가입할 수 없어요.")
            except ValueError:
                b = None; errs.append("생년월일을 정확히 입력해 주세요.")
            tg = f["tg"].lstrip("@")
            if tg and not TG_RE.match(tg): errs.append("텔레그램 아이디는 영문으로 시작하는 5~32자(영문·숫자·_)예요.")
            if request.form.get("agree") != "1": errs.append("개인정보 수집·이용에 동의해 주세요.")
            if not errs:
                if q("SELECT 1 FROM members WHERE login_id=?", (lid,), one=True): errs.append("이미 사용 중인 아이디예요.")
                if q("SELECT 1 FROM members WHERE nick_l=?", (f["nick"].lower(),), one=True): errs.append("이미 사용 중인 닉네임이에요.")
                if q("SELECT 1 FROM members WHERE phone_h=?", (phone_hash(ph),), one=True): errs.append("이미 가입된 휴대폰 번호예요.")
                if tg and q("SELECT 1 FROM members WHERE tg=?", (tg.lower(),), one=True): errs.append("이미 등록된 텔레그램 아이디예요.")
            if not errs:
                t = now_s()
                try:
                    q("INSERT INTO members(login_id,nick,nick_l,pw,name_e,phone_e,phone_h,birth_e,tg,created_at,agreed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (lid, f["nick"], f["nick"].lower(), generate_password_hash(pw), enc(f["name"]), enc(ph), phone_hash(ph),
                       enc(b.isoformat()), tg.lower() or None, t, t), fetch=False)
                except Exception:
                    log.exception("signup insert")
                    errs.append("이미 사용 중인 정보가 있어요. 다시 확인해 주세요.")
                if not errs:
                    r = q("SELECT id FROM members WHERE login_id=?", (lid,), one=True)
                    session.clear(); session.permanent = True; session["uid"] = r[0]
                    return redirect("/me?welcome=1")
    return render_template("member.html", page="signup", mode="signup", f=f, errs=errs)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not enabled():
        return render_template("member.html", page="login", mode="off")
    if current():
        return redirect("/me")
    errs, lid = [], (request.form.get("login_id") or "").strip().lower()
    nxt = request.values.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//"): nxt = "/"
    if request.method == "POST":
        if limited("li|" + ip(), 10, 600) or limited("lid|" + lid, 8, 900):
            errs.append("로그인 시도가 너무 많아요. 잠시 뒤에 다시 해 주세요.")
        else:
            r = q("SELECT id, pw, status FROM members WHERE login_id=?", (lid,), one=True)
            if not r or not check_password_hash(r[1], request.form.get("pw", "")):
                errs.append("아이디 또는 비밀번호가 맞지 않아요.")
            elif r[2] != "active":
                errs.append("이용이 정지된 계정이에요. 고객센터로 문의해 주세요.")
            else:
                session.clear(); session.permanent = True; session["uid"] = r[0]
                q("UPDATE members SET last_login=? WHERE id=?", (now_s(), r[0]), fetch=False)
                return redirect(nxt)
    return render_template("member.html", page="login", mode="login", lid=lid, errs=errs, nxt=nxt)


@bp.post("/logout")
def logout():
    session.pop("uid", None)
    return redirect("/")


@bp.route("/me", methods=["GET"])
def me_page():
    m = current()
    if not m:
        return redirect("/login?next=/me")
    r = q("SELECT name_e, phone_e, birth_e, tg, created_at FROM members WHERE id=?", (m["id"],), one=True)
    info = {"name": dec(r[0]), "phone": mask_phone(dec(r[1])), "birth": dec(r[2]), "tg": r[3], "created": r[4][:10]}
    return render_template("member.html", page="me", mode="me", info=info, welcome=request.args.get("welcome"))


@bp.post("/me/delete")
def me_delete():
    m = current()
    if not m:
        return redirect("/login")
    r = q("SELECT pw FROM members WHERE id=?", (m["id"],), one=True)
    if not r or not check_password_hash(r[0], request.form.get("pw", "")) or limited("del|" + str(m["id"]), 5, 600):
        flash("비밀번호가 맞지 않아요.")
        return redirect("/me#del")
    q("DELETE FROM members WHERE id=?", (m["id"],), fetch=False)
    session.clear()
    return render_template("member.html", page="me", mode="bye")


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html", page="privacy")


# ---------- 관리자 ----------
_fail = {}


def _admin_ok():
    t = session.get("adm")
    if not t or time.time() - t > ADMIN_TTL:
        session.pop("adm", None)
        return False
    session["adm"] = time.time()
    return True


def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not ADMIN_HASH or not enabled():
            return render_template("admin.html", mode="off", enc=enabled(), pw=bool(ADMIN_HASH)), 503
        if not _admin_ok():
            return redirect("/admin/login")
        return fn(*a, **k)
    return w


def alog(action, target=""):
    q("INSERT INTO admin_log(ts,ip,action,target) VALUES(?,?,?,?)", (now_s(), ip(), action, str(target)), fetch=False)


@bp.after_app_request
def _noindex(r):
    if request.path.startswith("/admin"):
        r.headers["X-Robots-Tag"] = "noindex, nofollow"
        r.headers["Cache-Control"] = "no-store"
    elif request.path.startswith(("/me", "/login", "/signup")):
        r.headers["Cache-Control"] = "no-store"
    return r


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_HASH or not enabled():
        return render_template("admin.html", mode="off", enc=enabled(), pw=bool(ADMIN_HASH)), 503
    err, key = "", ip()
    now = time.time()
    st = _fail.get(key, [0, 0])
    if st[1] > now:
        err = f"로그인 실패가 많아 {int((st[1] - now) // 60) + 1}분 동안 잠겼어요."
    elif request.method == "POST":
        if limited("adm|" + key, 10, 600) or limited("adm|all", 30, 600):
            err = "시도가 너무 많아요. 잠시 뒤에 다시 해 주세요."
        elif check_password_hash(ADMIN_HASH, request.form.get("pw", "")):
            _fail.pop(key, None)
            uid = session.get("uid"); session.clear()
            if uid: session["uid"] = uid
            session["adm"] = time.time()
            alog("login")
            return redirect("/admin")
        else:
            st[0] += 1
            if st[0] >= 5:
                st = [0, now + 15 * 60]; err = "5번 틀려서 15분 동안 잠겼어요."
            else:
                err = f"비밀번호가 맞지 않아요. ({st[0]}/5)"
            _fail[key] = st
            log.warning("admin login fail ip=%s", key)
    return render_template("admin.html", mode="login", err=err)


@bp.post("/admin/logout")
def admin_logout():
    session.pop("adm", None)
    return redirect("/admin/login")


PER = 20


@bp.route("/admin")
@admin_required
def admin():
    s = (request.args.get("q") or "").strip()
    page = max(1, request.args.get("p", 1, type=int))
    where, args = "", []
    if s:
        ph = norm_phone(s)
        if ph:
            where, args = "WHERE phone_h=?", [phone_hash(ph)]
        else:
            like = "%" + s.lower().lstrip("@").replace("%", "").replace("_", "\\_") + "%"
            where = "WHERE login_id LIKE ? ESCAPE '\\' OR nick_l LIKE ? ESCAPE '\\' OR tg LIKE ? ESCAPE '\\'"
            args = [like, like, like]
    total = q(f"SELECT COUNT(*) FROM members {where}", args, one=True)[0]
    rows = q(f"SELECT id,login_id,nick,name_e,phone_e,birth_e,tg,status,created_at,last_login FROM members {where} ORDER BY id DESC LIMIT {PER} OFFSET {(page - 1) * PER}", args)
    ms = []
    for r in rows:
        nm, ph, bd = dec(r[3]), dec(r[4]), dec(r[5])
        ms.append({"id": r[0], "login_id": r[1], "nick": r[2], "name": nm[0] + "*" * (len(nm) - 1),
                   "phone": mask_phone(ph) if ph[:1] == "0" else ph, "birth": bd[:4] + "-**-**",
                   "tg": r[6], "status": r[7], "created": r[8][:16], "last": (r[9] or "")[:16]})
    today = datetime.now(KST).strftime("%Y-%m-%d")
    stats = {"total": q("SELECT COUNT(*) FROM members", one=True)[0],
             "today": q("SELECT COUNT(*) FROM members WHERE created_at LIKE ?", (today + "%",), one=True)[0],
             "susp": q("SELECT COUNT(*) FROM members WHERE status='suspended'", one=True)[0]}
    pages = max(1, (total + PER - 1) // PER)
    return render_template("admin.html", mode="list", ms=ms, s=s, page=page, pages=pages, total=total, stats=stats,
                           storage=storage_desc())


@bp.post("/admin/reveal/<int:mid>")
@admin_required
def admin_reveal(mid):
    r = q("SELECT name_e,phone_e,birth_e FROM members WHERE id=?", (mid,), one=True)
    if not r:
        abort(404)
    alog("reveal", mid)
    p = dec(r[1])
    return {"name": dec(r[0]), "phone": fmt_phone(p) if p[:1] == "0" else p, "birth": dec(r[2])}


@bp.post("/admin/member/<int:mid>/<act>")
@admin_required
def admin_act(mid, act):
    if act in ("suspend", "unsuspend"):
        q("UPDATE members SET status=? WHERE id=?", ("suspended" if act == "suspend" else "active", mid), fetch=False)
    elif act == "delete":
        q("DELETE FROM members WHERE id=?", (mid,), fetch=False)
    else:
        abort(400)
    alog(act, mid)
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url + "admin") else "/admin")


@bp.post("/admin/export")
@admin_required
def admin_export():
    if not check_password_hash(ADMIN_HASH, request.form.get("pw", "")):
        flash("CSV 내보내기: 관리자 비밀번호를 다시 입력해 주세요.")
        return redirect("/admin")
    alog("export_csv")
    out = io.StringIO(); out.write("\ufeff")
    w = csv.writer(out)
    w.writerow(["번호", "아이디", "닉네임", "이름", "전화번호", "생년월일", "텔레그램", "상태", "가입일", "최근 로그인"])
    for r in q("SELECT id,login_id,nick,name_e,phone_e,birth_e,tg,status,created_at,last_login FROM members ORDER BY id"):
        p = dec(r[4])
        row = [r[0], r[1], r[2], dec(r[3]), fmt_phone(p) if p[:1] == "0" else p, dec(r[5]), r[6] or "", r[7], r[8], r[9] or ""]
        w.writerow(["'" + str(c) if str(c)[:1] in "=+-@" else c for c in row])
    fn = "twowin_members_" + datetime.now(KST).strftime("%Y%m%d_%H%M") + ".csv"
    return Response(out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={fn}"})


@bp.route("/admin/log")
@admin_required
def admin_logs():
    rows = q("SELECT ts,ip,action,target FROM admin_log ORDER BY id DESC LIMIT 200")
    return render_template("admin.html", mode="log", rows=rows)

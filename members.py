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
ADMIN_TTL = 2 * 60 * 60

_fernet = None
if ENC_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(ENC_KEY.encode())
    except Exception as e:  # 잘못된 키
        log.error("MEMBER_ENC_KEY invalid: %s", e)
_HKEY = hashlib.sha256(b"twowin-phone|" + ENC_KEY.encode()).digest()


_db_ok = [True]


def enabled():
    return _fernet is not None and _db_ok[0]


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
CREATE TABLE IF NOT EXISTS admin_log(id {pk}, ts TEXT NOT NULL, ip TEXT, action TEXT NOT NULL, target TEXT);
CREATE TABLE IF NOT EXISTS admins(id {pk}, username TEXT NOT NULL UNIQUE, pw TEXT NOT NULL, totp_e TEXT NOT NULL,
 last_step BIGINT NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS admin_backup(id {pk}, admin_id BIGINT NOT NULL, code_h TEXT NOT NULL, used_at TEXT)"""


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
    try:
        _init()
    except Exception:
        _db_ok[0] = False
        log.exception("member DB init failed: 회원 기능 비활성")


def _init():
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
    m = current()
    lv = promo = None
    if m:
        import levels
        lv = levels.info(m["id"])
        if lv and lv["i"] > lv["seen"] and request.method == "GET":
            promo = lv; levels.mark_seen(m["id"], lv["i"])
    return {"csrf_token": csrf_token, "me": m, "lv": lv, "lv_promo": promo}


@bp.before_app_request
def _lv_visit():
    if request.method != "GET" or request.path.startswith(("/static", "/api", "/admin")):
        return
    m = current()
    if m:
        d = datetime.now(KST).strftime("%Y-%m-%d")
        if session.get("lvd") != d:
            import levels
            levels.award(m["id"], "visit"); session["lvd"] = d


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


def parse_birth(s, today=None):
    """YYMMDD → date. YY > current 2-digit year → 19YY else 20YY. Invalid → None."""
    d = re.sub(r"\D", "", s or "")
    if not re.fullmatch(r"\d{6}", d):
        return None
    yy, mm, dd = int(d[:2]), int(d[2:4]), int(d[4:6])
    t = today or datetime.now(KST).date()
    century = 1900 if yy > (t.year % 100) else 2000
    try:
        b = date(century + yy, mm, dd)
    except ValueError:
        return None
    if b.year < 1900 or b > t:
        return None
    return b


def fmt_phone(d):
    return f"{d[:3]}-{d[3:-4]}-{d[-4:]}"


def mask_phone(d):
    return f"{d[:3]}-****-{d[-4:]}"


def now_s():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


# ---------- 휴대폰 인증 (Octomo MO: 회원이 1666-3538로 코드 문자 발송, 서버가 API로 확인) ----------
OCTOMO_KEY = os.environ.get("OCTOMO_API_KEY", "").strip()
OCTOMO_URL = "https://api.octoverse.kr/octomo/v1/public/message/exists"
OCTOMO_NUM = "16663538"
PV_TTL = 10 * 60


def pv_on():
    return bool(OCTOMO_KEY)


def _octomo_exists(phone, text):
    import json, urllib.request, urllib.error
    req = urllib.request.Request(OCTOMO_URL, method="POST",
        data=json.dumps({"mobileNum": phone, "text": text, "withinMinutes": 10}).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": "Octomo " + OCTOMO_KEY})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return bool(json.loads(r.read().decode() or "{}").get("exists")), None
    except urllib.error.HTTPError as e:
        log.warning("octomo http %s", e.code)
        return False, ("잠시 후 다시 시도해 주세요." if e.code == 429 else "인증 서버 오류예요. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        log.warning("octomo err %s", type(e).__name__)
        return False, "인증 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."


def _sms_qr(code):
    import qrcode, base64
    buf = io.BytesIO(); qrcode.make(f"SMSTO:{OCTOMO_NUM}:{code}", box_size=5, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@bp.route("/signup/phone/start", methods=["POST"])
def phone_start():
    if not (enabled() and pv_on()):
        return {"ok": False, "msg": "휴대폰 인증을 사용할 수 없어요."}, 400
    ph = norm_phone(request.form.get("phone"))
    if not ph or not ph.startswith("010") or len(ph) != 11:
        return {"ok": False, "msg": "010으로 시작하는 휴대폰 번호를 입력해 주세요."}, 400
    if limited("pvs|" + ip(), 5, 3600) or limited("pvs|" + phone_hash(ph), 5, 3600):
        return {"ok": False, "msg": "인증 요청이 너무 많아요. 1시간 뒤에 다시 해 주세요."}, 429
    if q("SELECT 1 FROM members WHERE phone_h=?", (phone_hash(ph),), one=True):
        return {"ok": False, "msg": "이미 가입된 휴대폰 번호예요."}, 400
    code = f"{secrets.randbelow(900000) + 100000}"
    session["pv"] = {"ph": ph, "code": code, "t": time.time(), "n": 0}
    session.pop("pv_ok", None)
    return {"ok": True, "code": code, "to": OCTOMO_NUM, "to_fmt": "1666-3538", "qr": _sms_qr(code),
            "sms": f"sms:{OCTOMO_NUM}?&body={code}", "ttl": PV_TTL}


@bp.route("/signup/phone/check", methods=["POST"])
def phone_check():
    pv = session.get("pv")
    if not (enabled() and pv_on()) or not pv:
        return {"ok": False, "msg": "먼저 인증 요청을 해 주세요."}, 400
    if time.time() - pv["t"] > PV_TTL:
        session.pop("pv", None)
        return {"ok": False, "msg": "인증 시간이 지났어요. 다시 요청해 주세요."}, 400
    if pv.get("n", 0) >= 20 or limited("pvc|" + ip(), 30, 600):
        return {"ok": False, "msg": "확인 시도가 너무 많아요. 잠시 후 다시 해 주세요."}, 429
    pv["n"] = pv.get("n", 0) + 1; session["pv"] = pv
    ok, err = _octomo_exists(pv["ph"], pv["code"])
    if err:
        return {"ok": False, "msg": err}, 502
    if not ok:
        return {"ok": False, "msg": "아직 문자가 확인되지 않았어요. 입력한 번호의 휴대폰으로 코드만 정확히 보내 주세요."}
    session["pv_ok"] = {"ph": pv["ph"], "t": time.time()}
    session.pop("pv", None)
    return {"ok": True, "msg": "휴대폰 인증이 완료됐어요."}


def ph_ok(p):
    ph = norm_phone(p)
    return pv_on() and ph and _pv_verified(ph)


def _pv_verified(ph):
    v = session.get("pv_ok")
    return bool(v and v.get("ph") == ph and time.time() - v.get("t", 0) < 30 * 60)


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
            if len(pw) < 4 or len(pw) > 64 or not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
                errs.append("비밀번호는 영문과 숫자를 섞어 4자 이상으로 해 주세요.")
            elif pw != pw2: errs.append("비밀번호 확인이 일치하지 않아요.")
            ne = chat.check_nick(f["nick"])
            if ne: errs.append(ne if f["nick"] else "닉네임을 입력해 주세요.")
            if not (1 <= len(f["name"]) <= 30) or re.search(r"[<>\d]", f["name"]): errs.append("이름을 정확히 입력해 주세요.")
            ph = norm_phone(f["phone"])
            if not ph: errs.append("휴대폰 번호 형식이 올바르지 않아요. (예: 010-1234-5678)")
            elif pv_on() and not _pv_verified(ph): errs.append("휴대폰 인증을 완료해 주세요. (인증한 번호와 입력한 번호가 같아야 해요)")
            b = parse_birth(f["birth"])
            if not b:
                errs.append("생년월일을 6자리로 입력해 주세요. (예: 940531)")
            elif age(b) < 14:
                errs.append("만 14세 미만은 가입할 수 없어요.")
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
    ph_disp = norm_phone(f.get("phone"))
    if ph_disp:
        f["phone"] = fmt_phone(ph_disp)
    return render_template("member.html", page="signup", mode="signup", f=f, errs=errs, pv=pv_on(), pv_done=bool(ph_ok(f["phone"])))


_DUMMY_PW = generate_password_hash("dummy-" + os.urandom(8).hex())


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not enabled():
        return render_template("member.html", page="login", mode="off")
    if current():
        return redirect("/me")
    errs, lid = [], (request.form.get("login_id") or "").strip().lower()
    nxt = request.values.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or any(ord(c) < 32 for c in nxt): nxt = "/"
    if request.method == "POST":
        if limited("li|" + ip(), 10, 600) or limited("lid|" + lid, 8, 900):
            errs.append("로그인 시도가 너무 많아요. 잠시 뒤에 다시 해 주세요.")
        else:
            r = q("SELECT id, pw, status FROM members WHERE login_id=?", (lid,), one=True)
            ok_pw = check_password_hash(r[1] if r else _DUMMY_PW, request.form.get("pw", ""))  # 없는 아이디도 같은 시간 소요
            if not r or not ok_pw:
                errs.append("아이디 또는 비밀번호가 올바르지 않습니다")
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


# ---------- 관리자 (아이디 + 비밀번호 + Google OTP) ----------
import base64
_fail, _flock = {}, threading.Lock()
_pend, _plock = {}, threading.Lock()   # 설정 진행 중 상태(서버 메모리, 15분)
_otplock = threading.Lock()
ISSUER = "TwowinSCORE Admin"
ADM_RE = re.compile(r"^[a-z0-9_]{4,20}$")


def admin_exists():
    return q("SELECT COUNT(*) FROM admins", one=True)[0] > 0


def _bk_hash(c):
    return hmac.new(_HKEY, b"adm-bk|" + c.encode(), hashlib.sha256).hexdigest()


def _norm_bk(c):
    return re.sub(r"[^A-Z0-9]", "", (c or "").upper())


def _new_backups():
    al = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ["".join(secrets.choice(al) for _ in range(5)) + "-" + "".join(secrets.choice(al) for _ in range(5)) for _ in range(10)]


def _save_backups(aid, codes):
    q("DELETE FROM admin_backup WHERE admin_id=?", (aid,), fetch=False)
    for c in codes:
        q("INSERT INTO admin_backup(admin_id,code_h) VALUES(?,?)", (aid, _bk_hash(_norm_bk(c))), fetch=False)


def _qr(secret, user):
    import pyotp, qrcode
    uri = pyotp.TOTP(secret).provisioning_uri(name=user, issuer_name=ISSUER)
    buf = io.BytesIO(); qrcode.make(uri, box_size=6, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _totp_step(secret, code, last=0):
    """유효한 코드면 해당 30초 구간 번호, 아니면 None. ±1 구간, last 이하(재사용) 거부."""
    import pyotp
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        return None
    t, now = pyotp.TOTP(secret), int(time.time()) // 30
    for s in (now - 1, now, now + 1):
        if s > (last or 0) and hmac.compare_digest(t.at(s * 30), code):
            return s
    return None


def _use_totp(aid, code):
    with _otplock:
        r = q("SELECT totp_e, last_step FROM admins WHERE id=?", (aid,), one=True)
        if not r:
            return False
        s = _totp_step(dec(r[0]), code, r[1])
        if s is None:
            return False
        q("UPDATE admins SET last_step=? WHERE id=?", (s, aid), fetch=False)
        return True


def _use_backup(aid, code):
    c = _norm_bk(code)
    if len(c) != 10:
        return False
    with _otplock:
        r = q("SELECT id FROM admin_backup WHERE admin_id=? AND code_h=? AND used_at IS NULL", (aid, _bk_hash(c)), one=True)
        if not r:
            return False
        q("UPDATE admin_backup SET used_at=? WHERE id=?", (now_s(), r[0]), fetch=False)
        return True


def _locked(keys):
    now = time.time()
    with _flock:
        for k in keys:
            st = _fail.get(k)
            if st and st[1] > now:
                return int((st[1] - now) // 60) + 1
    return 0


def _fail_hit(keys):
    """실패 1회 기록. 잠기면 True."""
    now, lk = time.time(), False
    with _flock:
        for k in keys:
            st = _fail.get(k) or [0, 0, now]
            if now - st[2] > 15 * 60: st = [0, 0, now]
            st[0] += 1
            if st[0] >= 5: st = [0, now + 15 * 60, now]; lk = True
            _fail[k] = st
    return lk


def _fail_clear(keys):
    with _flock:
        for k in keys: _fail.pop(k, None)


def _admin_ok():
    t, aid = session.get("adm"), session.get("adm_id")
    if not t or not aid or time.time() - t > ADMIN_TTL:
        session.pop("adm", None); session.pop("adm_id", None)
        return False
    r = q("SELECT username, pw FROM admins WHERE id=?", (aid,), one=True)
    if not r:
        session.pop("adm", None); session.pop("adm_id", None)
        return False
    g.admin = {"id": aid, "username": r[0], "pw": r[1]}
    session["adm"] = time.time()
    return True


def _off():
    return render_template("admin.html", mode="off", enc=enabled(), pw=bool(ADMIN_HASH)), 503


def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not enabled():
            return _off()
        if not admin_exists():
            return redirect("/admin/setup")
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


def _pget(name):
    tok = session.get(name)
    with _plock:
        now = time.time()
        for k in [k for k, v in _pend.items() if now - v["t"] > 15 * 60]:
            _pend.pop(k, None)
        return tok, _pend.get(tok) if tok else None


def _pset(name, data):
    tok = secrets.token_urlsafe(24); data["t"] = time.time()
    with _plock: _pend[tok] = data
    session[name] = tok


def _pdel(name):
    tok = session.pop(name, None)
    with _plock: _pend.pop(tok, None)


def strong_pw(pw):
    return 12 <= len(pw) <= 128 and sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")) >= 3


@bp.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    if not enabled():
        return _off()
    if admin_exists():
        _pdel("su_tok"); abort(404)
    if not ADMIN_HASH:
        return _off()
    key = "ip|" + ip()
    tok, p = _pget("su_tok")
    errs, f = [], {"username": (request.form.get("username") or "").strip().lower()}
    m = _locked([key])
    if m:
        return render_template("admin.html", mode="setup1", errs=[f"실패가 많아 {m}분 동안 잠겼어요."], f=f)
    if request.method == "POST" and request.form.get("step") == "1":
        if limited("adms|" + ip(), 20, 600):
            errs.append("시도가 너무 많아요. 잠시 뒤에 다시 해 주세요.")
        elif not check_password_hash(ADMIN_HASH, request.form.get("boot", "")):
            errs.append("초기 설정 비밀번호(ADMIN_PASSWORD)가 맞지 않아요.")
            if _fail_hit([key]): errs.append("5번 틀려서 15분 동안 잠겼어요.")
            log.warning("admin setup bootstrap fail ip=%s", ip())
        else:
            _fail_clear([key])
            pw = request.form.get("pw", "")
            if not ADM_RE.match(f["username"]): errs.append("관리자 아이디는 영문 소문자·숫자·_ 4~20자로 해 주세요.")
            if not strong_pw(pw): errs.append("비밀번호는 12자 이상, 대문자·소문자·숫자·특수문자 중 3종류 이상으로 해 주세요.")
            elif pw != request.form.get("pw2", ""): errs.append("비밀번호 확인이 일치하지 않아요.")
            elif check_password_hash(ADMIN_HASH, pw): errs.append("초기 설정 비밀번호와 다른 비밀번호를 써 주세요.")
            if not errs:
                import pyotp
                _pdel("su_tok")
                _pset("su_tok", {"u": f["username"], "pw": generate_password_hash(pw), "sec": pyotp.random_base32()})
                return redirect("/admin/setup")
        return render_template("admin.html", mode="setup1", errs=errs, f=f)
    if p and request.method == "POST" and request.form.get("step") == "2":
        if limited("adms2|" + ip(), 20, 600):
            errs.append("시도가 너무 많아요. 잠시 뒤에 다시 해 주세요.")
        elif _totp_step(p["sec"], request.form.get("code")) is None:
            errs.append("OTP 코드가 맞지 않아요. 휴대폰 시간이 맞는지 확인하고 새 코드를 넣어 주세요.")
        else:
            codes = _new_backups()
            with _otplock:
                if admin_exists():
                    _pdel("su_tok"); abort(404)
                s = _totp_step(p["sec"], request.form.get("code"))
                q("INSERT INTO admins(username,pw,totp_e,last_step,created_at) VALUES(?,?,?,?,?)",
                  (p["u"], p["pw"], enc(p["sec"]), s, now_s()), fetch=False)
            aid = q("SELECT id FROM admins WHERE username=?", (p["u"],), one=True)[0]
            _save_backups(aid, codes)
            _pdel("su_tok")
            alog("setup", p["u"])
            return render_template("admin.html", mode="codes", codes=codes, after="setup")
    if p:
        return render_template("admin.html", mode="setup2", errs=errs, qr=_qr(p["sec"], p["u"]), sec=p["sec"], u=p["u"], action="/admin/setup")
    return render_template("admin.html", mode="setup1", errs=errs, f=f)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not enabled():
        return _off()
    if not admin_exists():
        return redirect("/admin/setup")
    if request.args.get("restart"):
        session.pop("adm_pre", None)
    pre = session.get("adm_pre")
    if pre and time.time() - pre["t"] > 5 * 60:
        session.pop("adm_pre", None); pre = None
    u = (request.form.get("username") or (pre or {}).get("u") or "").strip().lower()
    keys = ["ip|" + ip(), "u|" + u] if u else ["ip|" + ip()]
    err = ""
    m = _locked(keys)
    stage = "otp" if pre else "pw"
    if m:
        err = f"로그인 실패가 많아 {m}분 동안 잠겼어요."
    elif request.method == "POST":
        if limited("adm|" + ip(), 20, 600) or limited("adm|all", 60, 600):
            err = "시도가 너무 많아요. 잠시 뒤에 다시 해 주세요."
        elif not pre:
            r = q("SELECT id, pw FROM admins WHERE username=?", (u,), one=True)
            if check_password_hash(r[1] if r else _DUMMY_PW, request.form.get("pw", "")) and r:
                session["adm_pre"] = {"id": r[0], "u": u, "t": time.time()}
                return redirect("/admin/login")
            if not r: check_password_hash(ADMIN_HASH or generate_password_hash("x"), "dummy")
            err = "5번 틀려서 15분 동안 잠겼어요." if _fail_hit(keys) else "아이디 또는 비밀번호가 올바르지 않습니다"
            alog("login_fail", u[:30]); log.warning("admin login fail ip=%s", ip())
        else:
            code = request.form.get("code", "")
            how = "otp" if _use_totp(pre["id"], code) else ("backup" if _use_backup(pre["id"], code) else "")
            if how:
                _fail_clear(keys)
                uid = session.get("uid"); session.clear()
                if uid: session["uid"] = uid
                session["adm"] = time.time(); session["adm_id"] = pre["id"]
                q("UPDATE admins SET last_login=? WHERE id=?", (now_s(), pre["id"]), fetch=False)
                alog("login" if how == "otp" else "login_backup_code", pre["u"])
                return redirect("/admin")
            lk = _fail_hit(keys)
            alog("login_otp_fail", pre["u"])
            if lk:
                session.pop("adm_pre", None); stage = "pw"; err = "5번 틀려서 15분 동안 잠겼어요."
            else:
                err = "OTP 코드가 맞지 않아요. (이미 쓴 코드는 다시 쓸 수 없어요)"
    left = None
    if stage == "otp":
        left = q("SELECT COUNT(*) FROM admin_backup WHERE admin_id=? AND used_at IS NULL", (pre["id"],), one=True)[0]
    return render_template("admin.html", mode="login", stage=stage, err=err, u=u, left=left)


@bp.post("/admin/logout")
def admin_logout():
    if session.get("adm_id"): 
        try: alog("logout")
        except Exception: pass
    session.pop("adm", None); session.pop("adm_id", None); session.pop("adm_pre", None)
    return redirect("/admin/login")


@bp.route("/admin/otp", methods=["GET", "POST"])
@admin_required
def admin_otp():
    a, errs = g.admin, []
    tok, p = _pget("otp_tok")
    if p and p.get("aid") != a["id"]:
        _pdel("otp_tok"); p = None
    if request.method == "POST" and request.form.get("step") == "1":
        if limited("admo|" + str(a["id"]), 5, 900):
            errs.append("시도가 너무 많아요. 15분 뒤에 다시 해 주세요.")
        elif not check_password_hash(a["pw"], request.form.get("pw", "")) or not _use_totp(a["id"], request.form.get("code", "")):
            errs.append("현재 비밀번호 또는 현재 OTP 코드가 맞지 않아요.")
            alog("otp_reset_fail", a["username"])
        else:
            import pyotp
            _pdel("otp_tok"); _pset("otp_tok", {"aid": a["id"], "sec": pyotp.random_base32()})
            return redirect("/admin/otp")
        return render_template("admin.html", mode="otp1", sec="otp", errs=errs)
    if p and request.method == "POST" and request.form.get("step") == "2":
        s = _totp_step(p["sec"], request.form.get("code"))
        if s is None or limited("admo2|" + str(a["id"]), 10, 600):
            errs.append("새 OTP 코드가 맞지 않아요. 새로 등록한 항목의 코드를 넣어 주세요.")
        else:
            with _otplock:
                q("UPDATE admins SET totp_e=?, last_step=? WHERE id=?", (enc(p["sec"]), s, a["id"]), fetch=False)
            codes = _new_backups(); _save_backups(a["id"], codes)
            _pdel("otp_tok"); alog("otp_reset", a["username"])
            return render_template("admin.html", mode="codes", codes=codes, after="reset")
    if p:
        return render_template("admin.html", mode="setup2", errs=errs, qr=_qr(p["sec"], a["username"]), sec=p["sec"], u=a["username"], action="/admin/otp", reset=True)
    return render_template("admin.html", mode="otp1", sec="otp", errs=errs)


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
    import levels
    tier = request.args.get("t", type=int)
    if tier is not None and not 0 <= tier < len(levels.TIERS):
        tier = None
    sort = "pts" if request.args.get("sort") == "pts" else "id"
    jn = "LEFT JOIN member_lv l ON l.member_id=members.id" if levels._ok[0] else ""
    pe = "COALESCE(l.pts,0)" if jn else "0"
    if tier is not None:
        lo, hi = levels.TIERS[tier][1], (levels.TIERS[tier + 1][1] if tier + 1 < len(levels.TIERS) else None)
        cond = f"{pe}>=?" + (f" AND {pe}<?" if hi is not None else "")
        where = (f"WHERE ({where[6:]}) AND " if where else "WHERE ") + cond
        args = args + [lo] + ([hi] if hi is not None else [])
    tcounts = [0] * len(levels.TIERS)
    if jn:
        for pts_, n_ in q(f"SELECT {pe}, COUNT(*) FROM members {jn} GROUP BY {pe}"):
            tcounts[levels.tier_of(int(pts_))] += int(n_)
    else:
        tcounts[0] = q("SELECT COUNT(*) FROM members", one=True)[0]
    order = f"{pe} DESC, members.id DESC" if sort == "pts" else "members.id DESC"
    total = q(f"SELECT COUNT(*) FROM members {jn} {where}", args, one=True)[0]
    rows = q(f"SELECT members.id,login_id,nick,name_e,phone_e,birth_e,tg,status,created_at,last_login FROM members {jn} {where} ORDER BY {order} LIMIT {PER} OFFSET {(page - 1) * PER}", args)
    ms = []
    lvp = levels.many([r[0] for r in rows])
    for r in rows:
        nm, ph, bd = dec(r[3]), dec(r[4]), dec(r[5])
        ms.append({"id": r[0], "login_id": r[1], "nick": r[2], "name": nm[0] + "*" * (len(nm) - 1),
                   "phone": mask_phone(ph) if ph[:1] == "0" else ph, "birth": bd[:4] + "-**-**",
                   "tg": r[6], "status": r[7], "created": r[8][:16], "last": (r[9] or "")[:16],
                   "pts": lvp.get(r[0], 0), "tier": levels.TIERS[levels.tier_of(lvp.get(r[0], 0))], "ti": levels.tier_of(lvp.get(r[0], 0))})
    today = datetime.now(KST).strftime("%Y-%m-%d")
    stats = {"total": q("SELECT COUNT(*) FROM members", one=True)[0],
             "today": q("SELECT COUNT(*) FROM members WHERE created_at LIKE ?", (today + "%",), one=True)[0],
             "susp": q("SELECT COUNT(*) FROM members WHERE status='suspended'", one=True)[0]}
    pages = max(1, (total + PER - 1) // PER)
    import admin_ext
    mc = admin_ext.memo_counts([m["id"] for m in ms])
    for m in ms:
        m["memos"] = mc.get(m["id"], 0)
    return render_template("admin.html", mode="list", sec="members", ms=ms, s=s, page=page, pages=pages, total=total, stats=stats, tier=tier, sort=sort, tcounts=tcounts, tiers=levels.TIERS,
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


@bp.post("/admin/member/<int:mid>/points")
@admin_required
def admin_points(mid):
    import levels
    try:
        d = int(request.form.get("delta", "0"))
    except ValueError:
        d = 0
    if d and -100000 <= d <= 100000 and q("SELECT 1 FROM members WHERE id=?", (mid,), one=True):
        new = levels.admin_set(mid, d)
        alog("points %+d -> %d" % (d, new), mid)
        flash(f"#{mid} 점수 {d:+d} → {new}점")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url + "admin") else "/admin")


@bp.post("/admin/export")
@admin_required
def admin_export():
    if not check_password_hash(g.admin["pw"], request.form.get("pw", "")):
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
    return render_template("admin.html", mode="log", sec="log", rows=rows)

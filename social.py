"""회원검색 · 친구 · 접속 상태 · 1:1 대화 (친구끼리만) · 차단/신고 · 관리자 모니터링."""
import re, time, hmac, logging, threading, unicodedata
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, render_template, redirect, abort, flash
import members as M
from members import q, admin_required, KST


def alog(action, target=""):
    a = (M.g.get("admin") or {}).get("username", "?")
    M.alog(f"[{a}] " + action, target)

log = logging.getLogger("social")
bp = Blueprint("social", __name__)
_ok = [False]
MAX_FRIENDS = 200
MAX_LEN = 300
ONLINE_SEC = 120
NOTICE = "운영 정책 위반 방지를 위해 1:1 대화는 관리자가 확인할 수 있습니다."
BLOCK_MSG = "연락처·메신저 아이디 공유는 할 수 없어요"
GENERIC = "요청을 처리할 수 없어요."

SCHEMA = """CREATE TABLE IF NOT EXISTS friend(a BIGINT NOT NULL, b BIGINT NOT NULL, status TEXT NOT NULL, req_by BIGINT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY(a,b));
CREATE INDEX IF NOT EXISTS friend_b ON friend(b);
CREATE TABLE IF NOT EXISTS mblock(member_id BIGINT NOT NULL, target BIGINT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY(member_id,target));
CREATE TABLE IF NOT EXISTS dm_msg(id {pk}, a BIGINT NOT NULL, b BIGINT NOT NULL, sender BIGINT NOT NULL, body TEXT NOT NULL, ts BIGINT NOT NULL, sus TEXT, hidden INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS dm_msg_ab ON dm_msg(a,b,id);
CREATE TABLE IF NOT EXISTS dm_read(member_id BIGINT NOT NULL, peer BIGINT NOT NULL, last_id BIGINT NOT NULL, PRIMARY KEY(member_id,peer));
CREATE TABLE IF NOT EXISTS dm_report(id {pk}, ts TEXT NOT NULL, reporter BIGINT NOT NULL, msg_id BIGINT NOT NULL, a BIGINT NOT NULL, b BIGINT NOT NULL, reason TEXT, status TEXT NOT NULL DEFAULT 'open');
CREATE TABLE IF NOT EXISTS notif(id {pk}, member_id BIGINT NOT NULL, kind TEXT NOT NULL, actor BIGINT, body TEXT, ts BIGINT NOT NULL, rd INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS notif_mid ON notif(member_id,id);
CREATE TABLE IF NOT EXISTS dm_blocked(id {pk}, ts TEXT NOT NULL, member_id BIGINT NOT NULL, peer BIGINT NOT NULL, body TEXT NOT NULL, reason TEXT)"""


def init_db():
    if not M.enabled():
        return
    try:
        pk = "BIGSERIAL PRIMARY KEY" if M.PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for s in SCHEMA.format(pk=pk).split(";"):
            q(s, fetch=False)
        for a in ("ALTER TABLE members ADD COLUMN hide_online INTEGER NOT NULL DEFAULT 0",
                  "ALTER TABLE members ADD COLUMN dm_until TEXT"):
            try:
                q(a, fetch=False)
            except Exception:
                pass
        _ok[0] = True
    except Exception:
        log.exception("social init failed")


# ---------- 필터 ----------
_DIG = {"공": "0", "영": "0", "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5", "육": "6", "륙": "6", "칠": "7", "팔": "8", "구": "9",
        "하나": "1", "둘": "2", "셋": "3", "넷": "4", "o": "0", "O": "0", "l": "1", "I": "1"}
_CIRC = {chr(0x2460 + i): str(i + 1) for i in range(9)}
MSGR = ["카톡", "카카오", "kakao", "katalk", "카톡아이디", "톡아이디", "텔레", "텔그", "텔레그램", "telegram", "tele", "라인아이디", "라인id", "lineid",
        "line아이디", "인스타", "insta", "instagram", "오픈채팅", "오픈톡", "openkakao", "open.kakao", "위챗", "wechat", "디스코드", "discord", "왓츠앱", "whatsapp",
        "스냅챗", "페북", "facebook", "dm주", "디엠주", "연락처", "전화번호", "폰번호", "핸드폰번호", "번호줘", "번호좀", "번호알려", "아이디줘", "아이디알려", "아디줘"]
SUSW = ["톡", "텔", "라인", "아이디", "아디", "번호", "연락", "오픈채팅", "카카", "인스타", "디엠", "dm", "메일", "주소", "만나", "입금", "계좌", "배당"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+\s*(@|골뱅이|\(at\)|\[at\])\s*[A-Za-z0-9.\-]+\s*(\.|닷|dot)\s*[A-Za-z]{2,}", re.I)
JAMO_RE = re.compile(r"[ㄱ-ㅊㅌㅍ]{2,}")


def _sq(t):
    return re.sub(r"[\s\.\,\-_~!\?\*\^'\"`|/\\()\[\]{}<>:;+=#$%&·•…ㆍ]+", "", t)


def _digits(t):
    s = "".join(_CIRC.get(c, c) for c in t)
    for k, v in sorted(_DIG.items(), key=lambda x: -len(x[0])):
        s = s.replace(k, v)
    return s


def check_dm(text):
    """(block_reason or None, suspicious_flags str)."""
    import chat
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", t)
    sq = _sq(t)
    flags = []
    if EMAIL_RE.search(t) or re.search(r"@\s*[a-z0-9_]{2,}", t):
        return BLOCK_MSG, "email/@"
    if chat.URL_RE.search(t) or chat.URL_RE.search(sq.replace("닷", ".")) or "t.me" in sq or "openkakao" in sq or "http" in sq:
        return BLOCK_MSG, "url"
    if any(w in sq for w in MSGR):
        return BLOCK_MSG, "messenger"
    d = re.sub(r"[^0-9]", "", _digits(sq))
    runs = re.findall(r"\d+", _digits(sq))
    if any(len(r) >= 7 for r in runs) or len(re.sub(r"[^0-9]", "", sq)) >= 7 or re.search(r"01[016789]\d{3,}", "".join(runs)) or re.search(r"(공|영|0)\s*(일|1)\s*(공|영|0)", t):
        return BLOCK_MSG, "phone"
    bad = chat.check_text(text)
    if bad:
        return ("링크·연락처·메신저 아이디 공유는 할 수 없어요" if ("전화" in bad or "링크" in bad or "@" in bad) else bad), "filter"
    if any(len(r) >= 4 for r in runs) or re.search(r"\d(\s+\d){3,}", t):
        flags.append("숫자")
    if re.search(r"[0-9공영일이삼사오육칠팔구]{1}(\s|[.\-])[0-9공영일이삼사오육칠팔구]", t) and len(d) >= 4:
        flags.append("띄운숫자")
    for w in SUSW:
        if w in sq:
            flags.append(w)
    if JAMO_RE.search(text):
        flags.append("초성")
    return None, ",".join(dict.fromkeys(flags))[:120]


# ---------- 공통 ----------
_seen, _sl = {}, threading.Lock()


def touch(mid):
    with _sl:
        _seen[mid] = time.time()


def online(mid):
    return time.time() - _seen.get(mid, 0) < ONLINE_SEC


def _me():
    m = M.current()
    if not m or not _ok[0]:
        abort(401)
    touch(m["id"])
    return m


def _csrf():
    t = request.headers.get("X-CSRF", "")
    if not t or not hmac.compare_digest(t, session.get("_csrf", "")):
        abort(400)


def _pair(x, y):
    return (x, y) if x < y else (y, x)


def _member(mid=None, nick=None):
    if mid:
        r = q("SELECT id,nick,status,hide_online FROM members WHERE id=?", (int(mid),), one=True)
    else:
        r = q("SELECT id,nick,status,hide_online FROM members WHERE nick_l=?", ((nick or "").lower(),), one=True)
    return r if r and r[2] == "active" else None


def _cards(rows):
    """rows: [(id,nick,hide_online)] -> 공개 카드 (닉네임·등급·VIP만)."""
    if not rows:
        return []
    import levels, vip
    ids = [r[0] for r in rows]
    lp, vp = levels.many(ids), vip.many(ids)
    out = []
    for r in rows:
        i = levels.tier_of(lp.get(r[0], 0))
        out.append({"id": r[0], "nick": r[1], "lv": [levels.TIERS[i][0], levels.TIERS[i][2], i], "vip": 1 if vp.get(r[0], {}).get("vip") else 0})
    return out


def _rel(me, other):
    a, b = _pair(me, other)
    r = q("SELECT status,req_by FROM friend WHERE a=? AND b=?", (a, b), one=True)
    if not r:
        return "none"
    if r[0] == "ok":
        return "friend"
    return "sent" if r[1] == me else "recv"


def _blocked(x, y):
    return q("SELECT 1 FROM mblock WHERE (member_id=? AND target=?) OR (member_id=? AND target=?)", (x, y, y, x), one=True) is not None


def _dm_banned(mid):
    r = q("SELECT dm_until FROM members WHERE id=?", (mid,), one=True)
    u = r and r[0]
    if not u:
        return None
    if u == "perm" or u > M.now_s():
        return u
    return None


def notify(mid, kind, actor, body=""):
    try:
        if kind == "dm":
            q("DELETE FROM notif WHERE member_id=? AND kind='dm' AND actor=? AND rd=0", (mid, actor), fetch=False)
        q("INSERT INTO notif(member_id,kind,actor,body,ts) VALUES(?,?,?,?,?)", (mid, kind, actor, (body or "")[:80], int(time.time())), fetch=False)
        if q("SELECT COUNT(*) FROM notif WHERE member_id=?", (mid,), one=True)[0] > 300:
            q("DELETE FROM notif WHERE member_id=? AND id < (SELECT MIN(id) FROM (SELECT id FROM notif WHERE member_id=? ORDER BY id DESC LIMIT 200) t)", (mid, mid), fetch=False)
    except Exception:
        log.exception("notify")


def _notifs(me, after=0, limit=30):
    rows = q("SELECT id,kind,actor,body,ts,rd FROM notif WHERE member_id=? AND id>? ORDER BY id DESC LIMIT ?", (me, after, limit))
    nk = {}
    ids = list({r[2] for r in rows if r[2]})
    if ids:
        ph = ",".join("?" * len(ids))
        nk = {r[0]: r[1] for r in q(f"SELECT id,nick FROM members WHERE id IN ({ph})", ids)}
    return [{"id": r[0], "k": r[1], "a": r[2], "n": nk.get(r[2], "회원"), "b": r[3] or "", "ts": r[4], "rd": r[5]} for r in rows]


@bp.get("/api/social/notifs")
def notifs():
    m = _me()
    return jsonify({"ok": True, "items": _notifs(m["id"], 0, 50)})


@bp.post("/api/social/notifs/read")
def notifs_read():
    m = _me(); _csrf()
    i = (request.get_json(silent=True) or {}).get("id")
    if i:
        q("UPDATE notif SET rd=1 WHERE member_id=? AND id=?", (m["id"], int(i)), fetch=False)
    else:
        q("UPDATE notif SET rd=1 WHERE member_id=?", (m["id"],), fetch=False)
    return jsonify({"ok": True})


# ---------- 페이지 ----------
@bp.route("/friends")
def page():
    m = M.current()
    if not m:
        return redirect("/login?next=/friends")
    touch(m["id"])
    hide = q("SELECT hide_online FROM members WHERE id=?", (m["id"],), one=True)
    return render_template("social.html", notice=NOTICE, hide=int(hide[0] or 0) if hide else 0,
                           tab=request.args.get("t", "friends"), peer=request.args.get("peer", type=int) or 0)


# ---------- API ----------
@bp.get("/api/social/badge")
def badge():
    m = M.current()
    if not m or not _ok[0]:
        return jsonify({"ok": False})
    touch(m["id"])
    me = m["id"]
    u = q("""SELECT COUNT(*) FROM dm_msg d LEFT JOIN dm_read r ON r.member_id=? AND r.peer=d.sender
             WHERE (d.a=? OR d.b=?) AND d.sender<>? AND d.hidden=0 AND d.id>COALESCE(r.last_id,0)""", (me, me, me, me), one=True)[0]
    rq = q("SELECT COUNT(*) FROM friend WHERE (a=? OR b=?) AND status='pending' AND req_by<>?", (me, me, me), one=True)[0]
    nu = q("SELECT COUNT(*) FROM notif WHERE member_id=? AND rd=0", (me,), one=True)[0]
    after = request.args.get("after", type=int)
    new = _notifs(me, after, 5) if after is not None else []
    top = q("SELECT MAX(id) FROM notif WHERE member_id=?", (me,), one=True)[0] or 0
    return jsonify({"ok": True, "dm": int(u), "req": int(rq), "noti": int(nu), "new": [x for x in new if not x["rd"]], "top": int(top)})


@bp.get("/api/social/search")
def search():
    m = _me()
    s = re.sub(r"[^0-9A-Za-z가-힣_]", "", request.args.get("q", ""))[:12]
    if len(s) < 1:
        return jsonify({"ok": True, "items": []})
    if M.limited("ss:" + str(m["id"]), 20, 60) or M.limited("ssip:" + M.ip(), 40, 60):
        return jsonify({"ok": False, "error": "잠시 후 다시 검색해 주세요."}), 429
    rows = q("SELECT id,nick,hide_online FROM members WHERE status='active' AND nick_l LIKE ? AND id<>? ORDER BY LENGTH(nick), nick LIMIT 20",
             ("%" + s.lower() + "%", m["id"]))
    items = _cards(rows)
    for it in items:
        it["rel"] = _rel(m["id"], it["id"])
    return jsonify({"ok": True, "items": items})


@bp.get("/api/social/profile")
def profile():
    m = M.current()
    r = _member(nick=request.args.get("nick", "")[:12])
    if not r:
        return jsonify({"ok": False, "error": "회원 정보를 찾을 수 없어요."}), 404
    c = _cards([(r[0], r[1], r[3])])[0]
    c["rel"] = "self" if m and m["id"] == r[0] else (_rel(m["id"], r[0]) if m else "guest")
    return jsonify({"ok": True, "p": c})


@bp.get("/api/social/friends")
def friends():
    m = _me(); me = m["id"]
    rows = q("SELECT a,b,status,req_by FROM friend WHERE a=? OR b=?", (me, me))
    other = {(r[1] if r[0] == me else r[0]): (r[2], r[3]) for r in rows}
    blk = [r[0] for r in q("SELECT target FROM mblock WHERE member_id=?", (me,))]
    ids = list(set(other) | set(blk))
    info = {}
    if ids:
        ph = ",".join("?" * len(ids))
        for c in _cards(q(f"SELECT id,nick,hide_online FROM members WHERE id IN ({ph}) AND status='active'", ids)):
            info[c["id"]] = c
        hid = {r[0]: r[1] for r in q(f"SELECT id,hide_online FROM members WHERE id IN ({ph})", ids)}
    out = {"friends": [], "recv": [], "sent": [], "blocked": []}
    for oid, (st, by) in other.items():
        c = info.get(oid)
        if not c:
            continue
        c = dict(c)
        if st == "ok":
            c["on"] = 1 if (online(oid) and not hid.get(oid)) else 0
            out["friends"].append(c)
        else:
            out["recv" if by != me else "sent"].append(c)
    out["blocked"] = [info[i] for i in blk if i in info]
    out["friends"].sort(key=lambda c: (-c["on"], c["nick"]))
    return jsonify({"ok": True, **out, "max": MAX_FRIENDS})


@bp.post("/api/social/friend")
def friend_act():
    m = _me(); _csrf(); me = m["id"]
    b = request.get_json(silent=True) or {}
    act = b.get("act")
    o = _member(mid=b.get("id")) if b.get("id") else _member(nick=str(b.get("nick") or "")[:12])
    if not o or o[0] == me or act not in ("req", "accept", "decline", "cancel", "remove"):
        return jsonify({"ok": False, "error": GENERIC}), 400
    oid = o[0]; a, bb = _pair(me, oid)
    rel = _rel(me, oid)
    if act == "req":
        if M.limited("fr:" + str(me), 20, 3600):
            return jsonify({"ok": False, "error": "친구 요청이 너무 많아요. 잠시 후 다시 해 주세요."}), 429
        if _blocked(me, oid):
            return jsonify({"ok": False, "error": GENERIC}), 400
        if rel == "friend":
            return jsonify({"ok": True, "rel": rel})
        if rel == "recv":
            act = "accept"
        elif rel == "sent":
            return jsonify({"ok": True, "rel": rel})
        else:
            n = q("SELECT COUNT(*) FROM friend WHERE (a=? OR b=?) AND status='ok'", (me, me), one=True)[0]
            if n >= MAX_FRIENDS:
                return jsonify({"ok": False, "error": f"친구는 {MAX_FRIENDS}명까지예요."}), 400
            pend = q("SELECT COUNT(*) FROM friend WHERE req_by=? AND status='pending'", (me,), one=True)[0]
            if pend >= 50:
                return jsonify({"ok": False, "error": "보낸 요청이 너무 많아요. 기존 요청을 정리해 주세요."}), 400
            try:
                q("INSERT INTO friend(a,b,status,req_by,ts) VALUES(?,?,'pending',?,?)", (a, bb, me, M.now_s()), fetch=False)
                notify(oid, "freq", me)
            except Exception:
                pass
            return jsonify({"ok": True, "rel": "sent"})
    if act == "accept":
        if rel != "recv":
            return jsonify({"ok": False, "error": GENERIC}), 400
        for x in (me, oid):
            if q("SELECT COUNT(*) FROM friend WHERE (a=? OR b=?) AND status='ok'", (x, x), one=True)[0] >= MAX_FRIENDS:
                return jsonify({"ok": False, "error": f"친구는 {MAX_FRIENDS}명까지예요."}), 400
        q("UPDATE friend SET status='ok', ts=? WHERE a=? AND b=? AND status='pending' AND req_by=?", (M.now_s(), a, bb, oid), fetch=False)
        notify(oid, "facc", me)
        return jsonify({"ok": True, "rel": "friend"})
    ok = {"decline": rel == "recv", "cancel": rel == "sent", "remove": rel == "friend"}[act]
    if not ok:
        return jsonify({"ok": False, "error": GENERIC}), 400
    q("DELETE FROM friend WHERE a=? AND b=?", (a, bb), fetch=False)
    return jsonify({"ok": True, "rel": "none"})


@bp.post("/api/social/block")
def block():
    m = _me(); _csrf(); me = m["id"]
    b = request.get_json(silent=True) or {}
    o = _member(mid=b.get("id"))
    if not o or o[0] == me:
        return jsonify({"ok": False, "error": GENERIC}), 400
    if b.get("on"):
        try:
            q("INSERT INTO mblock(member_id,target,ts) VALUES(?,?,?)", (me, o[0], M.now_s()), fetch=False)
        except Exception:
            pass
        a, bb = _pair(me, o[0]); q("DELETE FROM friend WHERE a=? AND b=?", (a, bb), fetch=False)
    else:
        q("DELETE FROM mblock WHERE member_id=? AND target=?", (me, o[0]), fetch=False)
    return jsonify({"ok": True})


@bp.post("/api/social/privacy")
def privacy():
    m = _me(); _csrf()
    h = 1 if (request.get_json(silent=True) or {}).get("hide") else 0
    q("UPDATE members SET hide_online=? WHERE id=?", (h, m["id"]), fetch=False)
    return jsonify({"ok": True, "hide": h})


@bp.get("/api/social/convs")
def convs():
    m = _me(); me = m["id"]
    rows = q("""SELECT d.a,d.b,MAX(d.id) FROM dm_msg d WHERE (d.a=? OR d.b=?) AND d.hidden=0 GROUP BY d.a,d.b ORDER BY MAX(d.id) DESC LIMIT 100""", (me, me))
    if not rows:
        return jsonify({"ok": True, "items": []})
    peers = [(r[1] if r[0] == me else r[0]) for r in rows]
    last = {r[2]: None for r in rows}
    ph = ",".join("?" * len(last))
    lm = {r[0]: r for r in q(f"SELECT id,sender,body,ts FROM dm_msg WHERE id IN ({ph})", list(last))}
    rd = {r[0]: r[1] for r in q("SELECT peer,last_id FROM dm_read WHERE member_id=?", (me,))}
    ph2 = ",".join("?" * len(peers))
    cards = {c["id"]: c for c in _cards(q(f"SELECT id,nick,hide_online FROM members WHERE id IN ({ph2})", peers))}
    hid = {r[0]: r[1] for r in q(f"SELECT id,hide_online FROM members WHERE id IN ({ph2})", peers)}
    un = {}
    for r in q(f"SELECT sender,COUNT(*),0 FROM dm_msg WHERE (a=? OR b=?) AND sender<>? AND hidden=0 AND sender IN ({ph2}) GROUP BY sender", [me, me, me] + peers):
        un[r[0]] = r[1]
    # 정확한 unread: last_id 이후
    out = []
    for r, p in zip(rows, peers):
        c = cards.get(p)
        if not c:
            continue
        l = lm.get(r[2])
        n = q("SELECT COUNT(*) FROM dm_msg WHERE a=? AND b=? AND sender=? AND hidden=0 AND id>?", (r[0], r[1], p, rd.get(p, 0)), one=True)[0]
        out.append({**c, "on": 1 if online(p) and not hid.get(p) else 0, "last": l[2][:60] if l else "", "ts": l[3] if l else 0, "mine": 1 if l and l[1] == me else 0, "unread": int(n)})
    return jsonify({"ok": True, "items": out})


@bp.get("/api/social/msgs")
def msgs():
    m = _me(); me = m["id"]
    o = _member(mid=request.args.get("peer", type=int))
    if not o:
        return jsonify({"ok": False, "error": GENERIC}), 404
    a, b = _pair(me, o[0])
    rel = _rel(me, o[0])
    after = request.args.get("after", 0, type=int)
    rows = q("SELECT id,sender,body,ts FROM dm_msg WHERE a=? AND b=? AND hidden=0 AND id>? ORDER BY id DESC LIMIT 200", (a, b, after))
    if rel != "friend" and not rows and not after:
        if not q("SELECT 1 FROM dm_msg WHERE a=? AND b=? LIMIT 1", (a, b), one=True):
            return jsonify({"ok": False, "error": "친구끼리만 대화할 수 있어요."}), 403
    rows = rows[::-1]
    q("UPDATE notif SET rd=1 WHERE member_id=? AND kind='dm' AND actor=? AND rd=0", (me, o[0]), fetch=False)
    if rows:
        lid = max(r[0] for r in rows)
        if q("SELECT 1 FROM dm_read WHERE member_id=? AND peer=?", (me, o[0]), one=True):
            q("UPDATE dm_read SET last_id=? WHERE member_id=? AND peer=? AND last_id<?", (lid, me, o[0], lid), fetch=False)
        else:
            q("INSERT INTO dm_read(member_id,peer,last_id) VALUES(?,?,?)", (me, o[0], lid), fetch=False)
    c = _cards([(o[0], o[1], o[3])])[0]
    c["on"] = 1 if online(o[0]) and not o[3] else 0
    return jsonify({"ok": True, "peer": c, "rel": rel, "blocked": _blocked(me, o[0]),
                    "items": [{"id": r[0], "me": 1 if r[1] == me else 0, "text": r[2], "ts": r[3]} for r in rows]})


@bp.post("/api/social/send")
def send():
    m = _me(); _csrf(); me = m["id"]
    b = request.get_json(silent=True) or {}
    o = _member(mid=b.get("peer"))
    text = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]*>", "", str(b.get("text") or ""))).strip()
    if not o or o[0] == me:
        return jsonify({"ok": False, "error": GENERIC}), 400
    if not text:
        return jsonify({"ok": False, "error": "내용을 입력해 주세요."}), 400
    if len(text) > MAX_LEN:
        return jsonify({"ok": False, "error": f"{MAX_LEN}자까지 쓸 수 있어요."}), 400
    if _rel(me, o[0]) != "friend" or _blocked(me, o[0]):
        return jsonify({"ok": False, "error": "친구끼리만 대화할 수 있어요."}), 403
    if _dm_banned(me):
        return jsonify({"ok": False, "error": "1:1 대화 이용이 제한된 계정이에요. 고객센터로 문의해 주세요."}), 403
    import chat
    if chat._mute.get("nick:" + m["nick"].lower(), 0) > time.time():
        return jsonify({"ok": False, "error": "채팅이 제한된 상태예요."}), 403
    if M.limited("dm:" + str(me), 12, 30) or M.limited("dmh:" + str(me), 300, 3600):
        return jsonify({"ok": False, "error": "너무 빨라요. 잠시 후 다시 보내 주세요."}), 429
    bad, flags = check_dm(text)
    if bad:
        q("INSERT INTO dm_blocked(ts,member_id,peer,body,reason) VALUES(?,?,?,?,?)", (M.now_s(), me, o[0], text[:300], flags), fetch=False)
        return jsonify({"ok": False, "error": bad}), 400
    a, bb = _pair(me, o[0])
    q("INSERT INTO dm_msg(a,b,sender,body,ts,sus) VALUES(?,?,?,?,?,?)", (a, bb, me, text, int(time.time()), flags or None), fetch=False)
    notify(o[0], "dm", me, text[:60])
    r = q("SELECT MAX(id) FROM dm_msg WHERE a=? AND b=? AND sender=?", (a, bb, me), one=True)
    return jsonify({"ok": True, "item": {"id": r[0], "me": 1, "text": text, "ts": int(time.time())}})


@bp.post("/api/social/report")
def report():
    m = _me(); _csrf(); me = m["id"]
    b = request.get_json(silent=True) or {}
    r = q("SELECT id,a,b,sender FROM dm_msg WHERE id=?", (b.get("id") or 0,), one=True)
    if not r or me not in (r[1], r[2]) or r[3] == me:
        return jsonify({"ok": False, "error": GENERIC}), 400
    if M.limited("rp:" + str(me), 10, 3600):
        return jsonify({"ok": False, "error": "잠시 후 다시 해 주세요."}), 429
    if not q("SELECT 1 FROM dm_report WHERE reporter=? AND msg_id=?", (me, r[0]), one=True):
        q("INSERT INTO dm_report(ts,reporter,msg_id,a,b,reason) VALUES(?,?,?,?,?,?)", (M.now_s(), me, r[0], r[1], r[2], str(b.get("reason") or "")[:100]), fetch=False)
    return jsonify({"ok": True})


# ---------- 관리자: 1:1 대화 모니터링 ----------
def _nicks(ids):
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    return {r[0]: (r[1], r[2]) for r in q(f"SELECT id,nick,status FROM members WHERE id IN ({ph})", ids)}


@bp.route("/admin/dm")
@admin_required
def adm_list():
    tab = request.args.get("tab", "convs")
    s = request.args.get("q", "").strip()[:12]
    d = request.args.get("d", "").strip()[:10]
    sus = request.args.get("sus") == "1"
    ctx = {"tab": tab, "s": s, "d": d, "sus": sus}
    if tab == "reports":
        rows = q("SELECT r.id,r.ts,r.reporter,r.msg_id,r.a,r.b,r.reason,r.status,m.body,m.sender FROM dm_report r LEFT JOIN dm_msg m ON m.id=r.msg_id ORDER BY (r.status='open') DESC, r.id DESC LIMIT 200")
        nk = _nicks([x for r in rows for x in (r[2], r[4], r[5], r[9])])
        ctx["reports"] = [{"id": r[0], "ts": r[1], "rep": nk.get(r[2], ("?",))[0], "a": r[4], "b": r[5], "an": nk.get(r[4], ("?",))[0], "bn": nk.get(r[5], ("?",))[0],
                           "reason": r[6], "st": r[7], "body": r[8], "sn": nk.get(r[9], ("?",))[0], "mid": r[3]} for r in rows]
    elif tab == "blocked":
        w, args = [], []
        if s:
            w.append("m.nick_l LIKE ?"); args.append("%" + s.lower() + "%")
        if d:
            w.append("b.ts LIKE ?"); args.append(d + "%")
        rows = q("SELECT b.id,b.ts,b.member_id,b.peer,b.body,b.reason FROM dm_blocked b JOIN members m ON m.id=b.member_id"
                 + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY b.id DESC LIMIT 300", args)
        nk = _nicks([x for r in rows for x in (r[2], r[3])])
        ctx["blocked"] = [{"ts": r[1], "mid": r[2], "n": nk.get(r[2], ("?",))[0], "pn": nk.get(r[3], ("?",))[0], "body": r[4], "why": r[5]} for r in rows]
    else:
        w, args = ["1=1"], []
        if s:
            ids = [r[0] for r in q("SELECT id FROM members WHERE nick_l LIKE ? LIMIT 200", ("%" + s.lower() + "%",))] or [0]
            ph = ",".join("?" * len(ids)); w.append(f"(a IN ({ph}) OR b IN ({ph}))"); args += ids + ids
        if d:
            try:
                t0 = int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST).timestamp())
                w.append("ts>=? AND ts<?"); args += [t0, t0 + 86400]
            except ValueError:
                pass
        having = " HAVING SUM(CASE WHEN sus IS NOT NULL AND sus<>'' THEN 1 ELSE 0 END)>0" if sus else ""
        rows = q(f"SELECT a,b,COUNT(*),MAX(id),SUM(CASE WHEN sus IS NOT NULL AND sus<>'' THEN 1 ELSE 0 END) FROM dm_msg WHERE {' AND '.join(w)} GROUP BY a,b{having} ORDER BY MAX(id) DESC LIMIT 200", args)
        lm = {}
        if rows:
            ph = ",".join("?" * len(rows))
            lm = {r[0]: r for r in q(f"SELECT id,body,ts,sender FROM dm_msg WHERE id IN ({ph})", [r[3] for r in rows])}
        nk = _nicks([x for r in rows for x in (r[0], r[1])])
        ctx["convs"] = [{"a": r[0], "b": r[1], "an": nk.get(r[0], ("?",))[0], "bn": nk.get(r[1], ("?",))[0], "n": r[2], "sus": int(r[4] or 0),
                         "last": (lm.get(r[3]) or (0, ""))[1][:60], "ts": datetime.fromtimestamp((lm.get(r[3]) or (0, "", 0))[2], KST).strftime("%m-%d %H:%M") if lm.get(r[3]) else ""} for r in rows]
    ctx["nrep"] = q("SELECT COUNT(*) FROM dm_report WHERE status='open'", one=True)[0]
    alog("dm list " + tab + (" q=" + s if s else ""))
    return render_template("admin.html", mode="dm", sec="dm", **ctx)


@bp.route("/admin/dm/<int:a>/<int:b>")
@admin_required
def adm_view(a, b):
    a, b = _pair(a, b)
    rows = q("SELECT id,sender,body,ts,sus,hidden FROM dm_msg WHERE a=? AND b=? ORDER BY id DESC LIMIT 500", (a, b))[::-1]
    nk = _nicks([a, b])
    rep = {r[0] for r in q("SELECT msg_id FROM dm_report WHERE a=? AND b=?", (a, b))}
    mem = {}
    for x in (a, b):
        r = q("SELECT dm_until,status FROM members WHERE id=?", (x,), one=True)
        mem[x] = {"id": x, "nick": nk.get(x, ("?",))[0], "dm": r[0] if r else None, "st": r[1] if r else "?"}
    if request.args.get("r") != "1":
        alog("dm view", f"{a},{b}")
    items = [{"id": r[0], "s": r[1], "sn": nk.get(r[1], ("?",))[0], "body": r[2], "ts": datetime.fromtimestamp(r[3], KST).strftime("%m-%d %H:%M:%S"),
              "sus": r[4], "hid": r[5], "rep": r[0] in rep, "left": r[1] == a} for r in rows]
    if request.args.get("part") == "1":
        return render_template("_dm_panel.html", items=items, pa=mem[a], pb=mem[b], a=a, b=b)
    return render_template("admin.html", mode="dmview", sec="dm", items=items, pa=mem[a], pb=mem[b], a=a, b=b)


@bp.post("/admin/dm/act")
@admin_required
def adm_act():
    from flask import get_flashed_messages
    r = _adm_act()
    if request.headers.get("X-Fetch") == "1":
        return jsonify({"ok": True, "msg": " ".join(get_flashed_messages()) or "적용했어요."})
    return r


def _adm_act():
    act = request.form.get("act", "")
    mid = request.form.get("mid", type=int)
    why = request.form.get("why", "").strip()[:100] or "-"
    back = request.form.get("back", "/admin/dm")
    if not back.startswith("/admin/dm"):
        back = "/admin/dm"
    if act == "del":
        msg = request.form.get("msg", type=int)
        q("UPDATE dm_msg SET hidden=1 WHERE id=?", (msg,), fetch=False)
        q("UPDATE dm_report SET status='done' WHERE msg_id=?", (msg,), fetch=False)
        alog(f"dm msg delete #{msg}: {why}", mid); flash("메시지를 삭제했어요.")
    elif act == "report_done":
        q("UPDATE dm_report SET status='done' WHERE id=?", (request.form.get("rid", type=int),), fetch=False); flash("처리 완료로 표시했어요.")
    elif act in ("dm1", "dm7", "dmp", "dm0") and mid:
        v = {"dm1": (datetime.now(KST) + timedelta(days=1)), "dm7": (datetime.now(KST) + timedelta(days=7))}.get(act)
        val = v.strftime("%Y-%m-%d %H:%M:%S") if v else ("perm" if act == "dmp" else None)
        q("UPDATE members SET dm_until=? WHERE id=?", (val, mid), fetch=False)
        alog(f"dm suspend {act}: {why}", mid); flash("1:1 대화 제한을 " + ("해제했어요." if act == "dm0" else "적용했어요."))
    elif act == "mute" and mid:
        r = q("SELECT nick FROM members WHERE id=?", (mid,), one=True)
        if r:
            import chat
            chat._mute["nick:" + r[0].lower()] = time.time() + 86400
            alog(f"chat mute 24h: {why}", mid); flash("채팅을 24시간 제한했어요.")
    elif act == "suspend" and mid:
        if not M.g.get("admin", {}).get("super"):
            abort(403)
        q("UPDATE members SET status='suspended' WHERE id=?", (mid,), fetch=False)
        alog(f"member suspend (dm): {why}", mid); flash("계정을 정지했어요.")
    return redirect(back)

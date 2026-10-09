"""투윈스코어 실시간 채팅 (가입 없음, HTTP 폴링). 메모리 보관 + /tmp 저장. 단일 워커 전제."""
import os, re, json, time, threading, hmac, hashlib, random, unicodedata
from collections import deque, OrderedDict
from flask import Blueprint, request, jsonify, abort

bp = Blueprint("chat", __name__)
CAP = 200
MAX_ROOMS = 300
MAX_LEN = 200
STORE = os.path.join(os.environ.get("CACHE_DIR", "/tmp/twowinscore-cache"), "chat.json")
ROOM_RE = re.compile(r"^(lounge|game-[a-z]+-\d+-[A-Za-z0-9]+)$")
NICK_RE = re.compile(r"^[0-9A-Za-z가-힣_]{2,12}$")
TAG_RE = re.compile(r"^\d{4}$")

_lock = threading.Lock()
_rooms = OrderedDict()          # room -> deque(msg)
_deleted = {}                   # room -> deque(id)
_online = {}                    # room -> {cid: ts}
_seq = [0]
_hist = {}                      # key -> deque(ts)  (rate limit)
_viol = {}                      # ip -> deque(ts)
_mute = {}                      # "ip:x" / "nick:x" -> until ts
_dirty = [0.0]

# ---------- moderation ----------
DRUGS = ["마약", "대마", "필로폰", "향정신제", "향정", "코카인", "케타민", "엑스터시", "떨액", "작대기", "아이스작대기"]
DRUG_TOKENS = ["아이스", "크리스탈", "차가운거", "떨"]   # 흔한 낱말과 겹쳐서 독립된 낱말일 때만
PROFANITY = ["씨발", "시발", "씨바", "ㅅㅂ", "ㅆㅂ", "ㅅ1ㅂ", "병신", "ㅂㅅ", "븅신", "좆", "존나", "졸라", "ㅈㄴ", "개새끼", "개새", "새끼",
             "니미", "느금", "엠창", "애미", "애비", "지랄", "ㅈㄹ", "썅", "미친놈", "미친년", "닥쳐", "꺼져", "등신", "호로", "fuck", "shit", "bitch"]
PORN = ["야동", "포르노", "porn", "섹스", "sex", "보지", "자지", "성인방", "조건만남", "몸캠", "노모", "야사", "av배우", "섹파", "오피", "유흥", "출장안마", "19금"]
BETTING = ["토토", "배팅", "베팅", "카지노", "바카라", "슬롯", "꽁머니", "먹튀", "사설", "배당", "충전", "환전", "픽스터", "가입코드", "추천인", "총판", "홀덤"]
SOLICIT = ["텔레그램", "텔레", "텔그", "telegram", "카톡", "오픈채팅", "오픈톡", "디엠", "dm주", "라인아이디", "위챗"]
WORDS = None  # _norm 적용 후 채움
URL_RE = re.compile(r"(https?://|www\.|t\.me|telegram\.(me|org)|tg://|\b[a-z0-9-]{2,}\s*(\.|닷|dot)\s*(com|net|org|kr|co|io|me|ly|gg|xyz|top|site|club|live|tv|link|app|bet|vip|shop)\b)", re.I)
HANDLE_RE = re.compile(r"@\s*[A-Za-z0-9_]{3,}")
STRIP_RE = re.compile(r"[\s\.\,\-_~!\?\*\^\'\"`|/\\()\[\]{}<>:;+=#$%&·•…ㆍ]+")


def _norm(s):
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", s)
    return s


WORDS = [_norm(w) for w in DRUGS + PROFANITY + PORN + BETTING + SOLICIT]
DRUG_TOKENS = [_norm(w) for w in DRUG_TOKENS]


def check_text(text):
    """None 이면 통과, 아니면 사유(한국어)."""
    t = _norm(text)
    if re.search(r"(공|영)\s*(일|1)\s*(공|영|0)", t):
        return "전화번호는 올릴 수 없어요."
    if URL_RE.search(t) or URL_RE.search(STRIP_RE.sub("", t).replace("닷", ".")):
        return "링크·주소는 올릴 수 없어요."
    if HANDLE_RE.search(t):
        return "@아이디는 올릴 수 없어요."
    digits = re.sub(r"[^0-9]", "", re.sub(r"[공영]", "0", t))
    if re.search(r"0\d{1,2}[\s\-\.]*\d{3,4}[\s\-\.]*\d{4}", t) or len(digits) >= 9 and re.search(r"\d[\d\s\-\.]{8,}\d", t):
        return "전화번호는 올릴 수 없어요."
    squeezed = STRIP_RE.sub("", t)
    for w in WORDS:
        if w in squeezed:
            return "사용할 수 없는 단어가 있어요."
    tokens = set(STRIP_RE.sub(" ", t).split())
    for w in DRUG_TOKENS:
        if w in tokens or any(tok.startswith(w) and len(tok) <= len(w) + 1 and w != "떨" for tok in tokens):
            return "사용할 수 없는 단어가 있어요."
    return None


def check_nick(nick):
    if not NICK_RE.match(nick or ""):
        return "닉네임은 2~12자 한글·영문·숫자로 해 주세요."
    if check_text(nick) or any(w in nick.lower() for w in ("admin", "관리자", "운영자", "투윈", "twowin")):
        return "사용할 수 없는 닉네임이에요."
    return None


# ---------- helpers ----------
def _ip():
    # Render(Cloudflare 앞단)는 CF-Connecting-IP/True-Client-IP 를 넣는다. 없으면 XFF 의 맨 오른쪽(프록시가 붙인 값).
    for h in ("CF-Connecting-IP", "True-Client-IP"):
        v = request.headers.get(h, "").strip()
        if v:
            return v
    xf = [x.strip() for x in request.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
    return (xf[-1] if xf else request.remote_addr) or "?"


def _iph(ip):
    return hashlib.sha256(("tw:" + ip).encode()).hexdigest()[:12]


def _room(name):
    if not ROOM_RE.match(name or ""):
        abort(404)
    with _lock:
        if name not in _rooms:
            _rooms[name] = deque(maxlen=CAP)
            _deleted[name] = deque(maxlen=100)
            while len(_rooms) > MAX_ROOMS:
                old, _ = _rooms.popitem(last=False)
                _deleted.pop(old, None); _online.pop(old, None)
        _rooms.move_to_end(name)
        return _rooms[name]


def _muted(ip, nick, now):
    for k in ("ip:" + ip, "nick:" + nick.lower()):
        u = _mute.get(k)
        if u and u > now:
            return u
    return None


def _violation(ip, nick, now):
    dq = _viol.setdefault(ip, deque(maxlen=10))
    dq.append(now)
    recent = [x for x in dq if now - x < 600]
    if len(recent) >= 3:
        _mute["ip:" + ip] = _mute["nick:" + nick.lower()] = now + 600
        dq.clear()
        return True
    return False


def _rate_ok(keys, now):
    for k in keys:
        dq = _hist.setdefault(k, deque(maxlen=10))
        if dq and now - dq[-1] < 2:
            return "너무 빨라요. 2초 뒤에 다시 보내 주세요."
        if len(dq) == 10 and now - dq[0] < 60:
            return "1분에 10개까지 보낼 수 있어요."
    for k in keys:
        _hist[k].append(now)
    return None


def _public(m):
    return {"id": m["id"], "nick": m["nick"], "tag": m["tag"], "text": m["text"], "ts": m["ts"]}


def _save_soon():
    _dirty[0] = time.time()


def _saver():
    while True:
        time.sleep(5)
        if not _dirty[0]:
            continue
        _dirty[0] = 0.0
        try:
            with _lock:
                snap = {"seq": _seq[0], "rooms": {r: list(d) for r, d in _rooms.items()}}
            os.makedirs(os.path.dirname(STORE), exist_ok=True)
            with open(STORE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)
            os.replace(STORE + ".tmp", STORE)
        except Exception:
            pass


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            snap = json.load(f)
        _seq[0] = int(snap.get("seq") or 0)
        for r, msgs in (snap.get("rooms") or {}).items():
            if ROOM_RE.match(r):
                _rooms[r] = deque(msgs[-CAP:], maxlen=CAP)
                _deleted[r] = deque(maxlen=100)
    except Exception:
        pass


_load()
threading.Thread(target=_saver, daemon=True).start()


def _online_count(room, cid, now):
    o = _online.setdefault(room, {})
    if cid and re.match(r"^[A-Za-z0-9]{8,32}$", cid):
        o[cid] = now
    for k in [k for k, t in o.items() if now - t > 40]:
        del o[k]
    return len(o)


# ---------- routes ----------
@bp.get("/api/chat/<room>")
def poll(room):
    msgs = _room(room)
    now = time.time()
    try:
        since = int(request.args.get("since", 0))
    except ValueError:
        since = 0
    with _lock:
        out = [_public(m) for m in msgs if m["id"] > since]
        if since == 0:
            out = out[-50:]
        n = _online_count(room, request.args.get("cid", ""), now)
        dels = list(_deleted.get(room) or [])
    return jsonify({"messages": out, "deleted": dels, "online": n, "last": _seq[0]})


@bp.get("/api/chat-online")
def online_all():
    now = time.time()
    with _lock:
        n = _online_count("lounge", request.args.get("cid", ""), now)
    return jsonify({"online": n})


@bp.post("/api/chat/<room>")
def post(room):
    msgs = _room(room)
    body = request.get_json(silent=True) or {}
    nick = str(body.get("nick") or "").strip()
    tag = str(body.get("tag") or "")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(body.get("text") or ""))).strip()
    ip = _ip()
    now = time.time()
    err = check_nick(nick) or (None if TAG_RE.match(tag) else "닉네임을 다시 정해 주세요.")
    if err:
        return jsonify({"ok": False, "error": err}), 400
    if not text:
        return jsonify({"ok": False, "error": "내용을 입력해 주세요."}), 400
    if len(text) > MAX_LEN:
        return jsonify({"ok": False, "error": f"{MAX_LEN}자까지 쓸 수 있어요."}), 400
    with _lock:
        u = _muted(ip, nick, now)
        if u:
            return jsonify({"ok": False, "error": f"채팅이 {int((u - now) // 60) + 1}분 동안 제한됐어요."}), 403
        bad = check_text(text)
        if bad:
            muted = _violation(ip, nick, now)
            return jsonify({"ok": False, "error": bad + (" 반복 위반으로 10분 동안 채팅이 제한돼요." if muted else "")}), 400
        rl = _rate_ok(["ip:" + ip, "nick:" + nick.lower()], now)
        if rl:
            return jsonify({"ok": False, "error": rl}), 429
        _seq[0] += 1
        m = {"id": _seq[0], "nick": nick, "tag": tag, "text": text, "ts": int(now), "iph": _iph(ip), "ip": ip}
        msgs.append(m)
        _save_soon()
    return jsonify({"ok": True, "message": _public(m)})


# ---------- admin ----------
def _admin():
    tok = os.environ.get("CHAT_ADMIN_TOKEN", "")
    given = request.headers.get("X-Admin-Token", "")
    if not tok or not given or not hmac.compare_digest(tok, given):
        abort(404)


@bp.post("/api/chat-admin")
def admin():
    _admin()
    b = request.get_json(silent=True) or {}
    act, now = b.get("action"), time.time()
    minutes = max(1, min(int(b.get("minutes") or 10), 7 * 24 * 60))
    with _lock:
        if act == "list":
            r = b.get("room", "lounge")
            return jsonify({"messages": [{**_public(m), "iph": m.get("iph")} for m in (_rooms.get(r) or [])][-100:],
                            "mutes": {k.split(":")[0] + ":" + (k.split(":", 1)[1] if k.startswith("nick:") else _iph(k[3:])): int(v - now)
                                      for k, v in _mute.items() if v > now}})
        if act == "delete":
            r, mid = b.get("room", "lounge"), int(b.get("id") or 0)
            dq = _rooms.get(r)
            if dq is None:
                return jsonify({"ok": False}), 404
            hit = [m for m in dq if m["id"] == mid]
            for m in hit:
                dq.remove(m)
                _deleted[r].append(mid)
            _save_soon()
            return jsonify({"ok": bool(hit)})
        if act == "mute":
            done = []
            if b.get("nick"):
                _mute["nick:" + str(b["nick"]).lower()] = now + minutes * 60; done.append("nick")
            if b.get("room") and b.get("id"):   # 메시지 작성자 IP 로 제한
                for m in _rooms.get(b["room"]) or []:
                    if m["id"] == int(b["id"]):
                        _mute["ip:" + m["ip"]] = _mute["nick:" + m["nick"].lower()] = now + minutes * 60; done.append("ip")
            return jsonify({"ok": bool(done), "muted": done, "minutes": minutes})
        if act == "unmute":
            if b.get("nick"):
                _mute.pop("nick:" + str(b["nick"]).lower(), None)
            return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "unknown action"}), 400

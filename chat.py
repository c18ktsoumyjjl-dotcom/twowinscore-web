"""투윈스코어 실시간 채팅 (가입 없음, HTTP 폴링). 메모리 보관 + /tmp 저장. 단일 워커 전제."""
import os, re, json, time, threading, hmac, hashlib, random, unicodedata
from collections import deque, OrderedDict
from flask import Blueprint, request, jsonify, abort

bp = Blueprint("chat", __name__)
CAP = 200
MAX_ROOMS = 300
MAX_LEN = 200
TTL = 600                       # 10분 지난 메시지는 사라진다
BRIDGE_ROOM = "lounge"
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
    if check_text(nick) or any(w in nick.lower() for w in ("admin", "관리자", "운영자", "운영진", "관리", "투윈", "twowin", "staff", "운영", "공식", "official", "mod", "gm", "system", "시스템", "고객센터", "매니저", "manager")):
        return "사용할 수 없는 닉네임이에요."
    return None


# ---------- helpers ----------
def _ip():
    # Render(Cloudflare 앞단)는 CF-Connecting-IP/True-Client-IP 를 넣는다. 없으면 XFF 의 맨 오른쪽(프록시가 붙인 값).
    # Render 앞단 Cloudflare 가 CF-Connecting-IP 를 덮어쓴다(클라이언트 값은 버려짐). True-Client-IP 등은 위조 가능하므로 무시.
    v = request.headers.get("CF-Connecting-IP", "").strip()
    if v and re.match(r"^[0-9A-Fa-f:.]{3,45}$", v):
        return v
    xf = [x.strip() for x in request.headers.get("X-Forwarded-For", "").split(",") if x.strip()]
    return (xf[-1] if xf else request.remote_addr) or "?"


def _tag(ip):
    """서버가 IP 해시로 정하는 #태그(4자리). 남의 태그를 흉내 낼 수 없다."""
    return str(1000 + int(hashlib.sha256(("tag:" + ip).encode()).hexdigest()[:8], 16) % 9000)


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
    d = {"id": m["id"], "nick": m["nick"], "tag": m["tag"], "text": m["text"], "ts": m["ts"]}
    if m.get("src") == "tg":
        d["src"] = "tg"
    return d


def _expire(now):
    """TTL 지난 메시지 제거(호출자가 _lock 보유)."""
    cut = now - TTL
    for dq in _rooms.values():
        while dq and dq[0]["ts"] < cut:
            dq.popleft()


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


def _cleaner():
    """기록이 무한히 늘지 않게 1분마다 오래된 항목 정리."""
    while True:
        time.sleep(60)
        now = time.time()
        try:
            with _lock:
                _expire(now)
                for k in [k for k, d in _hist.items() if not d or now - d[-1] > 120]:
                    del _hist[k]
                for k in [k for k, d in _viol.items() if not d or now - d[-1] > 600]:
                    del _viol[k]
                for k in [k for k, u in _mute.items() if u <= now]:
                    del _mute[k]
                for ip in list(_cidip):
                    m = _cidip[ip]
                    for c in [c for c, t in m.items() if now - t > 40]:
                        del m[c]
                    if not m:
                        del _cidip[ip]
                for r in list(_online):
                    o = _online[r]
                    for c in [c for c, t in o.items() if now - t > 40]:
                        del o[c]
                    if not o and r not in _rooms:
                        del _online[r]
        except Exception:
            pass


_load()
threading.Thread(target=_saver, daemon=True).start()
threading.Thread(target=_cleaner, daemon=True).start()


_cidip = {}                     # ip -> {cid: ts}  (접속자 수 부풀리기 방지)
MAX_CID_PER_IP = 6


def _online_count(room, cid, now):
    o = _online.setdefault(room, {})
    if cid and re.match(r"^[A-Za-z0-9]{8,32}$", cid):
        mine = _cidip.setdefault(_ip(), {})
        if cid in mine or len(mine) < MAX_CID_PER_IP:
            mine[cid] = now
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
        out = [_public(m) for m in msgs if m["id"] > since and now - m["ts"] < TTL]
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
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(body.get("text") or ""))).strip()
    ip = _ip()
    now = time.time()
    tag = _tag(ip)
    err = check_nick(nick)
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


# ---------- 응원 (경기별 두 팀 카운터, 메모리) ----------
_cheer, _cheer_ip = {}, {}
_CHEER_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


@bp.get("/api/cheer/<room>")
def cheer_get(room):
    if not _CHEER_RE.match(room):
        abort(404)
    with _lock:
        c = _cheer.get(room) or [0, 0]
    return jsonify({"L": c[0], "R": c[1]})


@bp.post("/api/cheer/<room>")
def cheer_post(room):
    if not _CHEER_RE.match(room):
        abort(404)
    side = (request.get_json(silent=True) or {}).get("side")
    if side not in ("L", "R"):
        return jsonify({"ok": False}), 400
    now, ip = time.time(), _ip()
    with _lock:
        if len(_cheer_ip) > 20000:
            for k in [k for k, t in _cheer_ip.items() if now - t > 5]:
                del _cheer_ip[k]
        k = ip + "|" + room
        if now - _cheer_ip.get(k, 0) < 1.0:
            c = _cheer.get(room) or [0, 0]
            return jsonify({"ok": False, "L": c[0], "R": c[1]}), 429
        _cheer_ip[k] = now
        if room not in _cheer and len(_cheer) > 3000:
            _cheer.clear()
        c = _cheer.setdefault(room, [0, 0])
        c[0 if side == "L" else 1] += 1
    return jsonify({"ok": True, "L": c[0], "R": c[1]})


# ---------- telegram bridge (lounge <-> 그룹방) ----------
PHONE_RE = re.compile(r"(\+?\d[\d\s\-\.]{7,}\d)|((공|영)\s*(일|1)\s*(공|영|0)[\s\d공영일이삼사오육칠팔구\-\.]*)")
URL_STRIP_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S*|telegram\.(me|org)\S*|tg://\S+|\b[a-z0-9-]{2,}\.(com|net|org|kr|co|io|me|ly|gg|xyz|top|site|club|live|tv|link|app|bet|vip|shop)\S*)", re.I)


def _bridge_auth():
    tok = os.environ.get("BRIDGE_TOKEN", "")
    given = request.headers.get("X-Bridge-Token", "")
    if len(tok) < 32 or not given or not hmac.compare_digest(tok, given):
        abort(404)


def bridge_clean(text):
    """그룹방 글: 링크·@아이디·전화번호는 지우고, 금지어가 남으면 None."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(text or ""))).strip()
    t = URL_STRIP_RE.sub("", t)
    t = HANDLE_RE.sub("", t)
    t = PHONE_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()[:MAX_LEN]
    if not t or check_text(t):
        return None
    return t


def bridge_name(name):
    n = re.sub(r"[^0-9A-Za-z가-힣_ ]", "", str(name or "")).strip()[:12]
    if len(n) < 1 or check_text(n) or check_nick(n.replace(" ", "_") if len(n) >= 2 else "xx") == "사용할 수 없는 닉네임이에요.":
        n = "회원"
    return n


@bp.post("/api/bridge/in")
def bridge_in():
    _bridge_auth()
    body = request.get_json(silent=True) or {}
    items = body.get("messages") or []
    if not isinstance(items, list):
        return jsonify({"ok": False}), 400
    msgs = _room(BRIDGE_ROOM)
    now, added, dropped = time.time(), 0, 0
    with _lock:
        for it in items[:30]:
            if not isinstance(it, dict):
                continue
            t = bridge_clean(it.get("text"))
            if not t:
                dropped += 1
                continue
            _seq[0] += 1
            msgs.append({"id": _seq[0], "nick": "[텔레] " + bridge_name(it.get("name")), "tag": "", "text": t,
                         "ts": int(now), "iph": "tg", "ip": "tg", "src": "tg"})
            added += 1
        if added:
            _save_soon()
    return jsonify({"ok": True, "added": added, "dropped": dropped})


@bp.get("/api/bridge/out")
def bridge_out():
    """그룹방으로 보낼 웹 메시지. since 없음(-1)이면 현재 번호만(시작 때 옛 글을 쏟지 않게)."""
    _bridge_auth()
    try:
        since = int(request.args.get("since", -1))
    except ValueError:
        since = -1
    now = time.time()
    with _lock:
        last = _seq[0]
        if since < 0 or since > last:          # 첫 호출 또는 웹 재시작으로 번호가 줄었음
            return jsonify({"messages": [], "last": last})
        out = [{"id": m["id"], "nick": m["nick"], "tag": m["tag"], "text": m["text"]}
               for m in (_rooms.get(BRIDGE_ROOM) or []) if m["id"] > since and m.get("src") != "tg" and now - m["ts"] < 120]
    return jsonify({"messages": out[:50], "last": last})


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

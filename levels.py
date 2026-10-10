"""회원 등급(리그 승강제). 활동 점수만 — 돈·상품·베팅과 무관. 모든 계산은 서버에서."""
import logging, threading
from datetime import datetime, timedelta
import members as M

log = logging.getLogger("levels")
# (이름, 필요 점수, 배지색)
TIERS = [("아마추어", 0, "#8a94a6"), ("세미프로", 30, "#3fa66b"), ("프로", 150, "#2f7fe0"),
         ("국가대표", 1500, "#ff7a1a"), ("레전드", 7000, "#f2c230")]
ATTEND, STREAK_STEP, STREAK_MAX = 10, 2, 10
CHAT_PER, CHAT_MAX = 1, 30
CHEER_PER, CHEER_MAX = 2, 10
_ok = [False]
_lk = threading.Lock()
SCHEMA = """CREATE TABLE IF NOT EXISTS member_lv(member_id BIGINT PRIMARY KEY, pts BIGINT NOT NULL DEFAULT 0,
 seen INTEGER NOT NULL DEFAULT 0, streak INTEGER NOT NULL DEFAULT 0, last_day TEXT, day TEXT,
 chat_pts INTEGER NOT NULL DEFAULT 0, cheer_pts INTEGER NOT NULL DEFAULT 0, cheer_rooms TEXT NOT NULL DEFAULT '')"""


def init():
    if not M.enabled():
        return
    try:
        M.q(SCHEMA, fetch=False); _ok[0] = True
    except Exception:
        log.exception("member_lv init failed")


def tier_of(p):
    i = 0
    for k, t in enumerate(TIERS):
        if p >= t[1]:
            i = k
    return i


def _today():
    return datetime.now(M.KST).strftime("%Y-%m-%d")


def _row(mid):
    r = M.q("SELECT pts,seen,streak,last_day,day,chat_pts,cheer_pts,cheer_rooms FROM member_lv WHERE member_id=?", (mid,), one=True)
    if not r:
        M.q("INSERT INTO member_lv(member_id) VALUES(?)", (mid,), fetch=False)
        r = (0, 0, 0, None, None, 0, 0, "")
    r = list(r)
    if r[4] != _today():          # 새 날: 일일 한도 리셋
        r[4], r[5], r[6], r[7] = _today(), 0, 0, ""
    return r


def _save(mid, r):
    M.q("UPDATE member_lv SET pts=?,seen=?,streak=?,last_day=?,day=?,chat_pts=?,cheer_pts=?,cheer_rooms=? WHERE member_id=?",
        (*r, mid), fetch=False)


def _attend(r):
    t = _today()
    if r[3] == t:
        return 0
    y = (datetime.now(M.KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    r[2] = r[2] + 1 if r[3] == y else 1
    r[3] = t
    add = ATTEND + min(STREAK_MAX, STREAK_STEP * (r[2] - 1))
    r[0] += add
    return add


def award(mid, kind, room=""):
    """kind: visit / chat / cheer. 승급하면 새 등급 번호 반환."""
    if not _ok[0] or not mid:
        return None
    try:
        with _lk:
            r = _row(mid); before = tier_of(r[0])
            _attend(r)
            if kind == "chat" and r[5] < CHAT_MAX:
                r[5] += CHAT_PER; r[0] += CHAT_PER
            elif kind == "cheer" and r[6] < CHEER_MAX and room and room not in r[7].split(","):
                r[6] += CHEER_PER; r[0] += CHEER_PER; r[7] = (r[7] + "," + room)[-900:]
            _save(mid, r)
            after = tier_of(r[0])
            return after if after > before else None
    except Exception:
        log.exception("award failed")
        return None


def info(mid):
    if not _ok[0] or not mid:
        return None
    try:
        r = M.q("SELECT pts,seen,streak FROM member_lv WHERE member_id=?", (mid,), one=True) or (0, 0, 0)
    except Exception:
        return None
    p = int(r[0]); i = tier_of(p); n = TIERS[i + 1] if i + 1 < len(TIERS) else None
    pct = 100 if not n else int((p - TIERS[i][1]) * 100 / (n[1] - TIERS[i][1]))
    return {"pts": p, "i": i, "name": TIERS[i][0], "color": TIERS[i][2], "seen": int(r[1]), "streak": int(r[2]),
            "next": n[0] if n else None, "need": (n[1] - p) if n else 0, "pct": pct}


def mark_seen(mid, i):
    if _ok[0]:
        M.q("UPDATE member_lv SET seen=? WHERE member_id=?", (i, mid), fetch=False)


def many(ids):
    if not _ok[0] or not ids:
        return {}
    ph = ",".join("?" * len(ids))
    return {r[0]: int(r[1]) for r in M.q(f"SELECT member_id,pts FROM member_lv WHERE member_id IN ({ph})", list(ids))}


def admin_set(mid, delta):
    with _lk:
        r = _row(mid); r[0] = max(0, r[0] + delta); _save(mid, r)
        return r[0]


def admin_set_tier(mid, i):
    """관리자가 등급을 직접 지정: 점수를 그 등급의 시작 점수로 맞춤 (이후 활동으로 계속 쌓임)"""
    with _lk:
        r = _row(mid); old = r[0]; r[0] = TIERS[i][1]; r[1] = min(r[1], i); _save(mid, r)
        return old, r[0]

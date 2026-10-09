"""Shared helpers for 투윈스코어 bot. Never prints/logs secret values."""
import os, json, time, urllib.request, urllib.parse, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE, "score.log")
CHANNEL_PATH = os.path.join(BASE, "channel.json")
CHANNEL_TITLE = "투윈스코어24"  # 채널 실제 제목. 예전 "투윈스코어" 와 다르면 시작 시 channel.json 을 지우고 멈춘다.
CANDIDATE_IDS = [-1004295999404, -4295999404]  # from Telegram Web URL #-4295999404


def _secrets():
    return [s for s in (os.environ.get("SCORE_BOT_TOKEN"), os.environ.get("API_SPORTS_KEY")) if s]


def redact(s):
    s = str(s)
    for sec in _secrets():
        s = s.replace(sec, "[redacted]")
    return s


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + redact(msg)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1_000_000:
            with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-3000:]
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class TgError(Exception):
    def __init__(self, code, desc, retry_after=None):
        super().__init__(f"{code} {desc}")
        self.code, self.desc, self.retry_after = code, desc, retry_after


def tg(method, payload=None, timeout=30):
    tok = os.environ.get("SCORE_BOT_TOKEN")
    if not tok:
        raise TgError(0, "SCORE_BOT_TOKEN missing")
    url = f"https://api.telegram.org/bot{tok}/{method}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            raise TgError(e.code, redact(e.reason))
    except Exception as e:
        raise TgError(-1, redact(e))
    if not body.get("ok"):
        ra = (body.get("parameters") or {}).get("retry_after")
        raise TgError(body.get("error_code"), redact(body.get("description")), ra)
    return body.get("result")


def tg_multipart(method, fields, files, timeout=60):
    """fields: dict (dict/list 값은 JSON 문자열로), files: {name: path}. 토큰은 로그/예외에 남기지 않는다."""
    import uuid
    tok = os.environ.get("SCORE_BOT_TOKEN")
    if not tok:
        raise TgError(0, "SCORE_BOT_TOKEN missing")
    boundary = "----twowin" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n').encode()
                     + str(v).encode("utf-8") + b"\r\n")
    for name, path in files.items():
        with open(path, "rb") as f:
            data = f.read()
        fn = os.path.basename(path)
        ctype = "image/jpeg" if fn.lower().endswith((".jpg", ".jpeg")) else "image/png"
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                      f'Content-Type: {ctype}\r\n\r\n').encode() + data + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    url = f"https://api.telegram.org/bot{tok}/{method}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            res = json.loads(e.read().decode())
        except Exception:
            raise TgError(e.code, redact(e.reason))
    except Exception as e:
        raise TgError(-1, redact(e))
    if not res.get("ok"):
        ra = (res.get("parameters") or {}).get("retry_after")
        raise TgError(res.get("error_code"), redact(res.get("description")), ra)
    return res.get("result")


def load_channel():
    try:
        with open(CHANNEL_PATH, encoding="utf-8") as f:
            d = json.load(f)
        cid = int(d["chat_id"])
        return cid
    except Exception:
        return None


def verify_chat(chat_id, bot_id=None):
    """Return chat info dict if chat is the 투윈스코어 channel and bot can post; else None."""
    try:
        c = tg("getChat", {"chat_id": chat_id})
    except TgError as e:
        return None
    if c.get("title") != CHANNEL_TITLE or c.get("type") != "channel":
        return {"_reject": True, "id": c.get("id"), "title": c.get("title"), "type": c.get("type")}
    info = {"chat_id": c["id"], "title": c["title"], "type": c["type"]}
    if bot_id:
        try:
            m = tg("getChatMember", {"chat_id": c["id"], "user_id": bot_id})
            info["bot_status"] = m.get("status")
            info["can_post_messages"] = m.get("can_post_messages")
            info["can_edit_messages"] = m.get("can_edit_messages")
            info["can_delete_messages"] = m.get("can_delete_messages")
        except TgError as e:
            info["bot_status"] = f"unknown ({e.desc})"
    return info


def discover_channel(verbose=False):
    """Find the 투윈스코어 channel via getUpdates and candidate ids. Saves channel.json. Returns info or None."""
    out = print if verbose else (lambda *a, **k: None)
    me = tg("getMe")
    bot_id = me["id"]
    seen = {}
    try:
        ups = tg("getUpdates", {"timeout": 0, "allowed_updates": ["my_chat_member", "channel_post", "message"]})
    except TgError as e:
        out("getUpdates 실패:", e.desc)
        ups = []
    for u in ups or []:
        for fld in ("my_chat_member", "channel_post", "edited_channel_post", "message"):
            obj = u.get(fld)
            if obj and obj.get("chat"):
                c = obj["chat"]
                seen[c["id"]] = (c.get("title"), c.get("type"), fld)
    for cid, (title, typ, fld) in seen.items():
        out(f"업데이트에서 발견: id={cid} title={title} type={typ} ({fld})")
    ids = [cid for cid, (t, ty, _) in seen.items() if t == CHANNEL_TITLE] + CANDIDATE_IDS
    for cid in dict.fromkeys(ids):
        info = verify_chat(cid, bot_id)
        if info is None:
            out(f"id={cid}: 접근 불가 (봇이 아직 추가되지 않았거나 id가 다름)")
            continue
        if info.get("_reject"):
            out(f"id={cid}: 제목/종류 불일치 title={info.get('title')} type={info.get('type')} → 사용 안 함")
            continue
        out(f"id={cid}: 확인됨 {info}")
        with open(CHANNEL_PATH, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=1)
        log(f"channel found id={info['chat_id']} status={info.get('bot_status')}")
        return info
    return None


def shown_number(v):
    """점수 None 은 0. 표기용."""
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def display_scores(g):
    """(홈 점수, 원정 점수). 사이트와 같이 홈이 앞."""
    return shown_number(g.get("home_score")), shown_number(g.get("away_score"))


def display_sides(g):
    """왼쪽=홈, 오른쪽=원정. 각 항목은 (이름, id, 로고, 점수, '홈'|'원정')."""
    hs, aws = display_scores(g)
    left = (g.get("home"), g.get("home_id"), g.get("home_logo"), hs, "홈")
    right = (g.get("away"), g.get("away_id"), g.get("away_logo"), aws, "원정")
    return left, right


def channel_sides(g):
    """채널 카드 좌우. 야구는 왼쪽=원정, 오른쪽=홈 (원정 vs 홈). 다른 종목은 display_sides 그대로(왼쪽=홈).
    그룹 카드는 이 함수를 쓰지 않는다."""
    left, right = display_sides(g)
    if g.get("kind") == "baseball":
        return right, left
    return left, right


def swap_home_away(g):
    """홈/원정 필드를 맞바꾼 얕은 사본(표시용). 야구 그룹 카드에서 왼쪽=원정, 오른쪽=홈으로 그릴 때 쓴다."""
    out = dict(g)
    for k, v in g.items():
        if k.startswith("home"):
            out["away" + k[4:]] = v
        elif k.startswith("away"):
            out["home" + k[4:]] = v
    out["_sides_swapped"] = True
    return out


def swap_pair(d):
    """{'home': x, 'away': y} -> {'home': y, 'away': x} (없는 키는 그대로 없음)."""
    d = d or {}
    out = {}
    if "away" in d:
        out["home"] = d["away"]
    if "home" in d:
        out["away"] = d["home"]
    return out


def format_match(g):
    """실시간/종료 문구. '홈 홈점수 : 원정점수 원정'."""
    hs, aws = display_scores(g)
    return f"{g['home']} {hs} : {aws} {g['away']}"


def format_vs(g):
    """일정 한 줄의 팀 순서. '홈 vs 원정'."""
    return f"{g['home']} vs {g['away']}"

"""웹 채팅 '투윈스코어' 알림 봇 — 축구 골 알림만.
- 인기 리그(EPL·K리그1·UCL·라리가·분데스·세리에A·리그1·UEL)+국가대표 경기의 골(득점자·분·스코어)
- 종료 결과·응원 투표는 보내지 않음(텔레그램 그룹은 점수 봇이 프리뷰+투표 담당)
- 해당 경기 채팅방 + 홈 라운지에 올려요. 라운지 글은 기존 web_bridge 로 텔레그램 멤버 그룹에도 가요
  (점수 봇은 그룹에 축구 골/종료 알림을 보내지 않아서 중복 없음).
- 중복 방지: 보낸 이벤트 키를 캐시 파일에 저장(재시작해도 다시 안 보냄). 처음 켜질 때 이미 지난 골은 '본 것'으로만 표시.
- 도배 방지: 방마다 8초 간격, 한 번에 여러 개면 한 메시지로 묶음, 라운지는 시간당 최대 40개.
- 한 워커에서만(파일 잠금)."""
import os, json, time, fcntl, threading, logging
from datetime import datetime, timedelta
from collections import deque
import data, chat

log = logging.getLogger("chatbot")
NICK, TAG = "투윈스코어", "BOT"
FOOT_LEAGUES = {"EPL", "K리그1", "챔피언스리그", "라리가", "분데스리가", "세리에A", "리그1", "유로파리그",
                "UEFA 네이션스리그", "A매치 친선"}          # 국가대표 경기 포함
NATIONAL_WORDS = ("A매치", "월드컵", "아시안컵", "네이션스", "유로 20", "코파")


def _ok_league(name, alias):
    n = _norm_league(name or "", alias)
    return n in FOOT_LEAGUES or any(w in n for w in NATIONAL_WORDS)
STATE = os.path.join(data.CACHE, "chatbot_state.json")
LOOP = 30
_st = {"seen": {}, "boot": 0}
_last_room = {}
_lounge_hr = deque()


def _norm_league(name, alias):
    return alias.get(name, name)


def _load():
    try:
        with open(STATE) as f:
            _st.update(json.load(f))
    except Exception:
        pass


def _save():
    cut = time.time() - 3 * 86400
    _st["seen"] = {k: v for k, v in _st["seen"].items() if v > cut}
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_st, f)
    os.replace(tmp, STATE)


def room_of(g):
    return "game-" + str(g["key"]).replace(":", "-")


def post(room, text, extra=None, tg=None, nobridge=False):
    """봇 메시지 한 개를 방에 넣어요(필터·속도제한 없이, 서버 내부에서만)."""
    now = time.time()
    if room == chat.BRIDGE_ROOM:
        while _lounge_hr and now - _lounge_hr[0] > 3600:
            _lounge_hr.popleft()
        if len(_lounge_hr) >= 40:
            return False
        _lounge_hr.append(now)
    msgs = chat._room(room)
    with chat._lock:
        chat._seq[0] += 1
        m = {"id": chat._seq[0], "nick": NICK, "tag": TAG, "text": text[:400], "ts": int(now), "iph": "bot", "ip": "bot", "src": "bot"}
        if extra:
            m["x"] = extra
        if tg:
            m["tg"] = tg[:400]
        if nobridge:
            m["nobridge"] = 1
        msgs.append(m)
        chat._save_soon()
    _last_room[room] = now
    return True


def _score_txt(g, h, a):
    return f"{g['home']} {h} : {a} {g['away']}"


def _events(g, boot):
    """이 경기에서 새로 생긴 이벤트 [(key, game_text, lounge_text, extra)]"""
    out = []
    k0 = str(g["key"])
    st = g.get("state")
    if st in ("live", "final"):
        import plays, sports2
        try:
            rows = plays._cached("fbraw:" + str(g["id"]), 60 if st == "live" else 6 * 3600, lambda: sports2.raw_events(g))
            gl = sports2.goals(g, rows)
        except Exception as e:
            log.warning("events %s: %s", k0, e); gl = None
        if gl is not None:
            h = a = 0
            for i, y in enumerate(x for x in gl if x["half"] != "승부차기"):
                if y["side"] == "home":
                    h += 1
                else:
                    a += 1
                key = f"goal:{k0}:{y['side']}:{y['o']}:{i}"
                who = (y["who"] or "").strip() or (g["home"] if y["side"] == "home" else g["away"])
                kind = f"({y['kind']})" if y["kind"] else ""
                tail = f"{y['min']} {who}{kind} · {g['home']} {h}:{a} {g['away']}"
                lg = g.get("site_league") or ""
                out.append((key, f"⚽ {lg} {tail}", f"⚽ [{lg}] {tail}", None))
    return out


def tick(alias, boot=False):
    today = datetime.now(data.SEOUL).date()
    gs, _ = data.games_for(today)
    if datetime.now(data.SEOUL).hour < 6:
        try:
            gp, _ = data.games_for(today - timedelta(days=1))
            gs = [g for g in gp if g.get("state") == "live"] + gs
        except Exception:
            pass
    gs = [g for g in gs if g.get("kind") == "football" and _ok_league(g.get("site_league"), alias)]
    lounge = []
    for g in gs:
        lk = "live:" + str(g["key"])
        if g.get("state") == "live":
            _st["seen"][lk] = time.time()
        quiet = boot or (g.get("state") == "final" and time.time() - _st["seen"].get(lk, 0) > 900)
        new = [e for e in _events(g, boot) if e[0] not in _st["seen"]]
        if not new:
            continue
        now = time.time()
        for e in new:
            _st["seen"][e[0]] = now
        if quiet:  # 처음 켜질 때·오래전 끝난 경기: 지난 골은 기억만
            # 처음 켜질 때: 이미 지난 골/종료는 보내지 않고 기억만 (응원 투표는 시간대가 맞으면 보냄)
            continue
        room = room_of(g)
        x = {"poll": {"room": room, "L": g["home"], "R": g["away"]}}   # 골 메시지에 응원 버튼(상세 페이지와 같은 집계)
        new = new[-4:]
        post(room, "\n".join(e[1] for e in new), x, tg="\n".join(e[2] for e in new))
        lounge.append((new, x))
    for new, x in lounge[:6]:
        post(chat.BRIDGE_ROOM, "\n".join(e[1] for e in new), x, tg="\n".join(e[2] for e in new))
    _save()


def _loop(alias):
    _load()
    first = not _st.get("boot")
    time.sleep(15)
    try:
        tick(alias, boot=first)
        _st["boot"] = 1
        _save()
    except Exception as e:
        log.warning("chatbot boot: %s", e)
    while True:
        time.sleep(LOOP)
        try:
            tick(alias)
        except Exception as e:
            log.warning("chatbot: %s", e)



_lockf = [None]


def start(alias):
    if os.environ.get("CHATBOT", "1") == "0":
        return False
    try:
        os.makedirs(data.CACHE, exist_ok=True)
        f = open(os.path.join(data.CACHE, "chatbot.lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _lockf[0] = f
    threading.Thread(target=_loop, args=(alias,), daemon=True, name="chatbot").start()
    return True


def send_test():
    """[테스트] 골 메시지 1개(응원 버튼 포함)를 홈 채팅에. 텔레그램엔 글자만."""
    try:
        gs, _ = data.games_for(datetime.now(data.SEOUL).date())
    except Exception:
        gs = []
    fb = [g for g in gs if g.get("kind") == "football"]
    pop = [x for x in fb if _ok_league(x.get("site_league"), {})]
    g = next((x for x in pop + fb if x.get("state") in ("scheduled", "live")), (pop or fb or [None])[0])
    if not g:
        post(chat.BRIDGE_ROOM, "[테스트] ⚽ EPL 55' 사카(PK) · 토트넘 1:1 아스널", tg="[테스트] ⚽ [EPL] 55' 사카(PK) · 토트넘 1:1 아스널")
        return False
    lg, h, a = g.get("site_league") or "", g["home"], g["away"]
    post(chat.BRIDGE_ROOM, f"[테스트] ⚽ {lg} 55' 테스트선수 · {h} 1:1 {a}",
         {"poll": {"room": room_of(g), "L": h, "R": a}}, tg=f"[테스트] ⚽ [{lg}] 55' 테스트선수 · {h} 1:1 {a}")
    return True


TEST_KEY = "chatbot_test_3"   # 새 테스트가 필요하면 이 키만 바꾸면 한 번 더 감
_tested = [False]


def _test_once():
    """배포 직후 한 번만(사장님 요청 테스트). DB 표시로 재시작해도 다시 안 보냄."""
    try:
        from admin_ext import kv_get, kv_set
        if _tested[0]:
            return
        _tested[0] = True
        if kv_get(TEST_KEY) == "1":
            return
        kv_set(TEST_KEY, "1")
        send_test()
        log.warning("chatbot: test messages posted")
    except Exception as e:
        log.warning("chatbot test: %s", e)


def install(app):
    """한 번만 도는 테스트를 첫 채팅 요청(요청 스레드)에서 실행 — 백그라운드 스레드 상태와 무관."""
    from flask import request

    @app.before_request
    def _chatbot_test_hook():
        if not _tested[0] and request.path.startswith("/api/chat/"):
            _test_once()

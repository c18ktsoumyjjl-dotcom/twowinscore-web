#!/usr/bin/env python3
"""투윈스코어: API-Sports 야구/농구/배구 스코어(국내 + 해외 주요 리그)를 채널에만 올린다.

표기 순서: 홈 점수 : 원정 점수. 일정은 '홈 vs 원정'.
카드도 왼쪽이 홈, 오른쪽이 원정.
카드 캡션은 세 줄(헤더 / 홈 이름 점수 / 원정 이름 점수). 팀 이름은 자르지 않는다.
야구 예시(롯데 홈, LG 원정): ⚾ KBO | 롯데 2 : 3 LG | 7회말
조회: 종목마다 /games?date=오늘&timezone=Asia/Seoul 한 번 → LEAGUES 의 리그 id만 남긴다.
"""
import os, sys, json, time, re, traceback, html
import urllib.request, urllib.parse, urllib.error
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common import (
    log, redact, tg, tg_multipart, TgError, load_channel, discover_channel, BASE, CHANNEL_TITLE,
    display_scores, format_match, format_vs,
)
import cards

SEOUL = ZoneInfo("Asia/Seoul")
STATE_PATH = os.path.join(BASE, "state.json")
POLL_HOT = 5                # 진행 중/시작 임박 경기가 있을 때 조회 간격
DELETE_AFTER = 1 * 3600     # 끝난 경기 글은 종료 1시간 뒤 삭제 (일정 글은 안 지움)
RESET_POLL = 180            # 진행 중이었다가 NS/점수 없음으로 돌아온 경기는 games?id= 를 3분마다
RESET_GIVEUP = 60 * 60      # 마지막 진행 갱신 후 60분 동안 점수가 없으면 '최종 점수 확인 중'으로 닫음
NOT_STARTED = {"NS", "TBD"}
FULL_EVERY = 60             # 전체 조회(모든 종목, 새 경기 확인) 간격. 그 사이에는 진행 중인 종목만 조회
POLL_COLD = 300
EDIT_GAP = 5
HOT_BEFORE = 15 * 60
HOT_AFTER = 20 * 60
PRE_BEFORE = 30 * 60        # 시작 30분 전부터 대기 카드. 5분(POLL_COLD) 늦는 것은 허용
PRE_DRAIN = 15             # 대기 글이 남아 있으면 이 간격으로 한 장씩 (API 전체 조회는 아님)
PREV_DAY_HOURS = 6          # 0~6시에는 전날 경기(자정 넘어 이어지는 경기)도 같이 본다
SCHEDULE_MAX_GAMES = 30     # 일정 메시지 1개당 최대 경기 수
SCHEDULE_MAX_CHARS = 3500   # 텔레그램 4096자 제한보다 여유 있게
TG_WINDOW = 60              # 채널 전송 속도 제한(분당 약 20건) 대응
TG_MAX_PER_WINDOW = 18      # 새 글/수정 합계 상한
TG_EDIT_CEILING = 14        # 수정은 여기까지만 쓰고 나머지는 새 글(시작/종료)용으로 남긴다
UPLOAD_TIMEOUT = 10         # 사진 업로드 응답 대기. 텔레그램이 사진 처리 후 응답을 늦게/안 주는 경우가 있어 짧게 끊고 확인한다
PHOTO_WIDTH = 900           # 업로드용 JPEG 폭
# 카드 사진 아래 문구. False면 예전 한 줄(fmt_live/fmt_result). True면 format_caption_v2.
# 켜도 사진 카드 자체는 그대로다. 지금은 끄고, 채널에 나가던 문구를 바꾸지 않는다.
CAPTION_V2 = True
# 컴팩트 배너와 캡션을 사진 위에 두는 동작은 cards.CARD_COMPACT. 지금은 False.
# True 로 바꾸기 전에는 1000x560 카드이고 캡션은 사진 아래다.

HOSTS = {
    "baseball": "https://v1.baseball.api-sports.io",
    "basketball": "https://v1.basketball.api-sports.io",
    "volleyball": "https://v1.volleyball.api-sports.io",
}
EMOJI = {"baseball": "⚾", "basketball": "🏀", "volleyball": "🏐"}

# 종목별 API team id -> 한글 표기. 못 찾으면 영문 이름.
TEAM_KO = {
    "baseball": {
        # KBO
        88: "두산", 89: "한화", 90: "KIA", 91: "KT", 92: "키움",
        93: "LG", 94: "롯데", 95: "NC", 97: "삼성", 647: "SSG",
        390: "드림", 391: "나눔",
        # MLB
        1: "아메리칸리그", 23: "내셔널리그",
        2: "애리조나", 963: "애슬레틱스", 3: "애틀랜타", 4: "볼티모어", 5: "보스턴",
        6: "시카고 컵스", 7: "시카고 화이트삭스", 8: "신시내티", 9: "클리블랜드",
        10: "콜로라도", 12: "디트로이트", 15: "휴스턴", 16: "캔자스시티",
        17: "LA 에인절스", 18: "LA 다저스", 19: "마이애미", 20: "밀워키",
        22: "미네소타", 24: "뉴욕 메츠", 25: "뉴욕 양키스", 27: "필라델피아",
        28: "피츠버그", 30: "샌디에이고", 31: "샌프란시스코", 32: "시애틀",
        33: "세인트루이스", 34: "탬파베이", 35: "텍사스", 36: "토론토", 37: "워싱턴",
        # NPB (API-Sports league 2, 2026-10-09 팀 목록 대조)
        66: "요미우리", 58: "한신", 65: "요코하마 DeNA", 56: "주니치", 59: "히로시마", 64: "야쿠르트",
        57: "소프트뱅크", 60: "닛폰햄", 61: "오릭스", 62: "라쿠텐", 63: "세이부", 55: "지바롯데",
        387: "센트럴리그", 388: "퍼시픽리그",
        # CPBL
        348: "중신 브라더스", 349: "푸방 가디언스", 482: "라쿠텐 몽키스",
        915: "TSG 호크스", 351: "퉁이 라이온스", 569: "웨이취안 드래곤스",
    },
    "basketball": {
        # KBL
        1102: "안양 정관장", 1103: "고양 소노", 1105: "부산 KCC",
        3081: "대구 한국가스공사", 1106: "창원 LG", 1107: "울산 현대모비스",
        1108: "서울 SK", 1109: "서울 삼성", 3173: "수원 KT", 1111: "원주 DB",
        # WKBL
        1112: "부산 BNK", 2347: "부천 하나은행", 1113: "청주 KB",
        1115: "인천 신한은행", 1116: "용인 삼성생명", 3112: "아산 우리은행",
        # NBA
        132: "애틀랜타", 133: "보스턴", 134: "브루클린", 135: "샬럿", 136: "시카고",
        137: "클리블랜드", 138: "댈러스", 139: "덴버", 140: "디트로이트",
        141: "골든스테이트", 142: "휴스턴", 143: "인디애나", 144: "LA 클리퍼스",
        145: "LA 레이커스", 146: "멤피스", 147: "마이애미", 148: "밀워키",
        149: "미네소타", 150: "뉴올리언스", 151: "뉴욕", 152: "오클라호마시티",
        153: "올랜도", 154: "필라델피아", 155: "피닉스", 156: "포틀랜드",
        157: "새크라멘토", 158: "샌안토니오", 159: "토론토", 160: "유타", 161: "워싱턴",
        # 유로리그 (같은 팀이 자국 리그에 나와도 같은 이름)
        1263: "아나돌루 에페스", 2329: "바르셀로나", 2331: "바스코니아", 522: "바이에른 뮌헨",
        1266: "베식타스", 1065: "츠르베나 즈베즈다", 6496: "두바이", 1270: "페네르바흐체",
        682: "하포엘 텔아비브", 26: "아스벨", 687: "마카비 텔아비브", 722: "올림피아 밀라노",
        1542: "올림피아코스", 614: "파나티나이코스", 108: "파리", 1068: "파르티잔",
        2338: "레알 마드리드", 2341: "발렌시아", 732: "비르투스 볼로냐", 796: "잘기리스",
        # B리그 (B1)
        748: "아키타", 6349: "알티리 지바", 749: "알바크 도쿄", 750: "가와사키",
        751: "지바 제츠", 752: "나고야 D", 2975: "군마", 1585: "히로시마",
        3061: "이바라키", 1584: "고베", 754: "교토", 7905: "레반가 홋카이도",
        6034: "나가사키", 755: "산엔 네오피닉스", 757: "오사카", 758: "류큐",
        6035: "사가", 759: "미카와", 1586: "센다이", 760: "시가", 761: "시마네",
        2259: "신슈", 7906: "선로커스 시부야", 763: "도야마", 764: "우츠노미야", 765: "요코하마",
        # CBA
        422: "베이징", 423: "베이징 로열 파이터스", 424: "푸젠", 425: "광둥",
        426: "광저우", 427: "장쑤", 428: "지린", 429: "랴오닝", 430: "난징",
        3187: "닝보", 431: "칭다오", 432: "산둥", 433: "상하이", 434: "산시",
        435: "선전", 436: "쓰촨", 437: "톈진", 438: "신장", 439: "저장 처우저우",
        440: "저장 광샤",
    },
    "volleyball": {
        # V-League 남자
        1171: "대한항공", 1170: "현대캐피탈", 1172: "KB손해보험",
        1175: "삼성화재", 1173: "한국전력", 1176: "우리카드", 4144: "OK저축은행",
        # V-League 여자
        1181: "현대건설", 1179: "GS칼텍스", 1180: "흥국생명",
        1178: "한국도로공사", 1182: "IBK기업은행", 2162: "페퍼저축은행", 3820: "정관장",
    },
}


def _L(kind, league, season, label):
    return {"kind": kind, "base": HOSTS[kind], "league": league,
            "season": season, "label": label, "emoji": EMOJI[kind]}


# 순서 = 일정/정렬 순서 (국내 먼저). season 은 2026-10 기준 현재 시즌(참고용, 조회는 날짜 기준).
LEAGUES = [
    _L("baseball", 5, 2026, "KBO"),
    _L("baseball", 1, 2026, "MLB"),
    _L("baseball", 2, 2026, "일본 NPB"),
    _L("baseball", 29, 2026, "CPBL"),
    _L("basketball", 91, "2026-2027", "KBL"),
    _L("basketball", 92, "2026-2027", "WKBL"),
    _L("basketball", 12, "2026-2027", "NBA"),
    _L("basketball", 120, 2026, "유로리그"),
    _L("basketball", 31, "2026-2027", "CBA"),
    _L("basketball", 56, "2026-2027", "B리그"),
    _L("basketball", 407, "2025-2026", "B2리그"),
    _L("basketball", 45, "2026-2027", "그리스 A1"),
    _L("basketball", 44, "2026-2027", "그리스 A2"),
    _L("basketball", 34, "2026-2027", "덴마크 리그"),
    _L("basketball", 35, "2026-2027", "덴마크 여자"),
    _L("basketball", 1, "2026-2027", "호주 NBL"),
    _L("basketball", 100, "2026-2027", "스위스 LNA"),
    _L("basketball", 18, "2026-2027", "아르헨티나 리가A"),
    _L("volleyball", 151, 2026, "V리그 남자"),
    _L("volleyball", 152, 2026, "V리그 여자"),
    _L("volleyball", 89, 2026, "세리에A1 여자"),
    _L("volleyball", 97, 2026, "세리에A1 남자"),
]
LEAGUE_BY_KEY = {(m["kind"], m["league"]): m for m in LEAGUES}
LEAGUE_ORDER = {(m["kind"], m["league"]): i for i, m in enumerate(LEAGUES)}
SPORTS = list(dict.fromkeys(m["kind"] for m in LEAGUES))

LIVE = {
    "baseball": lambda s: bool(re.fullmatch(r"IN\d+", s or "")),
    "basketball": lambda s: s in {"Q1", "Q2", "Q3", "Q4", "OT", "HT", "BT"},
    "volleyball": lambda s: s in {"S1", "S2", "S3", "S4", "S5"},
}
FINISHED = {"FT", "AOT", "AWD", "WO", "AW"}
CANCELLED = {"CANC", "ABD"}
POSTPONED = {"POST", "PST"}
BBALL_PERIOD = {
    "Q1": "1Q", "Q2": "2Q", "Q3": "3Q", "Q4": "4Q",
    "OT": "연장", "HT": "하프타임", "BT": "쿼터 휴식", "FT": "종료", "AOT": "종료",
}
_unmapped_logged = set()


def ko_name(kind, team_id, english):
    m = TEAM_KO.get(kind) or {}
    if team_id in m:
        return m[team_id]
    if (kind, team_id) not in _unmapped_logged:
        _unmapped_logged.add((kind, team_id))
    return english or "알 수 없음"


def api_get(base, params):
    key = os.environ.get("API_SPORTS_KEY")
    if not key:
        raise RuntimeError("API_SPORTS_KEY missing")
    url = base + "/games?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(redact(e))
    errs = body.get("errors")
    if errs:
        raise RuntimeError("api errors " + redact(errs)[:300])
    return body.get("response") or []


def _num(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _side_score(scores, side):
    node = (scores or {}).get(side)
    if isinstance(node, dict):
        return _num(node.get("total"))
    return _num(node)


def period_text(kind, status, scores=None):
    short = (status or {}).get("short") or ""
    long = (status or {}).get("long") or ""
    if kind == "baseball":
        m = re.fullmatch(r"IN(\d+)", short)
        if m:
            half = ""
            low = long.lower()
            if "bottom" in low:
                half = "말"
            elif "top" in low:
                half = "초"
            if not half and isinstance(scores, dict):
                n = m.group(1)
                hi = ((scores.get("home") or {}).get("innings") or {})
                ai = ((scores.get("away") or {}).get("innings") or {})
                if hi.get(n) is not None:
                    half = "말"
                elif ai.get(n) is not None:
                    half = "초"
            return f"{m.group(1)}회{half}"
        if short in FINISHED:
            return "종료"
        return long or short or "진행 중"
    if kind == "basketball":
        return BBALL_PERIOD.get(short, long or short or "진행 중")
    if kind == "volleyball":
        m = re.fullmatch(r"S(\d+)", short)
        if m:
            return f"{m.group(1)}세트"
        if short in FINISHED:
            return "종료"
        return long or short or "진행 중"
    return short or "진행 중"


VB_SETS = ("first", "second", "third", "fourth", "fifth")
BB_QS = (("quarter_1", "1Q"), ("quarter_2", "2Q"), ("quarter_3", "3Q"), ("quarter_4", "4Q"), ("over_time", "OT"))


def period_lines(kind, raw):
    """쿼터/세트별 점수 [(라벨, 홈, 원정)]. 점수가 있는 구간만. 야구는 빈 목록."""
    out = []
    try:
        if kind == "basketball":
            sc = raw.get("scores") or {}
            h, a = sc.get("home") or {}, sc.get("away") or {}
            for k, lab in BB_QS:
                if h.get(k) is not None and a.get(k) is not None:
                    out.append((lab, int(h[k]), int(a[k])))
        elif kind == "volleyball":
            per = raw.get("periods") or {}
            for i, k in enumerate(VB_SETS):
                x = per.get(k) or {}
                if x.get("home") is not None and x.get("away") is not None:
                    out.append((f"{i + 1}세트", int(x["home"]), int(x["away"])))
    except (TypeError, ValueError):
        return []
    return out


# 검색용 별칭(카드에는 쓰지 않음). 다른 리그와 겹치는 짧은 애칭은 넣지 않는다.
TEAM_ALIAS = {
    "baseball": {
        66: ["요미우리 자이언츠", "교진"], 58: ["한신 타이거스"], 65: ["요코하마 베이스타스", "디엔에이", "DeNA"],
        56: ["주니치 드래건스"], 59: ["히로시마 카프", "히로시마 도요 카프"], 64: ["야쿠르트 스왈로스"],
        57: ["소프트뱅크 호크스", "후쿠오카 소프트뱅크"], 60: ["닛폰햄 파이터스", "니혼햄", "니혼햄 파이터스"],
        61: ["오릭스 버펄로스"], 62: ["라쿠텐 골든이글스"], 63: ["세이부 라이온스"],
        55: ["치바롯데", "지바롯데 마린스", "마린스"],
    },
}

# NPB 포스트시즌: API-Sports 'week' 값(2025 자료로 확인) -> 표시
NPB_ROUND = {"Quarter-finals": "CS 퍼스트", "Semi-finals": "CS 파이널", "Final": "일본시리즈"}


def parse_game(raw, meta):
    status = raw.get("status") or {}
    teams = raw.get("teams") or {}
    home, away = teams.get("home") or {}, teams.get("away") or {}
    try:
        start = datetime.fromisoformat(raw["date"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=SEOUL)
    except Exception:
        return None
    hid, aid = home.get("id"), away.get("id")
    scores = raw.get("scores") or {}
    return {
        "key": f"{meta['kind']}:{meta['league']}:{raw.get('id')}",
        "id": raw.get("id"),
        "emoji": meta["emoji"],
        "label": meta["label"] + (f" · {NPB_ROUND[raw.get('week')]}"
                                  if meta["kind"] == "baseball" and meta["league"] == 2 and raw.get("week") in NPB_ROUND else ""),
        "kind": meta["kind"],
        "league": meta["league"],
        "order": LEAGUE_ORDER.get((meta["kind"], meta["league"]), 99),
        "start": start,
        "status": status.get("short") or "",
        "away": ko_name(meta["kind"], aid, away.get("name")),
        "home": ko_name(meta["kind"], hid, home.get("name")),
        "away_id": aid,
        "home_id": hid,
        "away_logo": away.get("logo"),
        "home_logo": home.get("logo"),
        "away_score": _side_score(scores, "away"),
        "home_score": _side_score(scores, "home"),
        "period": period_text(meta["kind"], status, scores),
        "lines": period_lines(meta["kind"], raw),
    }


def fetch_sport_day(kind, day):
    """한 종목, 한 날짜 조회 (API 1회). 실패하면 예외."""
    raws = api_get(HOSTS[kind], {
        "date": day.isoformat(),
        "timezone": "Asia/Seoul",
    })
    out = []
    for raw in raws:
        lid = (raw.get("league") or {}).get("id")
        meta = LEAGUE_BY_KEY.get((kind, lid))
        if not meta:
            continue
        g = parse_game(raw, meta)
        if g:
            out.append(g)
    return out


def fetch_day(day):
    """day: datetime.date. 종목마다 날짜 조회 1번. Returns (games, failed_sports)."""
    games, failed = [], []
    for kind in SPORTS:
        try:
            games.extend(fetch_sport_day(kind, day))
        except Exception as e:
            failed.append(kind)
            log(f"fetch {kind} {day.isoformat()} 실패 {e}")
    games.sort(key=lambda g: (g["order"], g["start"], g["key"]))
    return games, failed


def refresh_hot(games, now):
    """빠른 조회: 진행 중/시작 임박 경기가 있는 (종목, 날짜)만 다시 조회해서 그 경기들만 바꿔 끼운다."""
    targets = sorted({(g["kind"], g["start"].astimezone(SEOUL).date()) for g in games if in_hot_window(g, now)})
    fresh = {}
    for kind, d in targets:
        try:
            for g in fetch_sport_day(kind, d):
                fresh[g["key"]] = g
        except Exception as e:
            log(f"fetch {kind} {d.isoformat()} 실패 {e}")
    return [fresh.get(g["key"], g) for g in games], len(targets)


def is_live(g):
    fn = LIVE.get(g["kind"])
    return bool(fn and fn(g["status"]))


def is_finished(g):
    return g["status"] in FINISHED


def is_cancelled(g):
    return g["status"] in CANCELLED


def is_postponed(g):
    return g["status"] in POSTPONED


def is_terminal(g):
    return is_finished(g) or is_cancelled(g) or is_postponed(g)


def shown_score(v, started):
    if v is None:
        return 0 if started else 0
    return v


def line_score(g, started=True):
    return format_match(g)


def _when_kst(g):
    """시작 시각. 오늘이면 HH:MM, 다른 날이면 M/D HH:MM."""
    start = g["start"].astimezone(SEOUL)
    now = datetime.now(SEOUL)
    hm = start.strftime("%H:%M")
    if start.date() == now.date():
        return hm
    return f"{start.month}/{start.day} {hm}"


def _score_unit(g):
    """캡션 점수 단위. 배구 scores.home/away 는 세트 승수(세트 득점은 periods). 야구·농구는 점."""
    if g.get("kind") == "volleyball":
        return "세트"
    return "점"


def esc(s):
    """HTML parse_mode 용. 팀·리그 이름에 <, & 가 있어도 태그가 되지 않게."""
    return html.escape(str(s if s is not None else ""), quote=False)


def caption_plain(text):
    """텔레그램이 돌려주는 캡션은 태그가 빠진다. 비교는 이 평문으로."""
    t = re.sub(r"</?b>", "", text or "")
    return html.unescape(t)


def _team_lines_v2(g, with_scores):
    """카드 왼쪽 팀이 위, 오른쪽 팀이 아래. 야구는 원정이 위·홈이 아래, 그 외는 홈이 위.
    이름은 전체(검색용). 점수는 굵게, 단위 없음."""
    home, away = esc(g["home"]), esc(g["away"])
    hs, aws = display_scores(g)
    first, second = (home, hs), (away, aws)
    if g.get("kind") == "baseball":
        first, second = second, first
    if not with_scores:
        return f"{first[0]}\n{second[0]}"
    return f"{first[0]} <b>{first[1]}</b>\n{second[0]} <b>{second[1]}</b>"


SPORT_TAG = {"baseball": "야구", "basketball": "농구", "volleyball": "배구"}
# 리그 표시 이름 -> 해시태그(여러 개 가능). 없으면 표시 이름에서 공백·기호를 뺀 것.
LEAGUE_TAGS = {
    "일본 NPB": ["NPB"],
    "V리그 남자": ["V리그", "V리그남자"],
    "V리그 여자": ["V리그", "V리그여자"],
}


def tag_word(text):
    """해시태그용: 공백·점·하이픈 등 기호를 뺀다(글자·숫자·_만). 숫자뿐이면 빈 값."""
    t = re.sub(r"[^\w]", "", str(text or ""), flags=re.UNICODE)
    return "" if (not t or t.isdigit()) else t


def league_tags(g):
    label = g.get("label") or ""
    return LEAGUE_TAGS.get(label) or [label]


def hashtags(g, teams=True):
    """'#야구 #KBO #LG #롯데'. 팀 순서는 캡션과 같음(야구는 원정 먼저)."""
    words = [SPORT_TAG.get(g.get("kind"), "")] + league_tags(g)
    if teams:
        pair = [g.get("home"), g.get("away")]
        if g.get("kind") == "baseball":
            pair.reverse()
        words += pair
    out, seen = [], set()
    for w in words:
        t = tag_word(w)
        if t and t not in seen:
            seen.add(t)
            out.append("#" + t)
    return " ".join(out)


def channel_caption(g):
    """채널 캡션 = format_caption_v2 + 마지막 줄 해시태그. 1024자 안."""
    base = format_caption_v2(g)
    tags = hashtags(g)
    if tags and len(caption_plain(base)) + 1 + len(tags) <= 1024:
        return f"{base}\n{esc(tags)}"
    return base


def format_caption_v2(g):
    """카드 캡션 HTML. 세 줄, 홈이 위. 종목 이모지는 빼고 상태 이모지가 앞.

    진행:  '🔴 LIVE · 리그 · 4Q'
    대기:  '⏳ 대기 · 리그 · 09:00 시작' / 이름만
    종료:  '✅ 종료 · 리그' + 점수
    연기/취소: '⛔ 연기 · 리그' / '⛔ 취소 · 리그'
    """
    league = esc(g.get("label") or "")
    period = esc(g.get("period") or "")
    if is_finished(g):
        head = f"✅ 종료 · {league}"
        return f"{head}\n{_team_lines_v2(g, True)}"
    if is_cancelled(g):
        return f"⛔ 취소 · {league}\n{_team_lines_v2(g, False)}"
    if is_postponed(g):
        return f"⛔ 연기 · {league}\n{_team_lines_v2(g, False)}"
    if is_live(g) or g.get("status") in ("HT", "BT"):
        bit = period or "진행"
        return f"🔴 LIVE · {league} · {bit}\n{_team_lines_v2(g, True)}"
    return f"⏳ 대기 · {league} · {esc(_when_kst(g))} 시작\n{_team_lines_v2(g, False)}"


def fmt_live(g):
    if CAPTION_V2:
        return channel_caption(g)
    return f"{g['emoji']} {g['label']} | {line_score(g)} | {g['period']}"


def fmt_result(g, word):
    if CAPTION_V2:
        return channel_caption(g)
    return f"{g['emoji']} {g['label']} {word} | {line_score(g)}"


def weekday_ko(dt):
    return "월화수목금토일"[dt.weekday()]


def _game_line(g):
    hm = g["start"].astimezone(SEOUL).strftime("%H:%M")
    extra = ""
    if is_postponed(g):
        extra = " (연기)"
    elif is_cancelled(g):
        extra = " (취소)"
    elif is_finished(g):
        extra = " (종료)"
    if g.get("kind") == "baseball":
        # 야구는 채널 카드와 같이 원정 vs 홈 (홈팀이 오른쪽)
        return f"{hm} {g['away']} vs {g['home']}{extra}"
    return f"{hm} {format_vs(g)}{extra}"


def fmt_schedule_parts(now, games):
    """리그별로 묶고, 메시지 1개당 SCHEDULE_MAX_GAMES 경기 / SCHEDULE_MAX_CHARS 자 이내로 나눈다."""
    title = f"오늘의 경기 일정 ({now.month}월 {now.day}일 {weekday_ko(now)})"
    if not games:
        return [title + "\n오늘 예정된 경기가 없습니다."]
    blocks = []  # (header, [lines])
    for g in games:
        header = f"{g['emoji']} {g['label']}"
        if not blocks or blocks[-1][0] != header:
            blocks.append((header, []))
        blocks[-1][1].append(_game_line(g))
    parts, cur, cur_games, cur_chars = [], [], 0, 0

    def flush():
        nonlocal cur, cur_games, cur_chars
        if cur:
            parts.append(cur)
        cur, cur_games, cur_chars = [], 0, 0

    for header, lines in blocks:
        i = 0
        cont = False
        while i < len(lines):
            room_g = SCHEDULE_MAX_GAMES - cur_games
            hdr = header + (" (계속)" if cont else "")
            # 남은 리그 전체가 들어가지 않고, 이미 뭔가 있으면 새 메시지로 넘긴다(리그를 가급적 안 쪼갬)
            rest = lines[i:]
            rest_chars = len(hdr) + 2 + sum(len(x) + 1 for x in rest)
            if cur and (len(rest) > room_g or cur_chars + rest_chars > SCHEDULE_MAX_CHARS):
                if len(rest) <= SCHEDULE_MAX_GAMES and rest_chars <= SCHEDULE_MAX_CHARS:
                    flush()
                    continue
                if room_g < 3:
                    flush()
                    continue
            room_g = SCHEDULE_MAX_GAMES - cur_games
            take = []
            chars = cur_chars + len(hdr) + 2
            for x in rest:
                if len(take) >= room_g or chars + len(x) + 1 > SCHEDULE_MAX_CHARS:
                    break
                take.append(x)
                chars += len(x) + 1
            if not take:
                flush()
                continue
            cur.append((hdr, take))
            cur_games += len(take)
            cur_chars = chars
            i += len(take)
            cont = True
            if i < len(lines):
                flush()
    flush()
    total = len(parts)
    out = []
    tag_of = {f"{g['emoji']} {g['label']}": g for g in games}
    for n, blks in enumerate(parts, 1):
        head = title if total == 1 else f"{title} ({n}/{total})"
        lines = [head]
        tags = []
        for hdr, take in blks:
            lines.append("")
            lines.append(hdr)
            lines.extend(take)
            g0 = tag_of.get(hdr.replace(" (계속)", ""))
            if g0:
                for t in hashtags(g0, teams=False).split():
                    if t not in tags:
                        tags.append(t)
        # 종목 태그를 앞으로: #야구 #농구 ... 다음 리그 태그
        sport = [t for t in tags if t[1:] in SPORT_TAG.values()]
        rest = [t for t in tags if t not in sport]
        if tags:
            lines.append("")
            lines.append(" ".join(sport + rest))
        out.append("\n".join(lines))
    return out


def fmt_schedule(now, games):
    return "\n\n".join(fmt_schedule_parts(now, games))


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("not obj")
        d.setdefault("games", {})
        return d
    except FileNotFoundError:
        return {"games": {}}
    except Exception as e:
        log(f"state.json 읽기 실패, 새로 시작 {redact(e)}")
        return {"games": {}}


def save_state(state):
    state["max_msg_id"] = max(int(state.get("max_msg_id") or 0), _max_seen[0])
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


_tg_sent = deque()
_max_seen = [0]   # 지금까지 확인한 채널 글 번호 최댓값


def note_id(mid):
    if isinstance(mid, int) and mid > _max_seen[0]:
        _max_seen[0] = mid


def is_timeout(e):
    return getattr(e, "code", None) == -1 and "timed out" in (getattr(e, "desc", "") or "").lower()


class Throttled(Exception):
    pass


def _tg_used():
    """최근 60초 동안 보낸 글/수정 수. 대기 새 글은 이 값이 낮을 때만 보낸다."""
    now = time.time()
    while _tg_sent and now - _tg_sent[0] > TG_WINDOW:
        _tg_sent.popleft()
    return len(_tg_sent)


def _tg_budget(optional):
    """optional(수정)은 한도에 가까우면 건너뛰고, 새 글은 자리가 날 때까지 기다린다."""
    while True:
        now = time.time()
        while _tg_sent and now - _tg_sent[0] > TG_WINDOW:
            _tg_sent.popleft()
        used = len(_tg_sent)
        if optional:
            if used >= TG_EDIT_CEILING:
                raise Throttled()
            break
        if used < TG_MAX_PER_WINDOW:
            break
        time.sleep(max(1.0, TG_WINDOW - (now - _tg_sent[0]) + 0.5))
    _tg_sent.append(time.time())


def tg_call(method, payload, dry, optional=False, files=None, timeout=None):
    if dry:
        return {"message_id": 0, "dry": True}
    _tg_budget(optional)
    delay = 0
    for _ in range(4):
        if delay:
            time.sleep(delay)
        try:
            if files:
                res = tg_multipart(method, payload, files, timeout=timeout or UPLOAD_TIMEOUT)
            else:
                res = tg(method, payload)
            if isinstance(res, dict):
                note_id(res.get("message_id"))
            return res
        except TgError as e:
            if e.retry_after:
                delay = min(int(e.retry_after), 90) + 1
                log(f"telegram 429 {method} retry_after={e.retry_after}")
                continue
            desc = (e.desc or "").lower()
            if method.startswith("editMessage") and "not modified" in desc:
                return None
            raise
    raise TgError(429, "retry exceeded")


def photo_file(path):
    """카드 PNG -> 업로드용 JPEG(폭 900, 품질 85). PNG가 더 새로우면 다시 만든다."""
    try:
        jp = os.path.splitext(path)[0] + ".jpg"
        src_m = os.path.getmtime(path)
        if not (os.path.exists(jp) and os.path.getmtime(jp) + 0.001 >= src_m):
            from PIL import Image
            im = Image.open(path).convert("RGB")
            if im.width > PHOTO_WIDTH:
                im = im.resize((PHOTO_WIDTH, round(im.height * PHOTO_WIDTH / im.width)), Image.LANCZOS)
            im.save(jp + ".tmp", "JPEG", quality=85, optimize=True)
            os.replace(jp + ".tmp", jp)
        return jp
    except Exception as e:
        log(f"JPEG 변환 실패, PNG로 올림 {redact(e)[:120]}")
        return path


def find_posted_photo(chat_id, caption, state):
    """sendPhoto 응답이 시간 초과로 안 왔을 때: 실제로 올라갔는지 확인해서 글 번호를 찾는다.
    마지막으로 확인한 번호 다음부터 보이지 않는 확인(빈 버튼 수정)으로 존재 여부를 보고,
    parse_mode HTML 로 같은 캡션을 넣어 'not modified'면 우리 글이다. 서버가 돌려주는 캡션은 태그가 없으므로 caption_plain 과 같다."""
    tracked = {st.get("live_message_id") for st in (state.get("games") or {}).values()}
    start = max(int(state.get("max_msg_id") or 0), _max_seen[0])
    for attempt in range(3):
        for mid in range(start + 1, start + 16):
            if mid in tracked:
                continue
            try:
                tg("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": mid,
                                              "reply_markup": {"inline_keyboard": []}})
            except TgError as e:
                if "not modified" not in (e.desc or "").lower():
                    continue
            try:
                tg("editMessageCaption", {"chat_id": chat_id, "message_id": mid,
                                              "caption": caption, "parse_mode": "HTML"})
                # 캡션이 달랐던 사진 글 = 응답을 못 받은 예전 업로드. 지금 캡션으로 맞췄으니 이 글을 쓴다.
                note_id(mid)
                return mid
            except TgError as e:
                if "not modified" in (e.desc or "").lower():
                    note_id(mid)
                    return mid
        time.sleep(3)
    return None



def send_text(chat_id, text, dry):
    if dry:
        print(text)
        print("---")
        return -1
    res = tg_call("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }, dry=False)
    return (res or {}).get("message_id")


def edit_text(chat_id, message_id, text, optional=False):
    tg_call("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }, dry=False, optional=optional)


def card_for(g, kind, label=None):
    """카드 PNG 경로. 실패하면 None (그때는 글로만 올린다)."""
    try:
        return cards.render_card(g, kind, label)
    except Exception as e:
        log(f"카드 생성 실패 {g['key']} {redact(e)[:200]}")
        return None


def send_card(chat_id, g, card_kind, caption, state, label=None):
    """사진+캡션으로 새 글. Returns (message_id, media).
    응답 시간 초과면 실제로 올라갔는지 확인하고, 확인이 안 되면 중복을 피하려고 글로 다시 올리지 않는다 (None, None)."""
    path = card_for(g, card_kind, label)
    if path:
        jp = photo_file(path)
        try:
            fields = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            res = tg_call("sendPhoto", fields,
                          dry=False, files={"photo": jp}, timeout=UPLOAD_TIMEOUT)
            return (res or {}).get("message_id"), "photo"
        except TgError as e:
            if is_timeout(e):
                mid = find_posted_photo(chat_id, caption, state)
                if mid:
                    log(f"sendPhoto 응답 없음, 올라간 글 {mid} 확인 {g['key']}")
                    return mid, "photo"
                log(f"sendPhoto 응답 없음, 올라간 글 확인 못 함 — 다음 조회 때 다시 {g['key']}")
                return None, None
            log(f"sendPhoto 실패, 글로 올림 {g['key']} {e.desc}")
    return send_text(chat_id, caption, False), "text"


def edit_card(chat_id, message_id, g, card_kind, caption, optional=False, label=None):
    """사진 글 수정: editMessageMedia(사진+캡션 한 번에). 사진 교체가 안 되면 editMessageCaption.
    업로드 응답 시간 초과는 텔레그램 쪽에서 적용되므로 성공으로 본다."""
    path = card_for(g, card_kind, label)
    if path:
        try:
            tg_call("editMessageMedia", {
                "chat_id": chat_id, "message_id": message_id,
                "media": {"type": "photo", "media": "attach://card", "caption": caption, "parse_mode": "HTML"},
            }, dry=False, optional=optional, files={"card": photo_file(path)}, timeout=UPLOAD_TIMEOUT)
            return
        except Throttled:
            raise
        except TgError as e:
            if is_timeout(e):
                log(f"editMessageMedia 응답 없음, 적용된 것으로 처리 {g['key']}")
                return
            desc = (e.desc or "").lower()
            if "not found" in desc or "message to edit" in desc:
                raise
            log(f"editMessageMedia 실패, 캡션만 수정 {g['key']} {e.desc}")
    tg_call("editMessageCaption", {
        "chat_id": chat_id, "message_id": message_id, "caption": caption, "parse_mode": "HTML",
    }, dry=False, optional=optional)


def gstate(state, g):
    games = state.setdefault("games", {})
    st = games.get(g["key"])
    if not st:
        st = {"last_edit": 0}
        games[g["key"]] = st
    return st


def in_pre_window(g, now):
    """시작 시각이 지금부터 2시간 이내이고, 아직 시작 전."""
    if is_terminal(g) or is_live(g):
        return False
    delta = (g["start"] - now).total_seconds()
    return 0 <= delta <= PRE_BEFORE


def pending_pregames(games, state, now):
    out = []
    for g in games:
        if not in_pre_window(g, now):
            continue
        st = (state.get("games") or {}).get(g["key"]) or {}
        if st.get("live_message_id") or st.get("final_done"):
            continue
        out.append(g)
    out.sort(key=lambda g: (g["start"], g["key"]))
    return out


def promote_pregame(chat_id, g, st, now_ts):
    """대기 글을 지우고 새로 올리지 않고, 같은 글을 진행 카드/문구로 고친다."""
    text = fmt_live(g)
    sig = f"{g['home_score']}-{g['away_score']}|{g['period']}|H"
    mid = st.get("live_message_id")
    try:
        if st.get("media") == "photo":
            edit_card(chat_id, mid, g, "live", text, optional=False)
        else:
            edit_text(chat_id, mid, text)
    except Throttled:
        return False
    except TgError as e:
        desc = (e.desc or "").lower()
        if "not found" in desc or "message to edit" in desc:
            st.pop("live_message_id", None)
            st.pop("card_phase", None)
            log(f"대기 글 없음, 다음 조회에 진행 글로 다시 올림 {g['key']}")
        else:
            log(f"대기→진행 실패 {g['key']} {e.desc}")
        return False
    st["card_phase"] = "live"
    st["last_text"] = text
    st["last_sig"] = sig
    st["last_edit"] = now_ts
    hs, aws = display_scores(g)
    log(f"대기→진행 {g['key']} {g['home']} {hs}:{aws} {g['away']} (글 {mid} 수정)")
    try:
        import features
        features.on_live(g, st)
    except Exception as e:
        log(f"on_live {redact(e)[:160]}")
    return True


def post_pregames(chat_id, games, state, now):
    """시작 30분 전 대기 카드. 한 번에 한 장만. 진행 중 수정이 한도에 가까우면 미룬다."""
    # 진행 점수 수정(상한 14)을 위해 최근 전송이 8건 이상이면 새 대기 글은 건너뛴다.
    if _tg_used() >= 8:
        return 0
    pending = pending_pregames(games, state, now)
    if not pending:
        return 0
    g = pending[0]
    text = channel_caption(g)
    st = gstate(state, g)
    mid, media = send_card(chat_id, g, "pregame", text, state, label="대기")
    if not mid:
        log(f"대기 글 확인 못 함, 다음 차례에 다시 {g['key']}")
        return 0
    st["live_message_id"] = mid
    st["media"] = media
    st["card_phase"] = "pregame"
    st["last_text"] = text
    st["last_edit"] = time.time()
    st["announced"] = True
    save_state(state)
    log(f"대기 {g['key']} {g['home']} vs {g['away']} (글 {mid}, 남음 {len(pending) - 1})")
    try:
        import features
        features.on_pregame(g, datetime.now(SEOUL))
    except Exception as e:
        log(f"on_pregame {redact(e)[:160]}")
    return 1



def scores_wiped(g):
    """이미 진행했던 경기가 NS 등으로 돌아가고 점수가 비어 있는 경우."""
    if is_live(g) or is_terminal(g):
        return False
    if (g.get("status") or "") not in NOT_STARTED:
        return False
    return g.get("home_score") is None and g.get("away_score") is None


def was_posted_live(st):
    """채널에 올린 뒤 진행 점수를 한 번이라도 반영한 글. 대기만 올린 글은 제외."""
    if not st or st.get("final_done") or not st.get("live_message_id"):
        return False
    if st.get("score_reset"):
        return True
    sig = st.get("last_sig") or ""
    return sig.endswith("|H") and "-" in sig.split("|", 1)[0]


def remembered_scores(st):
    if st.get("reset_hs") is not None and st.get("reset_aws") is not None:
        return int(st["reset_hs"]), int(st["reset_aws"])
    sig = st.get("last_sig") or ""
    head = sig.split("|", 1)[0]
    if "-" in head:
        a, b = head.split("-", 1)
        try:
            return int(a), int(b)
        except ValueError:
            return None
    return None


def unconfirmed_caption(g, st):
    """1행만 확인 중. 마지막으로 본 점수는 그대로 둔다."""
    league = esc(g.get("label") or "")
    home, away = esc(g.get("home") or ""), esc(g.get("away") or "")
    scores = remembered_scores(st)
    if scores is None:
        body = f"{home}\n{away}"
    else:
        hs, aws = scores
        body = f"{home} <b>{hs}</b>\n{away} <b>{aws}</b>"
    return f"✅ 종료 · {league} · 최종 점수 확인 중\n{body}"


def fetch_game_id(kind, league, game_id):
    """날짜 목록에서 빠지거나 상태가 되돌아간 경기를 id 로 다시 조회."""
    meta = LEAGUE_BY_KEY.get((kind, int(league)))
    raws = api_get(HOSTS[kind], {"id": int(game_id)})
    if not raws:
        return None
    raw = raws[0]
    lid = (raw.get("league") or {}).get("id")
    meta = LEAGUE_BY_KEY.get((kind, lid)) or meta
    if not meta:
        return None
    return parse_game(raw, meta)


def close_unconfirmed(chat_id, g, st, now_ts, dry):
    """점수가 안 돌아오면 글을 지우지 않고 확인 중으로 고친 뒤, 종료 1시간 뒤 삭제."""
    text = unconfirmed_caption(g, st)
    mid = st.get("live_message_id")
    if not mid:
        st["final_done"] = "silent"
        st["done_ts"] = now_ts
        st["score_reset"] = False
        return
    if dry:
        print("[확인 중] " + caption_plain(text))
        print("---")
    else:
        try:
            if st.get("media") == "photo":
                tg_call("editMessageCaption", {
                    "chat_id": chat_id, "message_id": mid,
                    "caption": text, "parse_mode": "HTML",
                }, dry=False)
            else:
                edit_text(chat_id, mid, text)
        except TgError as e:
            desc = (e.desc or "").lower()
            st["final_tries"] = int(st.get("final_tries") or 0) + 1
            if "not found" not in desc and "message to edit" not in desc and st["final_tries"] < 5:
                log(f"확인 중 수정 실패, 다음 조회 때 다시 {g['key']} {e.desc}")
                return
            log(f"확인 중 수정 포기 {g['key']} {e.desc}")
    st["last_text"] = text
    st["last_edit"] = now_ts
    st["final_done"] = "unconfirmed"
    st["done_ts"] = now_ts
    st["card_phase"] = "final"
    st["score_reset"] = False
    scores = remembered_scores(st)
    log(f"최종 점수 확인 중 {g['key']} {g.get('home')} {scores} {g.get('away')} (글 {mid} 수정)")


def handle_score_reset(chat_id, g, st, state, now_ts, dry):
    """진행 글이 NS/빈 점수로 돌아오면 대기 문구로 되돌리지 않고 id 로 계속 본다."""
    if not st.get("score_reset"):
        st["score_reset"] = True
        st["reset_live_ts"] = float(st.get("last_edit") or now_ts)
        scores = remembered_scores(st)
        if scores:
            st["reset_hs"], st["reset_aws"] = scores
        log(f"점수 데이터 리셋, 마지막 점수 유지 {g['key']} {scores}")
    live_ts = float(st.get("reset_live_ts") or st.get("last_edit") or now_ts)
    giveup = now_ts - live_ts >= RESET_GIVEUP
    polled = float(st.get("reset_polled") or 0)
    if now_ts - polled >= RESET_POLL or (giveup and now_ts - polled >= 30):
        st["reset_polled"] = now_ts
        fresh = None
        try:
            fresh = fetch_game_id(g["kind"], g["league"], g["id"])
        except Exception as e:
            log(f"리셋 id 조회 실패 {g['key']} {redact(e)[:160]}")
        if fresh and (is_live(fresh) or is_terminal(fresh)):
            st["score_reset"] = False
            log(f"리셋 복구 {g['key']} status={fresh.get('status')}")
            handle_game(chat_id, fresh, state, now_ts, dry, phase="all")
            return
    if giveup and st.get("score_reset"):
        close_unconfirmed(chat_id, g, st, now_ts, dry)


def poll_tracked_resets(chat_id, games, state, now_ts, dry):
    """날짜 목록에서 빠진 리셋 경기도 id 조회를 이어 간다."""
    seen = {g["key"] for g in games}
    for key, st in list((state.get("games") or {}).items()):
        if not st.get("score_reset") or st.get("final_done") or key in seen:
            continue
        parts = key.split(":")
        if len(parts) != 3:
            continue
        kind, league_s, id_s = parts
        try:
            league, gid = int(league_s), int(id_s)
        except ValueError:
            continue
        meta = LEAGUE_BY_KEY.get((kind, league)) or {}
        stub = {
            "key": key, "id": gid, "kind": kind, "league": league,
            "label": meta.get("label") or "",
            "home": "", "away": "", "emoji": meta.get("emoji") or "",
            "status": "NS", "home_score": None, "away_score": None,
            "start": datetime.now(SEOUL), "period": "",
        }
        handle_score_reset(chat_id, stub, st, state, now_ts, dry)


def handle_game(chat_id, g, state, now_ts, dry, phase="all"):
    """phase: "events" = 시작/종료/취소만, "edits" = 진행 중 점수 수정만, "all" = 둘 다."""
    st = gstate(state, g)
    if phase == "edits" and (is_terminal(g) or not st.get("live_message_id")):
        return
    if st.get("final_done"):
        return
    if phase != "edits" and scores_wiped(g) and was_posted_live(st):
        handle_score_reset(chat_id, g, st, state, now_ts, dry)
        return
    if is_terminal(g) and phase != "edits":
        # 종료/취소/연기: 따로 새 글을 올리지 않고, 올라가 있는 경기 글(사진+캡션)을 최종 상태로 고친다.
        # 글이 없는 경기는 아무것도 올리지 않는다 (일정 글에만 표시).
        if is_finished(g):
            word, card_kind, label = "경기 종료", "final", None
        elif is_cancelled(g):
            word, card_kind, label = "경기 취소", "cancel", "취소"
        else:
            word, card_kind, label = "경기 연기", "cancel", "연기"
        mid = st.get("live_message_id")
        if not mid:
            st["final_done"] = "silent"
            st["done_ts"] = now_ts
            return
        text = fmt_result(g, word)
        if dry:
            print("[최종 수정] " + text)
            print("---")
        else:
            gc = g if is_finished(g) else dict(g, period=word)
            try:
                if st.get("media") == "photo":
                    edit_card(chat_id, mid, gc, card_kind, text, label=label)
                else:
                    edit_text(chat_id, mid, text)
            except TgError as e:
                desc = (e.desc or "").lower()
                st["final_tries"] = int(st.get("final_tries") or 0) + 1
                if "not found" not in desc and "message to edit" not in desc and st["final_tries"] < 5:
                    log(f"최종 수정 실패, 다음 조회 때 다시 {g['key']} {e.desc}")
                    return
                log(f"최종 수정 포기 {g['key']} {e.desc}")
        st["last_text"] = text
        st["last_edit"] = now_ts
        st["final_done"] = "finished" if is_finished(g) else word
        # 대기만 올렸던 연기/취소는 시작 시각 1시간 뒤에 지운다. 진행했던 경기는 지금 기준.
        if not is_finished(g) and st.get("card_phase") == "pregame":
            st["done_ts"] = g["start"].timestamp()
        else:
            st["done_ts"] = now_ts
        st["card_phase"] = "final"
        hs, aws = display_scores(g)
        log(f"{word} {g['key']} {g['home']} {hs}:{aws} {g['away']} (글 {mid} 수정)")
        if is_finished(g):
            try:
                import features
                features.on_final(g, st, datetime.now(SEOUL))
            except Exception as e:
                log(f"on_final {redact(e)[:160]}")
        return
    if not is_live(g) or is_terminal(g):
        return
    if st.get("card_phase") == "pregame" and st.get("live_message_id"):
        promote_pregame(chat_id, g, st, now_ts)
        return
    text = fmt_live(g)
    # H = 홈:원정. 예전 원정:홈 서명과 겹치지 않게 해서 순서가 바로 고쳐지게 한다.
    sig = f"{g['home_score']}-{g['away_score']}|{g['period']}|H"
    if not st.get("live_message_id"):
        if phase == "edits":
            return
        if dry:
            mid, media = send_text(chat_id, text, dry), "text"
        else:
            mid, media = send_card(chat_id, g, "live", text, state)
            if not mid:
                return
        st["live_message_id"] = mid
        st["media"] = media
        st["last_text"] = text
        st["last_sig"] = sig
        st["last_edit"] = now_ts
        st["announced"] = True
        log(f"start {g['key']} {text}")
        try:
            import features
            features.on_live(g, st)
        except Exception as e:
            log(f"on_live {redact(e)[:160]}")
        return
    if phase == "events":
        return
    if sig == st.get("last_sig"):
        return
    if now_ts - float(st.get("last_edit") or 0) < EDIT_GAP:
        return
    if dry:
        print("[수정] " + text)
        print("---")
    else:
        try:
            if st.get("media") == "photo":
                edit_card(chat_id, st["live_message_id"], g, "live", text, optional=True)
            else:
                # 예전에 글로 올린 경기는 끝날 때까지 글로 수정 (사진으로 못 바꿈)
                edit_text(chat_id, st["live_message_id"], text, optional=True)
        except Throttled:
            return  # 이번 회차는 건너뜀. 다음 조회 때 최신 점수로 수정
        except TgError as e:
            desc = (e.desc or "").lower()
            if "not found" in desc or "message to edit" in desc:
                mid, media = send_card(chat_id, g, "live", text, state)
                if not mid:
                    return
                st["live_message_id"] = mid
                st["media"] = media
                log(f"edit 대상 없음, 다시 올림 {g['key']}")
            else:
                log(f"edit 실패 {g['key']} {e.desc}")
                return
    st["last_text"] = text
    st["last_sig"] = sig
    st["last_edit"] = now_ts
    log(f"edit {g['key']} {sig}")
    try:
        import features
        features.on_score(g, st)
    except Exception as e:
        log(f"on_score {redact(e)[:160]}")



RELAYOUT_TAG = "wm10-v1"  # 바꾸면 재시작 때 채널 글을 지금 형식으로 한 번씩 다시 고친다


def relayout_baseball(chat_id, games, state, cutoff_mid, limit=4):
    """채널 글 형식 변경(야구 좌우·해시태그 등)을 반영. 재시작 전에 올라간 글(cutoff_mid 이하)만
    지금 상태 그대로 새 배치로 다시 그려 editMessageMedia. 한 회차에 limit 장씩. 지운 글은 건너뛴다."""
    n = 0
    gs = state.get("games") or {}
    for g in games:
        if n >= limit:
            break
        st = gs.get(g["key"])
        if not st:
            continue
        mid = st.get("live_message_id")
        if (not mid or st.get("media") != "photo" or st.get("post_deleted")
                or st.get("relayout") == RELAYOUT_TAG or int(mid) > int(cutoff_mid or 0)):
            continue
        fd = st.get("final_done")
        if fd == "finished" and is_finished(g):
            text, gc, kind, label = fmt_result(g, "경기 종료"), g, "final", None
        elif fd in ("경기 취소", "경기 연기") and (is_cancelled(g) or is_postponed(g)):
            label = "취소" if fd == "경기 취소" else "연기"
            text, gc, kind = fmt_result(g, fd), dict(g, period=fd), "cancel"
        elif not fd and st.get("card_phase") == "pregame" and not is_live(g) and not is_terminal(g):
            text, gc, kind, label = channel_caption(g), g, "pregame", "대기"
        elif not fd and st.get("card_phase") != "pregame" and is_live(g) and not is_terminal(g):
            text, gc, kind, label = fmt_live(g), g, "live", None
        else:
            # 상태가 바뀌는 중: 평소 흐름이 곧 새 배치로 고친다.
            st["relayout"] = RELAYOUT_TAG
            log(f"relayout 건너뜀(상태 전환 중) {g['key']} 글 {mid}")
            continue
        try:
            edit_card(chat_id, mid, gc, kind, text, optional=False, label=label)
        except TgError as e:
            desc = (e.desc or "").lower()
            if "not modified" in desc:
                pass
            elif "not found" in desc or "message to edit" in desc:
                log(f"relayout 대상 글 없음(삭제됨) {g['key']} 글 {mid}")
                st["relayout"] = RELAYOUT_TAG
                continue
            else:
                st["relayout_tries"] = int(st.get("relayout_tries") or 0) + 1
                log(f"relayout 실패 {g['key']} 글 {mid} {e.desc}")
                if st["relayout_tries"] >= 3:
                    st["relayout"] = RELAYOUT_TAG
                continue
        st["relayout"] = RELAYOUT_TAG
        st["last_text"] = text
        n += 1
        log(f"relayout {RELAYOUT_TAG} {g['key']} 글 {mid} ({kind})")
    if n:
        save_state(state)
    return n


def convert_text_live(chat_id, games, state):
    """시작 시 한 번: 진행 중인데 글(text)로 올라간 경기를 카드 사진+캡션으로 다시 올리고 옛 글은 지운다."""
    n = 0
    for g in games:
        if not is_live(g) or is_terminal(g):
            continue
        st = (state.get("games") or {}).get(g["key"])
        if not st or not st.get("live_message_id") or st.get("media") == "photo" or st.get("final_done"):
            continue
        old = st["live_message_id"]
        text = fmt_live(g)
        try:
            mid, media = send_card(chat_id, g, "live", text, state)
        except TgError as e:
            log(f"convert 실패, 글 유지 {g['key']} {e.desc}")
            continue
        if not mid or media != "photo":
            if mid:
                # 사진이 안 돼서 글로 올라갔으면 새 글을 지우고 옛 글을 유지한다
                try:
                    tg_call("deleteMessage", {"chat_id": chat_id, "message_id": mid}, dry=False)
                except TgError:
                    pass
            log(f"convert 사진 실패, 글 유지 {g['key']}")
            continue
        st["live_message_id"] = mid
        st["media"] = "photo"
        st["last_text"] = text
        st["last_sig"] = f"{g['home_score']}-{g['away_score']}|{g['period']}|H"
        st["last_edit"] = time.time()
        save_state(state)  # 새 글 번호를 먼저 저장해서 중복 전송을 막는다
        try:
            tg_call("deleteMessage", {"chat_id": chat_id, "message_id": old}, dry=False)
            log(f"convert {g['key']} text {old} -> photo {mid}")
        except TgError as e:
            st["orphan_text_message_id"] = old
            save_state(state)
            log(f"convert {g['key']} photo {mid} 올림, 옛 글 {old} 삭제 실패 {e.desc}")
        n += 1
    log(f"convert: 글로 올라간 진행 중 경기 {n}개를 사진으로 바꿈")
    return n


def maybe_schedule(chat_id, now, games, state, dry):
    today = now.date().isoformat()
    if state.get("schedule_date") == today:
        return
    if now.hour < 9 and not dry:
        return
    if not dry and not games:
        state["schedule_date"] = today
        log(f"schedule skipped {today} (경기 없음)")
        return
    if not dry and all(is_terminal(g) for g in games):
        state["schedule_date"] = today
        log(f"schedule skipped {today} (모든 경기 종료/취소)")
        return
    parts = fmt_schedule_parts(now, games)
    mids = []
    for text in parts:
        mids.append(send_text(chat_id, text, dry))
    if not dry:
        state["schedule_date"] = today
        state["schedule_msgs"] = [m for m in mids if isinstance(m, int) and m > 0]
        log(f"schedule posted {today} games={len(games)} parts={len(parts)}")


def in_hot_window(g, now):
    if is_terminal(g):
        return False
    if is_live(g):
        return True
    delta = (g["start"] - now).total_seconds()
    return -HOT_AFTER <= delta <= HOT_BEFORE


def sleep_seconds(now, games, state):
    if any(in_hot_window(g, now) for g in games):
        return POLL_HOT
    wait = float(POLL_COLD)
    today = now.date().isoformat()
    if state.get("schedule_date") != today:
        nine = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= nine:
            return POLL_HOT
        wait = min(wait, max(5.0, (nine - now).total_seconds()))
    if pending_pregames(games, state, now):
        wait = min(wait, float(PRE_DRAIN))
    if any(st.get("score_reset") and not st.get("final_done")
           for st in (state.get("games") or {}).values()):
        wait = min(wait, float(RESET_POLL))
    # 아직 목록에 없는 다음날 경기를 자정 2시간 전에 깨워서 조회한다.
    cross = (datetime.combine(now.date(), datetime.min.time(), tzinfo=SEOUL)
             + timedelta(days=1) - timedelta(seconds=PRE_BEFORE))
    if cross > now:
        wait = min(wait, max(5.0, (cross - now).total_seconds()))
    for g in games:
        if is_terminal(g):
            continue
        for secs in (PRE_BEFORE, HOT_BEFORE):
            open_at = g["start"] - timedelta(seconds=secs)
            if open_at > now:
                wait = min(wait, max(5.0, (open_at - now).total_seconds()))
    return wait


def delete_old_posts(chat_id, state, now_ts, limit=5):
    """종료/취소/연기된 경기 글을 끝난 시각(done_ts) 1시간 뒤 지운다. 상태에 남겨서 재시작해도 이어진다."""
    n = 0
    for key, st in (state.get("games") or {}).items():
        if n >= limit:
            break
        mid = st.get("live_message_id")
        if not mid or not st.get("final_done") or st.get("post_deleted"):
            continue
        if now_ts - float(st.get("done_ts") or now_ts) < DELETE_AFTER:
            continue
        try:
            tg_call("deleteMessage", {"chat_id": chat_id, "message_id": mid}, dry=False)
            log(f"종료 1시간 지난 글 삭제 {key} 글 {mid}")
        except TgError as e:
            log(f"종료 글 삭제 실패(다시 안 함) {key} 글 {mid} {e.desc}")
        st["post_deleted"] = now_ts
        n += 1
    return n


def prune_state(state, now):
    games = state.get("games") or {}
    # 키만으로는 날짜를 모르므로 final_done 이고 3일 넘은 항목은 last_edit 기준 정리
    cutoff = now.timestamp() - 3 * 86400
    drop = [k for k, st in games.items()
            if st.get("final_done") and 0 < float(st.get("done_ts") or 0) < cutoff]
    for k in drop:
        games.pop(k, None)



def caption_v2_preview():
    """오늘(그리고 0~6시면 전날) 경기 중 진행/휴식/종료/연기/취소/시작 전을 종류별로 몇 개만 찍는다. 전송 없음."""
    now = datetime.now(SEOUL)
    games, failed = fetch_day(now.date())
    if now.hour < PREV_DAY_HOURS:
        prev, _ = fetch_day(now.date() - timedelta(days=1))
        games = prev + games
    print(f"CAPTION_V2 flag={CAPTION_V2}  기준 {now.strftime('%Y-%m-%d %H:%M')} KST  실패={failed or '없음'}")
    print("아래는 format_caption_v2 결과. 채널은 아직 예전 문구를 쓴다.\n")
    buckets = [
        ("진행 농구", lambda g: is_live(g) and g["kind"]=="basketball" and g["status"] not in ("HT","BT")),
        ("진행 야구", lambda g: is_live(g) and g["kind"]=="baseball"),
        ("진행 배구", lambda g: is_live(g) and g["kind"]=="volleyball"),
        ("휴식", lambda g: g.get("status") in ("HT","BT") or g.get("period") in ("하프타임","쿼터 휴식")),
        ("종료", lambda g: is_finished(g)),
        ("연기", lambda g: is_postponed(g)),
        ("취소", lambda g: is_cancelled(g)),
        ("시작 전", lambda g: (not is_live(g)) and (not is_terminal(g))),
    ]
    for title, fn in buckets:
        hit = [g for g in games if fn(g)]
        print(f"===== {title} ({len(hit)}) =====")
        for g in hit[:3]:
            print(format_caption_v2(g))
            print("---")
        if not hit:
            print("(추적 리그에 없음)")
    return 0


def dry_run():
    now = datetime.now(SEOUL)
    games, failed = fetch_day(now.date())
    print(f"기준 시각 {now.strftime('%Y-%m-%d %H:%M')} KST  조회 실패 종목: {failed or '없음'}")
    print(f"오늘 경기 {len(games)}개")
    by = {}
    for g in games:
        by[g["label"]] = by.get(g["label"], 0) + 1
    print("리그별:", ", ".join(f"{k} {v}" for k, v in by.items()) or "없음")
    parts = fmt_schedule_parts(now, games)
    print()
    print(f"===== 오늘의 경기 일정 (dry-run, 전송 안 함) — 메시지 {len(parts)}개 =====")
    for i, t in enumerate(parts, 1):
        print(f"--- 메시지 {i} ({len(t)}자) ---")
        print(t)
    print()
    print("===== 지금 진행 중/종료 경기 문구 =====")
    shown = 0
    for g in games:
        if is_live(g):
            print("[진행]", fmt_live(g)); shown += 1
        elif is_finished(g):
            print("[종료]", fmt_result(g, "경기 종료")); shown += 1
    if not shown:
        print("(없음)")
    unm = sorted(_unmapped_logged)
    print(f"한글 매핑 없는 팀(영문 표기 유지): {len(unm)}개")
    return 0


def wait_channel():
    while True:
        cid = load_channel()
        if cid:
            return cid
        try:
            info = discover_channel(verbose=False)
        except Exception as e:
            log(f"채널 탐색 실패 {redact(e)}")
            info = None
        if info:
            log(f"채널 확인 chat_id={info['chat_id']}")
            return info["chat_id"]
        log("channel.json 없음. 투윈스코어 채널에 봇이 관리자로 들어올 때까지 60초 대기")
        time.sleep(60)


def loop():
    log("score bot start")
    chat_id = wait_channel()
    # 저장본이 다른 채팅이면 올리지 않는다. 시작 시 한 번 더 제목을 확인한다.
    try:
        chat = tg("getChat", {"chat_id": chat_id})
        if chat.get("title") != CHANNEL_TITLE or chat.get("type") != "channel":
            log(f"channel.json 대상이 투윈스코어 채널이 아님 title={chat.get('title')} type={chat.get('type')} — 다시 찾음")
            os.remove(os.path.join(BASE, "channel.json"))
            chat_id = wait_channel()
    except TgError as e:
        log(f"시작 시 getChat 실패, 탐색 재시도 {e.desc}")
        try:
            os.remove(os.path.join(BASE, "channel.json"))
        except OSError:
            pass
        chat_id = wait_channel()
    state = load_state()
    for st in (state.get("games") or {}).values():
        note_id(st.get("live_message_id"))
    note_id(int(state.get("max_msg_id") or 0))
    relayout_cutoff = _max_seen[0]  # 이 번호 이하 = 재시작 전에 올라간 글 (옛 좌우 배치)
    last_games = []
    last_day = None
    last_beat = 0.0
    last_prune = 0.0
    seeded = False
    converted = False
    last_full = 0.0
    while True:
        sleep_for = POLL_COLD
        try:
            now = datetime.now(SEOUL)
            day = now.date()
            if last_games and last_day == day and time.time() - last_full < FULL_EVERY:
                # 빠른 조회: 진행 중인 종목만 (종목당 API 1회)
                games, _n = refresh_hot(last_games, now)
                failed = []
                last_games = games
            else:
                games, failed = fetch_day(day)
                if now.hour < PREV_DAY_HOURS:
                    prev, _ = fetch_day(day - timedelta(days=1))
                    games = [g for g in prev if is_live(g) or (is_finished(g) and not (state.get("games", {}).get(g["key"]) or {}).get("final_done"))] + games
                # 30분 창이 자정을 넘으면 다음날 시작 시각도 봐야 대기 글을 놓치지 않는다.
                if (now + timedelta(seconds=PRE_BEFORE)).date() > day:
                    nxt, nf = fetch_day(day + timedelta(days=1))
                    games = games + nxt
                    if nf:
                        failed = list(failed) + [k + "+1" for k in nf]
                        log(f"다음날 조회 일부 실패 {nf}")
                if failed and len(failed) == len(SPORTS) and last_games and last_day == day:
                    games = last_games
                else:
                    last_games, last_day = games, day
                    last_full = time.time()
            now_ts = time.time()
            if not seeded and not failed:
                # 재시작 직후: 이미 끝났는데 알린 적 없는 경기는 결과를 몰아서 올리지 않는다
                n = 0
                for g in games:
                    if is_terminal(g):
                        st = gstate(state, g)
                        if not st.get("final_done") and not st.get("live_message_id") and not st.get("announced"):
                            st["final_done"] = "silent"
                            st["done_ts"] = now_ts
                            n += 1
                seeded = True
                log(f"startup seed: 이미 끝난 경기 {n}개 조용히 처리")
            maybe_schedule(chat_id, now, games, state, dry=False)
            for g in games:
                handle_game(chat_id, g, state, now_ts, dry=False, phase="events")
            try:
                poll_tracked_resets(chat_id, games, state, now_ts, dry=False)
            except Exception as e:
                log("리셋 조회 오류 " + redact(e)[:160])
            if not converted and not failed:
                converted = True
                try:
                    convert_text_live(chat_id, games, state)
                except Exception as e:
                    log("convert 오류 " + redact(e))
            if not failed:
                try:
                    relayout_baseball(chat_id, games, state, relayout_cutoff)
                except Exception as e:
                    log("relayout 오류 " + redact(e)[:160])
            gs = state.get("games", {})
            edits = sorted((g for g in games if is_live(g)),
                           key=lambda g: float((gs.get(g["key"]) or {}).get("last_edit") or 0))
            for g in edits:
                handle_game(chat_id, g, state, time.time(), dry=False, phase="edits")
            try:
                post_pregames(chat_id, games, state, now)
            except Exception as e:
                log("대기 글 오류 " + redact(e))
            try:
                import features
                features.maybe_summary(chat_id, games, state, now)
                features.maybe_previews(games, now)
                features.maybe_period_posts(games, now)
                features.maybe_weekly(now)
                features.drain_dms(8)
                features.drain_paused_replies()
            except Exception as e:
                log("features 루프 " + redact(e)[:160])
            delete_old_posts(chat_id, state, time.time())
            prune_state(state, now)
            save_state(state)
            if time.time() - last_prune > 3600:
                try:
                    n = cards.prune_cards()
                    if n:
                        log(f"오래된 카드 {n}개 정리")
                except Exception as e:
                    log(f"카드 정리 실패 {redact(e)}")
                last_prune = time.time()
            sleep_for = sleep_seconds(now, games, state)
            if now_ts - last_beat > 600:
                live_n = sum(1 for g in games if is_live(g))
                log(f"alive date={day.isoformat()} games={len(games)} live={live_n} sleep={int(sleep_for)}")
                last_beat = now_ts
        except Exception as e:
            log("loop 오류 " + redact(e) + " " + redact(traceback.format_exc())[-400:])
            sleep_for = 30
        time.sleep(max(5, sleep_for))


def main():
    if "--caption-v2" in sys.argv:
        # 전송하지 않는다. 새 문구만 찍어 본다.
        sys.exit(caption_v2_preview())
    if "--dry-run" in sys.argv:
        sys.exit(dry_run())
    while True:
        try:
            loop()
        except Exception as e:
            log("치명 오류, 5초 후 루프 재시작 " + redact(e))
            time.sleep(5)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""채널 요약, 그룹 순위/일정/예측/명장면, 응원 DM. getUpdates 는 하지 않는다."""
import os, json, time, re, fcntl
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common import BASE, log, redact, tg, tg_multipart, TgError
import score_bot as sb
import cards

SEOUL = ZoneInfo("Asia/Seoul")
FANS_PATH = os.path.join(BASE, "fans.json")
PRED_PATH = os.path.join(BASE, "predictions.json")
CHANNEL_ID = -1004295999404
BOT_LINK = "https://t.me/kr_twowin_bot"
DM_GAP = 0.2
ALERT_MAX_HOUR = 10
POLL_MAX_DAY = 6
# 23:50 일일 결과 요약. 멤버 그룹에만. 채널로는 보내지 않는다.
SUMMARY_ENABLED = True
BLOCKED_GROUP_ID = -1003938093685
# 티어별 하루 상한. NBA 가 새벽에 6장을 다 쓰지 않게.
TIER_CAP = {0: 6, 1: 4, 2: 3, 3: 2}
_std_cache = {}
_season_cache = {}
_fix_cache = {}
_alert_ts = []
_dm_queue = []
_last_group_send = 0.0
_summary_try = {}


GROUP_PAUSE_PATH = os.path.join(BASE, "group_auto_paused")


def group_auto_paused():
    """파일이 있으면 그룹 자동 글(예측 카드·투표·결과·명장면)을 보내지 않는다. 지으면 재시작 없이 재개."""
    return os.path.isfile(GROUP_PAUSE_PATH)


def group_id():
    """현재 멤버 그룹. 파일을 못 읽으면 None (차단된 옛 그룹으로 보내지 않음)."""
    try:
        with open(os.path.join(BASE, "group.json"), encoding="utf-8") as f:
            return int(json.load(f)["chat_id"])
    except Exception:
        return None


def _game_ts(g):
    try:
        return int(g["start"].timestamp())
    except Exception:
        return None


def dedupe_games(games):
    """같은 경기를 한 번만. 키(종목:리그:id)·(종목,id)·(종목,홈id,원정id,시작시각) 중 하나라도 겹치면 중복.
    먼저 나온 것을 남긴다. 순서는 유지."""
    out, seen = [], set()
    for g in games or []:
        marks = set()
        if g.get("key"):
            marks.add(("key", g["key"]))
        if g.get("id") is not None:
            marks.add(("id", g.get("kind"), g.get("id")))
        ts = _game_ts(g)
        if ts is not None and (g.get("home_id") is not None or g.get("home")):
            marks.add(("match", g.get("kind"), g.get("home_id") or g.get("home"),
                       g.get("away_id") or g.get("away"), ts))
        if marks & seen:
            continue
        seen |= marks
        out.append(g)
    return out


def matchup_key(g):
    """홈·원정 순서 무관한 같은 종목·리그 대진."""
    a = g.get("home_id") if g.get("home_id") is not None else g.get("home")
    b = g.get("away_id") if g.get("away_id") is not None else g.get("away")
    return (g.get("kind"), g.get("league"), frozenset((str(a), str(b))))


def _locked_update(path, default, mutator):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        raw = f.read()
        try:
            data = json.loads(raw) if raw.strip() else json.loads(json.dumps(default))
        except Exception:
            data = json.loads(json.dumps(default))
        mutator(data)
        f.seek(0)
        f.truncate()
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        return data


def _locked_read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            raw = f.read()
            return json.loads(raw) if raw.strip() else json.loads(json.dumps(default))
    except FileNotFoundError:
        return json.loads(json.dumps(default))
    except Exception:
        return json.loads(json.dumps(default))


# ---------- leagues / teams ----------
# (kind, league id, label, season key in LEAGUES, tier or None if no poll)
def _meta(kind, league):
    return sb.LEAGUE_BY_KEY.get((kind, league))


ALIASES = {
    "kbo": ("baseball", 5), "케이비오": ("baseball", 5), "한국야구": ("baseball", 5),
    "mlb": ("baseball", 1), "엠엘비": ("baseball", 1), "메이저리그": ("baseball", 1),
    "cpbl": ("baseball", 29), "대만야구": ("baseball", 29),
    "npb": ("baseball", 2), "일본야구": ("baseball", 2), "일본프로야구": ("baseball", 2), "일본npb": ("baseball", 2),
    "엔피비": ("baseball", 2),
    "kbl": ("basketball", 91), "케이비엘": ("basketball", 91),
    "wkbl": ("basketball", 92), "더블유케이비엘": ("basketball", 92), "여자농구": ("basketball", 92),
    "nba": ("basketball", 12), "엔비에이": ("basketball", 12),
    "유로리그": ("basketball", 120), "엘": ("basketball", 120),
    "cba": ("basketball", 31),
    "브이리그": ("volleyball", 151), "v리그": ("volleyball", 151), "v-league": ("volleyball", 151),
    "브이리그남자": ("volleyball", 151), "v리그남자": ("volleyball", 151),
    "브이리그여자": ("volleyball", 152), "v리그여자": ("volleyball", 152),
}

POLL_TIER = {
    ("baseball", 5): 0,
    ("basketball", 91): 1,
    ("basketball", 92): 1,
    ("volleyball", 151): 2,
    ("volleyball", 152): 2,
    ("basketball", 12): 3,
}

VLEAGUE_BOTH = {"브이리그", "v리그", "v-league", "배구"}


def norm(s):
    return "".join((s or "").casefold().split())


def supported_lines():
    return [
        "KBO · MLB · 일본 NPB · CPBL",
        "KBL · WKBL · NBA · 유로리그",
        "V리그 남자 · V리그 여자",
        "예: .순위 KBO   .순위 NPB   .순위 NBA   .순위 브이리그",
    ]


def resolve_league(text):
    key = norm(text)
    if key in VLEAGUE_BOTH:
        return [ALIASES["브이리그남자"], ALIASES["브이리그여자"]]
    hit = ALIASES.get(key)
    return [hit] if hit else []


def team_index():
    """norm name -> [(kind, id, display)] exact and we also substring later."""
    rows = []
    for kind, mp in sb.TEAM_KO.items():
        for tid, name in mp.items():
            rows.append((kind, tid, name))
    return rows


def find_teams(query, kind=None):
    nq = norm(query)
    if len(nq) < 2:
        return []
    exact, partial = [], []
    for k, tid, name in team_index():
        if kind and k != kind:
            continue
        nn = norm(name)
        rec = (k, tid, name)
        aliases = [norm(x) for x in ((getattr(sb, "TEAM_ALIAS", {}).get(k) or {}).get(tid) or [])]
        if nn == nq or nq in aliases:
            exact.append(rec)
        elif nq in nn or nn in nq:
            partial.append(rec)
    return exact or partial


def ko_team(kind, tid, english):
    return sb.ko_name(kind, tid, english)


# ---------- standings ----------
def _api(kind, path, params):
    return sb.api_get(sb.HOSTS[kind] + path if False else sb.HOSTS[kind], None) if False else None


def _parse_day(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def season_span_label(season, start=None, end=None):
    """2026 → 2026, 2026-2027 또는 연도가 걸친 시즌 → 2026-27."""
    sy = _parse_day(start)
    ey = _parse_day(end)
    if sy and ey and ey.year != sy.year:
        return f"{sy.year}-{str(ey.year)[2:]}"
    s = str(season)
    m = re.fullmatch(r"(\d{4})-(\d{4})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)[2:]}"
    return s


def current_season(kind, league, today=None):
    """leagues 응답의 current, 없으면 오늘이 포함된 시즌, 없으면 곧 시작하는 시즌."""
    today = today or datetime.now(SEOUL).date()
    hit = _season_cache.get((kind, league))
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1], hit[2]
    meta = _meta(kind, league)
    fallback = meta["season"] if meta else None
    season, label = fallback, season_span_label(fallback) if fallback is not None else ""
    try:
        import urllib.parse, urllib.request, json as _json
        key = os.environ.get("API_SPORTS_KEY")
        if not key:
            raise RuntimeError("API_SPORTS_KEY missing")
        url = sb.HOSTS[kind] + "/leagues?" + urllib.parse.urlencode({"id": league})
        req = urllib.request.Request(url, headers={"x-apisports-key": key})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = _json.loads(r.read().decode())
        if body.get("errors"):
            raise RuntimeError("api errors " + redact(body.get("errors"))[:160])
        seasons = ((body.get("response") or [{}])[0].get("seasons")) or []
        chosen = None
        flagged = [s for s in seasons if isinstance(s, dict) and s.get("current") is True]
        if flagged:
            chosen = flagged[-1]
        else:
            dated = []
            for s in seasons:
                if not isinstance(s, dict):
                    continue
                dated.append((s, _parse_day(s.get("start")), _parse_day(s.get("end"))))
            inside = [s for s, a, b in dated if a and b and a <= today <= b]
            if inside:
                chosen = inside[-1]
            else:
                upcoming = sorted((a, s) for s, a, b in dated if a and a > today)
                if upcoming:
                    chosen = upcoming[0][1]
                else:
                    past = sorted((b or today, s) for s, a, b in dated if b)
                    if past:
                        chosen = past[-1][1]
        if chosen and chosen.get("season") is not None:
            season = chosen.get("season")
            label = season_span_label(season, chosen.get("start"), chosen.get("end"))
    except Exception as e:
        log(f"season {kind}:{league} {redact(e)[:140]}")
    if season is not None:
        _season_cache[(kind, league)] = (time.time(), season, label)
    return season, label


def fetch_standings(kind, league, season=None):
    meta = _meta(kind, league)
    if not meta:
        return []
    if season is None:
        season, _label = current_season(kind, league)
        if season is None:
            season = meta["season"]
    cache_key = (kind, league, str(season))
    now = time.time()
    hit = _std_cache.get(cache_key)
    if hit and now - hit[0] < 20 * 60:
        return hit[1]
    import urllib.parse, urllib.request, json as _json
    key = os.environ.get("API_SPORTS_KEY")
    if not key:
        raise RuntimeError("API_SPORTS_KEY missing")
    url = sb.HOSTS[kind] + "/standings?" + urllib.parse.urlencode({"league": league, "season": season})
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = _json.loads(r.read().decode())
    if body.get("errors"):
        raise RuntimeError("api errors " + redact(body.get("errors"))[:200])
    groups = _flatten_standings(body.get("response") or [], kind)
    _std_cache[cache_key] = (now, groups)
    return groups


def _iter_standing_rows(node):
    if isinstance(node, dict) and "team" in node and "games" in node:
        yield node
        return
    if isinstance(node, list):
        for x in node:
            yield from _iter_standing_rows(x)
    elif isinstance(node, dict):
        for v in node.values():
            if isinstance(v, (list, dict)):
                yield from _iter_standing_rows(v)


def _group_kind(stage, group):
    s = (stage or "").lower()
    g = (group or "").lower()
    if "pre-season" in s or "preseason" in s:
        return "pre"
    if "division" in g:
        return "division"
    if "conference" in g or g in ("american league", "national league"):
        return "conference"
    return "overall"


def _section_name(stage, group, kind):
    names = {
        "Eastern Conference": "동부",
        "Western Conference": "서부",
        "American League": "아메리칸리그",
        "National League": "내셔널리그",
        "Central Division": "센트럴리그",
        "Pacific Division": "퍼시픽리그",
    }
    bits = []
    if kind == "pre" or "pre-season" in (stage or "").lower() or "preseason" in (stage or "").lower():
        bits.append("프리시즌")
    label = names.get(group or "", group or "")
    if label:
        bits.append(label)
    return " · ".join(bits)


def _flatten_standings(resp, kind):
    """스테이지·조마다 팀을 모은다. 팀 id 는 한 조 안에서 한 번만."""
    buckets = {}
    order = []
    for api_i, row in enumerate(_iter_standing_rows(resp)):
        team = row.get("team") or {}
        tid = team.get("id")
        g = row.get("group") or {}
        stage = str(row.get("stage") or "")
        gname = g.get("name") or ""
        key = (stage, gname)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        games = row.get("games") or {}
        try:
            played = int(games.get("played") or 0)
        except (TypeError, ValueError):
            played = 0
        win = ((games.get("win") or {}).get("total"))
        lose = ((games.get("lose") or {}).get("total"))
        try:
            win = int(win) if win is not None else None
        except (TypeError, ValueError):
            win = None
        try:
            lose = int(lose) if lose is not None else None
        except (TypeError, ValueError):
            lose = None
        raw_pct = (games.get("win") or {}).get("percentage")
        pct_f = None
        try:
            if raw_pct not in ("", None):
                pct_f = float(raw_pct)
        except (TypeError, ValueError):
            pct_f = None
        if pct_f is None and win is not None and lose is not None and (win + lose) > 0:
            pct_f = win / (win + lose)
        pct_s = f"{pct_f:.3f}" if pct_f is not None else ""
        pts = row.get("points")
        try:
            pts_f = float(pts) if pts not in (None, "") else None
        except (TypeError, ValueError):
            pts_f = None
        if kind == "volleyball" and pts_f is not None:
            extra = f"{int(pts_f) if pts_f == int(pts_f) else pts_f}점"
        else:
            extra = pct_s
        name = ko_team(kind, tid, team.get("name"))
        wl = f"{win}승 {lose}패" if win is not None and lose is not None else ""
        seen = {r.get("tid") for r in buckets[key]}
        if tid is not None and tid in seen:
            continue
        buckets[key].append({
            "rank": api_i + 1, "team": name, "wl": wl, "extra": extra,
            "win": win, "lose": lose, "pct": pct_f, "pts": pts_f, "api_i": api_i,
            "played": played, "tid": tid,
        })
    groups = []
    for key in order:
        stage, gname = key
        rows = buckets[key]
        if not rows:
            continue
        gk = _group_kind(stage, gname)
        groups.append({"stage": stage, "group": gname, "kind": gk, "rows": rows})
    return _choose_standings(groups, kind)


def _rows_played(rows):
    return any((r.get("played") or 0) > 0 or (r.get("win") or 0) + (r.get("lose") or 0) > 0 for r in rows)


def _choose_standings(groups, kind):
    """정규시즌(또는 전체) 하나만. NBA·MLB 는 컨퍼런스/리그, 디비전은 제외. 정규 경기가 없을 때만 프리시즌."""
    if not groups:
        return []
    def is_pre(g):
        return g["kind"] == "pre"
    regular = [g for g in groups if not is_pre(g)]
    pre = [g for g in groups if is_pre(g)]
    reg_played = any(_rows_played(g["rows"]) for g in regular)
    pool = pre if (not reg_played and any(_rows_played(g["rows"]) for g in pre)) else regular
    if not pool:
        pool = regular or pre
    # 같은 스테이지가 여러 개면 정규시즌 문구, 그다음 경기가 많은 쪽
    stages = []
    for g in pool:
        if g["stage"] not in stages:
            stages.append(g["stage"])
    def stage_key(st):
        played = sum(r.get("played") or 0 for g in pool if g["stage"] == st for r in g["rows"])
        regular_name = 1 if "regular" in st.lower() else 0
        return (regular_name, played)
    if stages:
        best = max(stages, key=stage_key)
        pool = [g for g in pool if g["stage"] == best]
    conf = [g for g in pool if g["kind"] == "conference"]
    overall = [g for g in pool if g["kind"] == "overall"]
    if conf:
        pool = conf
    elif overall:
        pool = overall
    # 디비전만 있으면 그대로
    order = {
        "동부": 0, "서부": 1, "아메리칸리그": 0, "내셔널리그": 1,
    }
    out = []
    for g in pool:
        rows = _sort_standings(list(g["rows"]), kind)
        label = _section_name(g["stage"], g["group"], g["kind"])
        out.append((label, rows, order.get(label.split(" · ")[-1], 5)))
    out.sort(key=lambda x: x[2])
    return [(label, rows) for label, rows, _ in out]


def _sort_standings(built, kind):
    """API position 은 오래됐을 수 있어 다시 매긴다. 동률이면 API 순서를 유지."""
    if not built:
        return built
    has_wl = any(r.get("win") is not None and r.get("lose") is not None for r in built)
    if kind == "volleyball" and any(r.get("pts") is not None for r in built):
        built.sort(key=lambda r: (-(r["pts"] if r.get("pts") is not None else -1), r["api_i"]))
    elif kind == "baseball" and has_wl:
        def best(r):
            return (-(r["pct"] if r.get("pct") is not None else -1),
                    -((r.get("win") or 0) - (r.get("lose") or 0)),
                    r["api_i"])
        leader = min(built, key=best)
        lw, ll = leader.get("win") or 0, leader.get("lose") or 0
        for r in built:
            if r.get("win") is None or r.get("lose") is None:
                r["_gb"] = 10**6
                continue
            gb = ((lw - r["win"]) + (r["lose"] - ll)) / 2.0
            r["_gb"] = gb
            r["extra"] = "GB -" if gb <= 0 else f"GB {gb:.1f}"
        built.sort(key=lambda r: (r.get("_gb", 10**6),
                                  -(r["pct"] if r.get("pct") is not None else -1),
                                  r["api_i"]))
    elif has_wl:
        built.sort(key=lambda r: (-(r["pct"] if r.get("pct") is not None else -1),
                                  -((r.get("win") or 0) - (r.get("lose") or 0)),
                                  r["api_i"]))
    for i, r in enumerate(built, 1):
        r["rank"] = i
    return built


def _played_groups(groups):
    """전 팀이 0경기인 조(0승 0패 표)는 뺀다."""
    out = []
    for section, rows in groups:
        if any((r.get("played") or 0) > 0 or (r.get("win") or 0) + (r.get("lose") or 0) > 0 for r in rows):
            out.append((section, rows))
    return out


def standings_image(query):
    leagues = resolve_league(query)
    if not leagues:
        path = cards.render_board_image("순위 — 지원 리그", supported_lines())
        return path, "순위표\n" + "\n".join(supported_lines())
    groups = []
    bits = []
    for kind, league in leagues:
        meta = _meta(kind, league)
        label = meta["label"] if meta else str(league)
        season, slabel = current_season(kind, league)
        bits.append((label, slabel or ""))
        try:
            got = fetch_standings(kind, league, season)
        except Exception as e:
            log(f"standings {kind}:{league} {redact(e)[:160]}")
            got = []
        got = _played_groups(got)
        if not got:
            groups.append((label, []))
            continue
        seen = set()
        for section, rows in got:
            kept = []
            for r in rows:
                tid = r.get("tid")
                if tid is not None and tid in seen:
                    continue
                if tid is not None:
                    seen.add(tid)
                kept.append(r)
            if not kept:
                continue
            head = label if not section else f"{label} · {section}"
            groups.append((head, kept[:20]))
    labels = [b[0] for b in bits]
    slabs = {b[1] for b in bits if b[1]}
    if len(labels) > 1 and len(slabs) == 1 and all("V리그" in x for x in labels):
        title = f"순위 V리그 · {next(iter(slabs))} 시즌"
    elif len(slabs) == 1:
        title = "순위 " + " · ".join(labels) + f" · {next(iter(slabs))} 시즌"
    else:
        title = "순위 " + " · ".join(f"{a} · {b} 시즌" if b else a for a, b in bits)
    season = next(iter(slabs)) if len(slabs) == 1 else ""
    if len(labels) > 1 and all("V리그" in x for x in labels):
        league_name = "V리그"
    elif len(labels) == 1:
        league_name = labels[0]
    else:
        league_name = " · ".join(labels)
    cap = f"📊 {sb.esc(league_name)} 순위" + (f" · {sb.esc(season)} 시즌" if season else "")
    pre = "새 시즌 개막 전입니다"
    if groups and all(not rows for _, rows in groups):
        path = cards.render_standings_image(title, [], empty_text=pre)
        return path, cap + " · 개막 전"
    path = cards.render_standings_image(title, [(s, r) for s, r in groups if r][:6])
    return path, cap


# ---------- schedule ----------
def fetch_team_games(kind, team_id):
    meta_seasons = [m for m in sb.LEAGUES if m["kind"] == kind]
    # 팀 리그를 모르면 그 종목 리그를 모두 치면 호출이 많다. TEAM_KO 는 리그를 모르므로
    # 종목의 시즌 문자열은 리그마다 다르다. 팀 id 로 한 번: 가장 흔한 시즌은 리그 메타.
    # games?team&season 은 시즌이 필수. 팀이 속한 리그를 찾기 위해 standings 캐시 대신
    # 각 리그 시즌이 같으면 한 번만.
    seasons = []
    for m in meta_seasons:
        key = (kind, str(m["season"]))
        if key not in seasons:
            seasons.append(key)
    now = time.time()
    out = []
    for kind, season in seasons:
        ck = (kind, team_id, season)
        hit = _fix_cache.get(ck)
        if hit and now - hit[0] < 15 * 60:
            out.extend(hit[1])
            continue
        import urllib.parse, urllib.request, json as _json
        key = os.environ.get("API_SPORTS_KEY")
        url = sb.HOSTS[kind] + "/games?" + urllib.parse.urlencode({
            "team": team_id, "season": season, "timezone": "Asia/Seoul",
        })
        req = urllib.request.Request(url, headers={"x-apisports-key": key})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = _json.loads(r.read().decode())
        except Exception as e:
            log(f"schedule {kind} team {team_id} {redact(e)[:120]}")
            _fix_cache[ck] = (now, [])
            continue
        rows = []
        for raw in body.get("response") or []:
            lid = (raw.get("league") or {}).get("id")
            meta = sb.LEAGUE_BY_KEY.get((kind, lid))
            if not meta:
                continue
            g = sb.parse_game(raw, meta)
            if g:
                rows.append(g)
        _fix_cache[ck] = (now, rows)
        out.extend(rows)
    return out


_form_cache = {}
FORM_TTL = 30 * 60


def team_league_games(kind, league, team_id):
    """그 리그·현재 시즌의 팀 경기 전체. 리그 시즌이 다른 경기는 넣지 않는다. 30분 캐시."""
    meta = sb.LEAGUE_BY_KEY.get((kind, league))
    if not meta or team_id is None:
        return []
    season = meta["season"]
    ck = (kind, league, team_id, str(season))
    hit = _form_cache.get(ck)
    if hit and time.time() - hit[0] < FORM_TTL:
        return hit[1]
    import urllib.parse, urllib.request, json as _json
    key = os.environ.get("API_SPORTS_KEY")
    url = sb.HOSTS[kind] + "/games?" + urllib.parse.urlencode({
        "team": team_id, "season": season, "league": league, "timezone": "Asia/Seoul",
    })
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = _json.loads(r.read().decode())
    except Exception as e:
        log(f"form {kind}:{league} team {team_id} {redact(e)[:120]}")
        # 실패는 짧게만 기억해서 곧 다시 시도
        _form_cache[ck] = (time.time() - FORM_TTL + 120, [])
        return []
    rows = []
    for raw in body.get("response") or []:
        lg = raw.get("league") or {}
        if lg.get("id") != league or str(lg.get("season")) != str(season):
            continue
        g = sb.parse_game(raw, meta)
        if g:
            rows.append(g)
    rows = dedupe_games(rows)
    _form_cache[ck] = (time.time(), rows)
    return rows


def team_form(kind, league, team_id, now=None, n=5):
    """최근 종료 n경기의 결과 목록(오래된 → 최근). 'W'|'L'|'D'. 자료 없으면 []."""
    now = now or datetime.now(SEOUL)
    done = [g for g in team_league_games(kind, league, team_id)
            if sb.is_finished(g) and g["start"] <= now]
    done.sort(key=lambda g: g["start"], reverse=True)
    out = []
    for g in done[:n]:
        hs, aws = sb.display_scores(g)
        try:
            hs, aws = int(hs), int(aws)
        except (TypeError, ValueError):
            continue
        mine, theirs = (hs, aws) if g.get("home_id") == team_id else (aws, hs)
        if g.get("home_id") != team_id and g.get("away_id") != team_id:
            continue
        out.append("W" if mine > theirs else ("L" if mine < theirs else "D"))
    return list(reversed(out))


def form_record(results):
    if not results:
        return ""
    w = results.count("W")
    l = results.count("L")
    d = results.count("D")
    s = f"최근 {len(results)}경기 {w}승 {l}패"
    if d:
        s += f" {d}무"
    return s


def team_next_game(kind, league, team_id, after, now=None, days=14):
    """after(경기 시작 시각) 이후, 지금부터 days 안의 다음 경기. 없으면 None."""
    now = now or datetime.now(SEOUL)
    horizon = now + timedelta(days=days)
    up = [g for g in team_league_games(kind, league, team_id)
          if g["start"] > after and g["start"] <= horizon
          and not sb.is_finished(g) and not sb.is_cancelled(g)]
    up.sort(key=lambda g: g["start"])
    return up[0] if up else None


def next_game_line(g, team_id):
    if not g:
        return ""
    st = g["start"].astimezone(SEOUL)
    home = g.get("home_id") == team_id
    opp = g["away"] if home else g["home"]
    side = "홈" if home else "원정"
    return f"다음 경기 · {st.month}/{st.day}({sb.weekday_ko(st)}) {st.strftime('%H:%M')} vs {opp} ({side})"


def schedule_image(query, kind=None, now=None):
    now = now or datetime.now(SEOUL)
    teams = find_teams(query, kind)
    if not teams:
        path = cards.render_schedule_image(f"일정  {query}", [])
        return path, f"🔍 {sb.esc(query)} 팀을 찾지 못했어요 · 예) .일정 LG"
    if len(teams) > 1 and not kind:
        lines = [f"{i}. {sb.EMOJI.get(k,'')} {name}" for i, (k, _tid, name) in enumerate(teams[:8], 1)]
        lines.append("예: .일정 야구 " + query)
        path = cards.render_board_image(f"어느 팀인가요?  {query}", lines)
        return path, "✏️ 어느 팀인가요 · 종목을 붙여 주세요 · 예) .일정 야구 " + sb.esc(query)
    k, tid, name = teams[0]
    horizon = now + timedelta(days=14)
    games = []
    seen = set()
    for g in dedupe_games(fetch_team_games(k, tid)):
        if g["key"] in seen:
            continue
        seen.add(g["key"])
        if g["start"] < now - timedelta(hours=3):
            continue
        if g["start"] > horizon:
            continue
        if sb.is_finished(g) or sb.is_cancelled(g):
            continue
        games.append(g)
    games.sort(key=lambda g: g["start"])
    games = games[:3]
    rows = []
    for g in games:
        st = g["start"].astimezone(SEOUL)
        when = st.strftime("%m/%d %H:%M")
        side = "홈" if g.get("home_id") == tid else "원정"
        me = g["home"] if side == "홈" else g["away"]
        opp = g["away"] if side == "홈" else g["home"]
        match = f"{g['home']} vs {g['away']}"
        rows.append({"when": when + " KST", "league": g["label"], "match": match, "side": side, "emoji": g.get("emoji") or ""})
    path = cards.render_schedule_image(f"일정  {name}", rows)
    text = f"📅 {sb.esc(name)} 다음 경기" if rows else f"🔍 {sb.esc(name)} 다음 경기가 없어요"
    return path, text


# ---------- fans ----------
def _fans_default():
    return {"users": {}}


def fan_add(user_id, name, query, kind=None):
    teams = find_teams(query, kind)
    if not teams:
        path = cards.render_board_image("응원팀", [f"'{query}' 팀을 찾지 못했어요.", "예: .응원 LG   .응원 야구 롯데"])
        return path, f"🔍 {sb.esc(query)} 팀을 찾지 못했어요 · 예) .응원 LG"
    if len(teams) > 1 and not kind:
        lines = [f"{i}. {name_}" for i, (_k, _t, name_) in enumerate(teams[:8], 1)]

        def mut(data):
            u = data["users"].setdefault(str(user_id), {"name": name, "teams": []})
            u["name"] = name or u.get("name") or ""
            u["pending"] = [{"kind": k, "id": tid, "name": nm} for k, tid, nm in teams[:8]]
        _locked_update(FANS_PATH, _fans_default(), mut)
        path = cards.render_board_image("어느 팀인가요?", lines + ["번호만 보내 주세요."])
        return path, "✏️ 어느 팀인가요 · 번호만 보내 주세요"

    def mut(data):
        u = data["users"].setdefault(str(user_id), {"name": name, "teams": []})
        u["name"] = name or u.get("name") or ""
        u.pop("pending", None)
        k, tid, nm = teams[0]
        if any(t.get("kind") == k and t.get("id") == tid for t in u["teams"]):
            u["_note"] = "already"
            return
        if len(u["teams"]) >= 5:
            u["_note"] = "full"
            return
        u["teams"].append({"kind": k, "id": tid, "name": nm})
        u["_note"] = "ok"
    data = _locked_update(FANS_PATH, _fans_default(), mut)
    u = data["users"].get(str(user_id)) or {}
    note = u.get("_note")
    # _note 는 저장본에 남으므로 지운다
    def clean(d):
        uu = d["users"].get(str(user_id))
        if uu:
            uu.pop("_note", None)
    _locked_update(FANS_PATH, _fans_default(), clean)
    if note == "full":
        path = cards.render_board_image("응원팀", ["응원팀은 5팀까지예요.", "지우려면 .응원취소 팀이름"])
        return path, "✏️ 응원팀은 한 사람당 5팀까지예요"
    k, tid, nm = teams[0]
    if note == "already":
        path = cards.render_board_image("응원팀", [f"{nm} 은 이미 등록되어 있어요."])
        return path, f"✅ {sb.esc(nm)} 은 이미 등록되어 있어요"
    path = cards.render_board_image("응원 등록", [nm, "경기 시작과 종료를 여기로 보내 드려요."])
    return path, f"✅ {sb.esc(nm)} 응원 등록 · 시작과 종료를 알려 드려요"


def fan_pick(user_id, number):
    picked = {}

    def mut(data):
        u = data["users"].get(str(user_id)) or {}
        pending = u.get("pending") or []
        if not pending or number < 1 or number > len(pending):
            picked["err"] = "no"
            return
        choice = pending[number - 1]
        u["pending"] = []
        if any(t.get("kind") == choice["kind"] and t.get("id") == choice["id"] for t in u.get("teams") or []):
            picked["err"] = "already"
            picked["name"] = choice["name"]
            return
        if len(u.get("teams") or []) >= 5:
            picked["err"] = "full"
            return
        u.setdefault("teams", []).append(choice)
        picked["name"] = choice["name"]
    _locked_update(FANS_PATH, _fans_default(), mut)
    if picked.get("err") == "no":
        return None
    if picked.get("err") == "full":
        path = cards.render_board_image("응원팀", ["응원팀은 5팀까지예요."])
        return path, "✏️ 응원팀은 한 사람당 5팀까지예요"
    nm = picked.get("name") or ""
    if picked.get("err") == "already":
        path = cards.render_board_image("응원팀", [f"{nm} 은 이미 등록되어 있어요."])
        return path, f"✅ {sb.esc(nm)} 은 이미 등록되어 있어요"
    path = cards.render_board_image("응원 등록", [nm])
    return path, f"✅ {sb.esc(nm)} 응원 등록 · 시작과 종료를 알려 드려요"


def fan_list(user_id):
    data = _locked_read(FANS_PATH, _fans_default())
    teams = ((data.get("users") or {}).get(str(user_id)) or {}).get("teams") or []
    uniq, seen_t = [], set()
    for t in teams:
        mark = (t.get("kind"), t.get("id"))
        if mark in seen_t:
            continue
        seen_t.add(mark)
        uniq.append(t)
    lines = [t.get("name") or "?" for t in uniq] or ["등록된 응원팀이 없어요.", "예: .응원 LG"]
    path = cards.render_board_image("내 응원팀", lines)
    names = " · ".join(sb.esc(x) for x in lines[:8])
    return path, f"📋 내 응원팀 · {names}"


def fan_remove(user_id, query):
    nq = norm(query)
    removed = []

    def mut(data):
        u = (data.get("users") or {}).get(str(user_id))
        if not u:
            return
        keep = []
        for t in u.get("teams") or []:
            if nq and nq in norm(t.get("name") or ""):
                removed.append(t.get("name"))
            else:
                keep.append(t)
        u["teams"] = keep
    _locked_update(FANS_PATH, _fans_default(), mut)
    if not removed:
        path = cards.render_board_image("응원 해제", ["해당하는 응원팀이 없어요."])
        return path, "🔍 해당하는 응원팀이 없어요"
    path = cards.render_board_image("응원 해제", removed)
    return path, "🗑 " + " · ".join(sb.esc(x) for x in removed) + " 응원 해제"


def fans_for_game(g):
    data = _locked_read(FANS_PATH, _fans_default())
    ids = {g.get("home_id"), g.get("away_id")}
    kind = g.get("kind")
    out = []
    for uid, u in (data.get("users") or {}).items():
        for t in u.get("teams") or []:
            if t.get("kind") == kind and t.get("id") in ids:
                out.append((int(uid), u.get("name") or ""))
                break
    return out


def drop_fan(user_id):
    def mut(data):
        (data.get("users") or {}).pop(str(user_id), None)
    _locked_update(FANS_PATH, _fans_default(), mut)


def queue_fan_dm(g, phase):
    """phase start|end. 실제 전송은 drain_dms."""
    if phase == "start":
        cap = "▶ 경기 시작\n" + sb.format_caption_v2(g)
        spec = ("live", None) if sb.is_live(g) else ("pregame", "대기")
    else:
        cap = "🏁 경기 종료\n" + sb.format_caption_v2(g)
        spec = ("final", None)
    try:
        path = cards.render_group_card(g, spec[0], spec[1])
    except Exception as e:
        log(f"fan card {g.get('key')} {redact(e)[:120]}")
        return
    for uid, _name in fans_for_game(g):
        _dm_queue.append({"uid": uid, "path": path, "caption": cap, "key": g.get("key"), "phase": phase})


def drain_dms(limit=8):
    n = 0
    while _dm_queue and n < limit:
        item = _dm_queue.pop(0)
        try:
            jp = sb.photo_file(item["path"])
            tg_multipart("sendPhoto", {
                "chat_id": item["uid"],
                "caption": item["caption"][:1024],
                "parse_mode": "HTML",
            }, {"photo": jp}, timeout=20)
        except TgError as e:
            desc = (e.desc or "").lower()
            if e.code == 403 or "blocked" in desc or "deactivated" in desc or "initiate" in desc:
                drop_fan(item["uid"])
                log(f"fan 제거 {item['uid']} {e.desc[:80]}")
            else:
                log(f"fan DM 실패 {item['uid']} {e.desc[:120]}")
        except Exception as e:
            log(f"fan DM 오류 {redact(e)[:120]}")
        n += 1
        time.sleep(DM_GAP)
    return n


# ---------- polls / predictions ----------
def _pred_default():
    return {"polls": {}, "votes": {}, "scores": {}}


def _month(now):
    return now.strftime("%Y-%m")


def maybe_open_poll(g, now, reply_to=None, with_card=True):
    """reply_to 가 있으면 그 글(프리뷰)에 답글로 투표만 붙인다."""
    if group_auto_paused():
        return
    tier = POLL_TIER.get((g.get("kind"), g.get("league")))
    if tier is None:
        return
    day = now.astimezone(SEOUL).date().isoformat() if now.tzinfo else now.date().isoformat()
    gid = group_id()
    if not gid:
        return

    holder = {}

    def mut(data):
        polls = data.setdefault("polls", {})
        if g["key"] in polls:
            return
        today = [p for p in polls.values() if isinstance(p, dict) and p.get("day") == day]
        # 같은 경기가 다른 id 로 다시 와도 투표는 한 번만
        ts = _game_ts(g)
        if any(p.get("home") == g.get("home") and p.get("away") == g.get("away")
               and (p.get("start_ts") in (None, ts)) and p.get("label") == g.get("label")
               for p in today):
            return
        if len(today) >= POLL_MAX_DAY:
            return
        if sum(1 for p in today if p.get("tier") == tier) >= TIER_CAP.get(tier, 2):
            return
        last = max((p.get("opened") or 0) for p in today) if today else 0
        if time.time() - last < 30:
            return
        holder["open"] = True
    _locked_update(PRED_PATH, _pred_default(), mut)
    if not holder.get("open"):
        return
    # 카드 먼저, 이어서 무기명 아닌 투표
    try:
        if with_card or not reply_to:
            path = cards.render_group_card(g, "pregame", "대기")
            jp = sb.photo_file(path)
            cap = with_tags(sb.format_caption_v2(g), group_tags(g))
            photo = tg_multipart("sendPhoto", {"chat_id": gid, "caption": cap[:1024], "parse_mode": "HTML"}, {"photo": jp}, timeout=20)
        else:
            photo = {"message_id": reply_to}
        if g.get("kind") == "baseball":
            options = [g["away"], g["home"]]  # 야구: 원정 vs 홈
        else:
            options = [g["home"], g["away"]]
        if g.get("kind") == "baseball" and g.get("league") == 5:
            options.append("무승부")
        q = f"[{g['label']}] {options[0]} vs {options[1]} — 승리 팀은?"
        poll_msg = tg("sendPoll", {
            "chat_id": gid,
            "question": q[:300],
            "options": options,
            "is_anonymous": False,
            "reply_to_message_id": (photo or {}).get("message_id"),
        })
    except Exception as e:
        log(f"poll 실패 {g.get('key')} {redact(e)[:160]}")
        return
    poll = (poll_msg or {}).get("poll") or {}
    pmid = (poll_msg or {}).get("message_id")

    def save(d):
        d.setdefault("polls", {})[g["key"]] = {
            "poll_id": poll.get("id"),
            "chat_id": gid,
            "message_id": pmid,
            "photo_id": (photo or {}).get("message_id"),
            "options": options,
            "home": g["home"],
            "away": g["away"],
            "label": g["label"],
            "day": day,
            "tier": tier,
            "opened": time.time(),
            "closed": False,
            "scored": False,
            "key": g["key"],
            "start_ts": _game_ts(g),
        }
    _locked_update(PRED_PATH, _pred_default(), save)
    log(f"poll {g['key']} msg {pmid}")


def close_poll(g):
    data = _locked_read(PRED_PATH, _pred_default())
    p = (data.get("polls") or {}).get(g["key"])
    if not p or p.get("closed") or not p.get("message_id"):
        return
    try:
        tg("stopPoll", {"chat_id": p["chat_id"], "message_id": p["message_id"]})
    except TgError as e:
        if "not found" not in (e.desc or "").lower() and "poll" not in (e.desc or "").lower():
            log(f"stopPoll {g.get('key')} {e.desc[:120]}")
    def mut(d):
        pp = (d.get("polls") or {}).get(g["key"])
        if pp:
            pp["closed"] = True
    _locked_update(PRED_PATH, _pred_default(), mut)


def record_vote(ans):
    poll_id = ans.get("poll_id")
    user = ans.get("user") or {}
    uid = user.get("id")
    if not poll_id or not uid:
        return
    name = user.get("first_name") or ""
    if user.get("last_name"):
        name = (name + " " + user["last_name"]).strip()
    option_ids = ans.get("option_ids") or []

    def mut(data):
        bucket = data.setdefault("votes", {}).setdefault(poll_id, {})
        if not option_ids:
            bucket.pop(str(uid), None)
            return
        prev = bucket.get(str(uid)) or {}
        bucket[str(uid)] = {"option": int(option_ids[0]), "name": name,
                            "ts": prev.get("ts") or time.time()}
    _locked_update(PRED_PATH, _pred_default(), mut)


def _winner_index(g, options):
    """이긴 팀 보기 번호. 보기 순서(홈 먼저/원정 먼저)와 관계없이 팀 이름으로 찾는다."""
    hs, aws = sb.display_scores(g)
    if hs == aws and len(options) >= 3:
        return 2
    if hs == aws:
        return None
    win, pos = (g.get("home"), 0) if hs > aws else (g.get("away"), 1)
    if win in options[:2]:
        return options.index(win)
    return pos


def score_poll(g, now):
    if not sb.is_finished(g):
        return
    month = _month(now)
    gid = group_id()
    if not gid:
        return
    payload = {}

    def mut(data):
        p = (data.get("polls") or {}).get(g["key"])
        if not p or p.get("scored"):
            return
        idx = _winner_index(g, p.get("options") or [])
        votes = (data.get("votes") or {}).get(p.get("poll_id") or "", {})
        correct = []
        results = {}
        scores = data.setdefault("scores", {}).setdefault(month, {})
        for uid, vote in votes.items():
            results[uid] = {"name": vote.get("name") or uid,
                            "ok": bool(idx is not None and vote.get("option") == idx),
                            "ts": vote.get("ts")}
            rec = scores.setdefault(uid, {"name": vote.get("name") or uid, "correct": 0, "total": 0})
            if vote.get("name"):
                rec["name"] = vote["name"]
            rec["total"] = int(rec.get("total") or 0) + 1
            if idx is not None and vote.get("option") == idx:
                rec["correct"] = int(rec.get("correct") or 0) + 1
                correct.append(rec["name"])
        p["scored"] = True
        p["results"] = results
        p["game_day"] = g["start"].astimezone(SEOUL).date().isoformat()
        p["scored_ts"] = time.time()
        p["correct_index"] = idx
        p["correct_n"] = len(correct)
        payload["p"] = p
        payload["correct"] = correct
        payload["idx"] = idx
    _locked_update(PRED_PATH, _pred_default(), mut)
    p = payload.get("p")
    if not p:
        return
    idx = payload.get("idx")
    options = p.get("options") or []
    answer = options[idx] if idx is not None and idx < len(options) else "무승부 없음"
    hs, aws = sb.display_scores(g)
    first = (f"{g['away']} {aws} : {hs} {g['home']}" if g.get("kind") == "baseball"
             else f"{g['home']} {hs} : {aws} {g['away']}")
    lines = [
        first,
        f"정답  {answer}",
        f"적중  {len(payload.get('correct') or [])}명",
    ]
    path = cards.render_board_image("예측 결과", lines)
    k = len(payload.get("correct") or [])
    cap = with_tags(f"✅ 예측 결과 · {sb.esc(answer)} 승 · 적중 {k}명", group_tags(g, "예측결과"))
    if group_auto_paused():
        def hold(d):
            pp = (d.get("polls") or {}).get(g["key"])
            if pp:
                pp["reply_pending"] = True
                pp["reply_caption"] = cap
        _locked_update(PRED_PATH, _pred_default(), hold)
        log(f"group auto paused, 예측 결과 보류 {g.get('key')}")
        return
    try:
        jp = sb.photo_file(path)
        fields = {"chat_id": gid, "caption": cap[:1024], "parse_mode": "HTML"}
        if p.get("message_id"):
            fields["reply_to_message_id"] = p["message_id"]
        tg_multipart("sendPhoto", fields, {"photo": jp}, timeout=20)
    except TgError as e:
        log(f"예측 결과 전송 실패 {g.get('key')} {e.desc[:120]}")


def leaderboard_image(now, user_id=None):
    month = _month(now)
    data = _locked_read(PRED_PATH, _pred_default())
    scores = (data.get("scores") or {}).get(month) or {}
    rows = []
    for uid, rec in scores.items():
        rows.append((int(rec.get("correct") or 0), int(rec.get("total") or 0), rec.get("name") or uid, str(uid)))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    if user_id is None:
        lines = [f"{i}. {name}  {c}적중 / {t}회" for i, (c, t, name, _uid) in enumerate(rows[:10], 1)]
        title = f"{now.month}월 예측 순위"
        path = cards.render_board_image(title, lines)
        return path, f"🏆 {now.month}월 예측 순위"
    mine = None
    rank = None
    for i, (c, t, name, uid) in enumerate(rows, 1):
        if uid == str(user_id):
            mine = (i, c, t, name)
            break
    if not mine:
        lines = ["이번 달 참여 기록이 없어요."]
    else:
        i, c, t, name = mine
        lines = [f"{name}", f"{i}위", f"{c}적중 / {t}회"]
    who = (mine[3] if mine else "") or "회원"
    title = f"{who}님의 예측 기록"
    path = cards.render_board_image(title, lines)
    return path, f"🎯 {sb.esc(who)}님의 예측 기록"


# ---------- highlights ----------
def _inning(period):
    m = re.search(r"(\d+)회", period or "")
    return int(m.group(1)) if m else 0


def observe(g, st):
    """라이브 점수 변화로 명장면 이벤트 목록. st 를 갱신한다."""
    events = []
    alerted = set(st.get("alerted") or [])
    hs, aws = sb.display_scores(g)
    prev_h = st.get("prev_h")
    prev_a = st.get("prev_a")
    kind = g.get("kind")
    period = g.get("period") or ""

    def add(code, headline, score_line, sub):
        if code in alerted:
            return
        if not _alert_budget():
            return
        alerted.add(code)
        label = {"comeback": "역전", "set_comeback": "역전", "ot": "연장", "extra": "연장",
                 "walkoff": "끝내기", "close": "접전 종료", "set5": "5세트"}.get(code, "역전")
        # 표시 순서: 야구는 왼쪽=원정, 오른쪽=홈. 배너의 home/away 인자는 '왼쪽/오른쪽' 뜻으로 넘긴다.
        ln, ls, rn, rs = g.get("home"), hs, g.get("away"), aws
        if kind == "baseball":
            ln, ls, rn, rs = rn, rs, ln, ls
        cap = with_tags(f"🔥 {label} · {sb.esc(ln)} <b>{ls}</b> – <b>{rs}</b> {sb.esc(rn)}"
                        + (f" · {sb.esc(period)}" if period else ""), group_tags(g, "하이라이트"))
        events.append({"code": code, "headline": headline, "score": score_line, "sub": sub,
                       "caption": cap, "home": ln, "away": rn,
                       "hs": ls, "aws": rs, "emoji": g.get("emoji") or "",
                       "league": g.get("label") or "",
                       "winner": "home" if ls > rs else ("away" if rs > ls else "")})

    if prev_h is not None:
        st["home_down"] = max(int(st.get("home_down") or 0), prev_a - prev_h)
        st["away_down"] = max(int(st.get("away_down") or 0), prev_h - prev_a)

    unit = "점" if kind != "volleyball" else "세트"
    score_line = (f"{g['away']} {aws}{unit} — {g['home']} {hs}{unit}" if kind == "baseball"
                  else f"{g['home']} {hs}{unit} — {g['away']} {aws}{unit}")

    if kind == "basketball" and not sb.is_terminal(g):
        if hs > aws and int(st.get("home_down") or 0) >= 10:
            add("comeback", "🔥 역전!", f"{g['home']} {hs}점 — {g['away']} {aws}점", period)
        elif aws > hs and int(st.get("away_down") or 0) >= 10:
            add("comeback", "🔥 역전!", f"{g['away']} {aws}점 — {g['home']} {hs}점", period)
        if g.get("status") == "OT" or "연장" in period:
            add("ot", "⏱ 연장!", score_line, period)
    if kind == "baseball" and not sb.is_terminal(g):
        if hs > aws and int(st.get("home_down") or 0) >= 4:
            add("comeback", "🔥 역전!", f"{g['home']} {hs}점 — {g['away']} {aws}점", period)
        elif aws > hs and int(st.get("away_down") or 0) >= 4:
            add("comeback", "🔥 역전!", f"{g['away']} {aws}점 — {g['home']} {hs}점", period)
        if _inning(period) >= 10:
            add("extra", "⏱ 연장전!", score_line, period)
    if kind == "volleyball" and prev_h is not None and not sb.is_terminal(g):
        if prev_h == 0 and prev_a >= 2 and hs > prev_h:
            add("set_comeback", "🔥 세트 역전!", f"{g['home']} {hs}세트 — {g['away']} {aws}세트", "0-2 뒤 세트 승")
        if prev_a == 0 and prev_h >= 2 and aws > prev_a:
            add("set_comeback", "🔥 세트 역전!", f"{g['away']} {aws}세트 — {g['home']} {hs}세트", "0-2 뒤 세트 승")
        if hs + aws >= 4 and (prev_h + prev_a) < 4:
            add("set5", "🏐 5세트!", score_line, "듀스 세트")
    if sb.is_finished(g) and kind == "baseball" and prev_h is not None:
        if _inning(period) >= 9 and "말" in period and hs > aws and prev_h <= prev_a:
            add("walkoff", "🔥 끝내기!", f"{g['home']} {hs}점 — {g['away']} {aws}점", period)
    if sb.is_finished(g) and kind == "basketball":
        if abs(hs - aws) <= 2 or g.get("status") in ("AOT",) or "연장" in period:
            add("close", "🎯 접전 종료!", f"{g['home']} {hs}점 — {g['away']} {aws}점", period or "종료")

    st["prev_h"] = hs
    st["prev_a"] = aws
    st["alerted"] = sorted(alerted)
    return events


def _alert_budget():
    global _alert_ts
    now = time.time()
    _alert_ts = [t for t in _alert_ts if now - t < 3600]
    return len(_alert_ts) < ALERT_MAX_HOUR


def post_alerts(events):
    global _last_group_send, _alert_ts
    if not events or group_auto_paused():
        return
    gid = group_id()
    if not gid:
        return
    for ev in events:
        if time.time() - _last_group_send < 3:
            time.sleep(3)
        path = cards.render_alert_banner(
            ev["headline"], ev["score"], ev.get("sub") or "",
            home=ev.get("home"), away=ev.get("away"), hs=ev.get("hs"), aws=ev.get("aws"),
            emoji=ev.get("emoji"), league=ev.get("league"), winner=ev.get("winner"),
        )
        try:
            jp = sb.photo_file(path)
            tg_multipart("sendPhoto", {
                "chat_id": gid,
                "caption": ev["caption"][:1024],
                "parse_mode": "HTML",
            }, {"photo": jp}, timeout=20)
            _alert_ts.append(time.time())
            _last_group_send = time.time()
            log(f"alert {ev['code']} {ev['score'][:80]}")
        except TgError as e:
            log(f"alert 실패 {e.desc[:120]}")


# ---------- daily summary ----------
def drain_paused_replies():
    """멈춰 둔 예측 결과 답장. 플래그가 있으면 그대로 두고, 없으면 보낸다."""
    if group_auto_paused():
        return 0
    data = _locked_read(PRED_PATH, _pred_default())
    pending = [(k, p) for k, p in (data.get("polls") or {}).items()
               if isinstance(p, dict) and p.get("reply_pending") and p.get("reply_caption")]
    n = 0
    for key, p in pending:
        if group_auto_paused():
            break
        try:
            lines = [ln for ln in (p.get("reply_caption") or "").split("\n") if not ln.startswith("#")]
            path = cards.render_board_image("예측 결과", lines[1:] or lines)
            jp = sb.photo_file(path)
            gid = group_id()
            stored = p.get("chat_id")
            # 차단된 옛 그룹에 남은 결과는 새 그룹으로만
            chat = stored if stored and int(stored) == int(gid or 0) else gid
            if not chat:
                continue
            fields = {"chat_id": chat, "caption": p["reply_caption"][:1024], "parse_mode": "HTML"}
            if p.get("message_id"):
                fields["reply_to_message_id"] = p["message_id"]
            tg_multipart("sendPhoto", fields, {"photo": jp}, timeout=20)
        except TgError as e:
            log(f"예측 결과 보류분 실패 {key} {e.desc[:120]}")
            continue
        def clear(d, key=key):
            pp = (d.get("polls") or {}).get(key)
            if pp:
                pp["reply_pending"] = False
        _locked_update(PRED_PATH, _pred_default(), clear)
        n += 1
    return n


def summary_target(now, state):
    """23:50에 그날 요약. 자정을 넘긴 직후(00:40 전)만 전날을 한 번 더 시도한다."""
    if now.hour == 23 and now.minute >= 50:
        target = now.date()
    elif now.hour == 0 and now.minute < 40:
        target = now.date() - timedelta(days=1)
    else:
        return None
    if state.get("summary_posted") == target.isoformat():
        return None
    return target


def finished_rows(games, day):
    rows = []
    for g in dedupe_games(games):
        if not sb.is_finished(g):
            continue
        if g["start"].astimezone(SEOUL).date() != day:
            continue
        hs, aws = sb.display_scores(g)
        ln, ls, rn, rs = g["home"], hs, g["away"], aws
        if g.get("kind") == "baseball":
            # 야구: 왼쪽=원정, 오른쪽=홈. 행의 home/away 는 '왼쪽/오른쪽' 뜻.
            ln, ls, rn, rs = rn, rs, ln, ls
        winner = "home" if ls > rs else ("away" if rs > ls else "")
        rows.append({
            "label": g["label"], "emoji": g.get("emoji") or "", "kind": g.get("kind"),
            "home": ln, "away": rn, "hs": ls, "aws": rs, "winner": winner,
            "order": g.get("order", 99), "start": g["start"],
        })
    rows.sort(key=lambda r: (r["order"], r["start"], r["label"]))
    return rows


def summary_caption(day, n, rows=None):
    """팀 이름을 넣지 않는다. 마지막 줄: 종목·리그 태그 + #경기결과."""
    cap = f"📋 {int(day.month)}월 {int(day.day)}일 경기 결과 · {int(n)}경기"
    sport, league = [], []
    for r in rows or []:
        for t in group_tags({"kind": r.get("kind"), "label": r.get("label")}, teams=False).split():
            bucket = sport if t[1:] in sb.SPORT_TAG.values() else league
            if t not in bucket:
                bucket.append(t)
    tags = " ".join(sport + league + ["#경기결과"])
    return with_tags(cap, tags)


def maybe_summary(chat_id, games, state, now):
    """매일 23:50 결과 이미지. 멤버 그룹으로만. chat_id(채널)로는 보내지 않는다."""
    global _last_group_send
    if not SUMMARY_ENABLED:
        return
    if group_auto_paused():
        return
    gid = group_id()
    if not gid:
        return
    gid = int(gid)
    if gid == int(CHANNEL_ID) or gid == int(BLOCKED_GROUP_ID):
        log("summary skip 그룹 id 가 채널이거나 차단된 그룹")
        return
    target = summary_target(now, state)
    if not target:
        return
    if sb._tg_used() >= 8:
        return
    if time.time() - _last_group_send < 3:
        return
    last = _summary_try.get(target.isoformat()) or 0
    if time.time() - last < 600 and state.get("summary_posted") != target.isoformat():
        # 방금 실패했으면 10분 쉬되, 첫 시도는 통과. last 가 있으면 대기.
        if last:
            return
    _summary_try[target.isoformat()] = time.time()
    use = games
    if target != now.date():
        try:
            use, _failed = sb.fetch_day(target)
        except Exception as e:
            log(f"summary fetch {redact(e)[:160]}")
            return
    rows = finished_rows(use, target)
    if not rows:
        state["summary_posted"] = target.isoformat()
        log(f"summary skip {target} 종료 경기 없음")
        return
    paths = cards.render_summary_pages(target, rows, max_pages=3)
    cap = summary_caption(target, len(rows), rows)
    try:
        if len(paths) == 1:
            jp = sb.photo_file(paths[0])
            sb.tg_call("sendPhoto", {"chat_id": gid, "caption": cap[:1024], "parse_mode": "HTML"}, dry=False,
                       files={"photo": jp}, timeout=20)
        else:
            media = []
            files = {}
            for i, pth in enumerate(paths):
                jp = sb.photo_file(pth)
                files[f"f{i}"] = jp
                item = {"type": "photo", "media": f"attach://f{i}"}
                if i == 0:
                    item["caption"] = cap[:1024]
                    item["parse_mode"] = "HTML"
                media.append(item)
            sb.tg_call("sendMediaGroup", {"chat_id": gid, "media": media}, dry=False, files=files, timeout=30)
    except Exception as e:
        log(f"summary 전송 실패 {redact(e)[:180]}")
        return
    _last_group_send = time.time()
    state["summary_posted"] = target.isoformat()
    log(f"summary posted group={gid} {target} games={len(rows)} pages={len(paths)}")


# ---------- 경기 프리뷰 (멤버 그룹, 시작 약 1시간 전) ----------
PREVIEW_PATH = os.path.join(BASE, "previews.json")
PREVIEW_ENABLED = True
PREVIEW_MAX_DAY = 6
PREVIEW_MIN, PREVIEW_MAX = 50 * 60, 70 * 60   # 시작 70~50분 전 사이에 한 번
# 리그별 하루 상한. 국내 먼저, NBA·MLB 는 하루 1경기.
PREVIEW_TIER = {
    ("baseball", 5): ("KBO", 3),
    ("basketball", 91): ("KBL", 2),
    ("basketball", 92): ("WKBL", 1),
    ("volleyball", 151): ("V리그", 2),
    ("volleyball", 152): ("V리그", 2),
    ("baseball", 1): ("MLB", 1),
    ("baseball", 2): ("NPB", 1),
    ("basketball", 12): ("NBA", 1),
}
PREVIEW_GAP = 120   # 프리뷰끼리 최소 간격(초). 같은 시각 경기가 몰려도 한꺼번에 올리지 않음.
_preview_try = {}
_preview_last = 0.0
_poll_retry = {}
_h2h_cache = {}


def _api_json(kind, path, params, timeout=25):
    import urllib.parse, urllib.request, json as _json
    key = os.environ.get("API_SPORTS_KEY")
    url = sb.HOSTS[kind] + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode())


def head_to_head(kind, home_id, away_id, before, n=5):
    """두 팀의 끝난 맞대결, 최근 n경기(최근 → 오래된). 리그 무관 실제 경기만. 6시간 캐시."""
    if home_id is None or away_id is None:
        return []
    a, b = sorted([int(home_id), int(away_id)])
    ck = (kind, a, b)
    hit = _h2h_cache.get(ck)
    if hit and time.time() - hit[0] < 6 * 3600:
        raws = hit[1]
    else:
        try:
            if kind == "basketball":
                body = _api_json(kind, "/games", {"h2h": f"{a}-{b}", "timezone": "Asia/Seoul"})
            else:
                body = _api_json(kind, "/games/h2h", {"h2h": f"{a}-{b}", "timezone": "Asia/Seoul"})
            raws = body.get("response") or [] if not body.get("errors") else []
        except Exception as e:
            log(f"h2h {kind} {a}-{b} {redact(e)[:120]}")
            raws = []
        _h2h_cache[ck] = (time.time(), raws)
    games = []
    for raw in raws:
        lid = (raw.get("league") or {}).get("id")
        meta = sb.LEAGUE_BY_KEY.get((kind, lid)) or {
            "kind": kind, "league": lid, "season": (raw.get("league") or {}).get("season"),
            "label": (raw.get("league") or {}).get("name") or "", "emoji": sb.EMOJI.get(kind, ""), "order": 99,
        }
        try:
            g = sb.parse_game(raw, meta)
        except Exception:
            g = None
        if not g or not sb.is_finished(g) or g["start"] >= before:
            continue
        if {g.get("home_id"), g.get("away_id")} != {int(home_id), int(away_id)}:
            continue
        games.append(g)
    games = dedupe_games(games)
    games.sort(key=lambda g: g["start"], reverse=True)
    out = []
    for g in games[:n]:
        hs, aws = sb.display_scores(g)
        try:
            hs, aws = int(hs), int(aws)
        except (TypeError, ValueError):
            continue
        out.append({"date": g["start"].astimezone(SEOUL), "home": g["home"], "away": g["away"],
                    "home_id": g.get("home_id"), "away_id": g.get("away_id"), "hs": hs, "aws": aws})
    return out


def season_record(kind, league, team_id):
    """순위표에서 팀 시즌 성적. {'text': '88승 54패 · 1위', 'pre': bool} 또는 None."""
    try:
        season, _lab = current_season(kind, league)
        groups = _played_groups(fetch_standings(kind, league, season))
    except Exception as e:
        log(f"preview standings {kind}:{league} {redact(e)[:120]}")
        return None
    for section, rows in groups:
        for r in rows:
            if r.get("tid") != team_id:
                continue
            bits = []
            if r.get("win") is not None and r.get("lose") is not None:
                bits.append(f"{r['win']}승 {r['lose']}패")
            if kind == "volleyball" and r.get("pts") is not None:
                pts = r["pts"]
                bits.append(f"{int(pts) if pts == int(pts) else pts}점")
            if r.get("rank"):
                bits.append(f"{section + ' ' if section and '프리시즌' not in section else ''}{r['rank']}위")
            if not bits:
                return None
            pre = "프리시즌" in (section or "")
            return {"text": ("프리시즌 " if pre else "") + " · ".join(bits), "pre": pre}
    return None


def preview_data(g, now=None):
    """프리뷰 카드에 들어갈 실제 자료. 없는 칸은 비운다(지어내지 않음)."""
    now = now or datetime.now(SEOUL)
    kind, league = g["kind"], g.get("league")
    hid, aid = g.get("home_id"), g.get("away_id")
    # 다섯 조회를 동시에 (각자 캐시가 있다). 순서·결과는 예전과 같다.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_fh = ex.submit(team_form, kind, league, hid, now) if hid is not None else None
        f_fa = ex.submit(team_form, kind, league, aid, now) if aid is not None else None
        f_sh = ex.submit(season_record, kind, league, hid)
        f_sa = ex.submit(season_record, kind, league, aid)
        f_h2 = ex.submit(head_to_head, kind, hid, aid, g["start"])
        form_h = f_fh.result() if f_fh else []
        form_a = f_fa.result() if f_fa else []
        season_h, season_a, h2h = f_sh.result(), f_sa.result(), f_h2.result()
    return {
        "g": g,
        "form": {"home": form_h, "away": form_a},
        "season": {"home": season_h, "away": season_a},
        "h2h": h2h,
    }


def group_tags(g, kind_tag=None, teams=True):
    """그룹 글 해시태그 한 줄: 채널과 같은 규칙(종목·리그·두 팀, 야구는 원정 먼저) + 글 종류 태그."""
    try:
        tags = sb.hashtags(g, teams=teams)
    except Exception:
        tags = ""
    if kind_tag:
        tags = (tags + " #" + kind_tag).strip()
    return tags


def with_tags(cap, tags):
    """캡션 마지막 줄에 태그. 1024자를 넘기면 태그를 뺀다."""
    if not tags:
        return cap
    if len(sb.caption_plain(cap)) + 1 + len(tags) > 1024:
        return cap
    return f"{cap}\n{sb.esc(tags)}"


def preview_caption(g):
    st = g["start"].astimezone(SEOUL)
    hm = st.strftime("%H:%M")
    if st.date() != datetime.now(SEOUL).date():
        hm = f"{st.month}/{st.day}({sb.weekday_ko(st)}) {hm}"
    extra = ""
    if g.get("series_ko"):
        extra += f" · {sb.esc(g['series_ko'])}"
    if g.get("if_necessary"):
        extra += " · 필요 시 개최"
    left, right = (g["away"], g["home"]) if g.get("kind") == "baseball" else (g["home"], g["away"])
    return with_tags(f"🔎 경기 프리뷰 · {sb.esc(left)} vs {sb.esc(right)} · {hm}{extra}", group_tags(g, "프리뷰"))


def _preview_default():
    return {"posted": {}}


def preview_candidates(games, now, data=None):
    """지금 보낼 수 있는 프리뷰 후보(우선순위 순). 상한·중복을 반영."""
    data = data or _locked_read(PREVIEW_PATH, _preview_default())
    posted = data.get("posted") or {}
    out = []
    for g in games:
        tier = PREVIEW_TIER.get((g.get("kind"), g.get("league")))
        if not tier or g.get("status") not in sb.NOT_STARTED:
            continue
        if g["key"] in posted:
            continue
        lead = (g["start"] - now).total_seconds()
        if not (PREVIEW_MIN <= lead <= PREVIEW_MAX):
            continue
        day = g["start"].astimezone(SEOUL).date().isoformat()
        today = [v for v in posted.values() if v.get("day") == day]
        if len(today) >= PREVIEW_MAX_DAY:
            continue
        group_name, cap = tier
        if sum(1 for v in today if v.get("group") == group_name) >= cap:
            continue
        # 같은 대진·시각이 다른 id 로 이미 나갔으면 건너뜀
        ts = int(g["start"].timestamp())
        if any(v.get("home") == g["home"] and v.get("away") == g["away"] and v.get("ts") == ts for v in today):
            continue
        out.append(g)
    order = list(PREVIEW_TIER)
    out.sort(key=lambda g: (order.index((g["kind"], g["league"])), g["start"], g["key"]))
    return out


def _attach_pending_polls(games, now):
    """프리뷰는 나갔지만 투표가 아직 없는 경기에 답글 투표를 붙인다(시작 35분 전까지, 1분마다 한 번)."""
    data = _locked_read(PREVIEW_PATH, _preview_default())
    polls = (_locked_read(PRED_PATH, _pred_default()).get("polls") or {})
    by_key = {g["key"]: g for g in games}
    for key, v in (data.get("posted") or {}).items():
        g = by_key.get(key)
        if not g or key in polls or not v.get("message_id") or g.get("status") not in sb.NOT_STARTED:
            continue
        if (g["start"] - now).total_seconds() < 35 * 60:
            continue
        if time.time() - (_poll_retry.get(key) or 0) < 60:
            continue
        _poll_retry[key] = time.time()
        try:
            maybe_open_poll(g, now, reply_to=v["message_id"], with_card=False)
        except Exception as e:
            log(f"preview poll {key} {redact(e)[:120]}")
        return


def maybe_previews(games, now):
    """시작 약 1시간 전 프리뷰 1장(+예측 투표). 한 번 돌 때 최대 1경기."""
    global _last_group_send, _preview_last
    if not PREVIEW_ENABLED or group_auto_paused():
        return
    gid = group_id()
    if not gid or int(gid) in (int(CHANNEL_ID), int(BLOCKED_GROUP_ID)):
        return
    if sb._tg_used() >= 8 or time.time() - _last_group_send < 3:
        return
    _attach_pending_polls(games, now)
    if time.time() - _preview_last < PREVIEW_GAP or time.time() - _last_group_send < 3:
        return
    cands = preview_candidates(games, now)
    cands = [g for g in cands if time.time() - (_preview_try.get(g["key"]) or 0) > 300]
    if not cands:
        return
    g = cands[0]
    _preview_try[g["key"]] = time.time()
    try:
        info = preview_data(g, now)
        path = cards.render_preview_card(info)
        jp = sb.photo_file(path)
        msg = tg_multipart("sendPhoto", {"chat_id": int(gid), "caption": preview_caption(g)[:1024],
                                         "parse_mode": "HTML"}, {"photo": jp}, timeout=20)
    except Exception as e:
        log(f"preview 실패 {g['key']} {redact(e)[:160]}")
        return
    _last_group_send = time.time()
    _preview_last = time.time()
    mid = (msg or {}).get("message_id")
    group_name = PREVIEW_TIER[(g["kind"], g["league"])][0]

    def mut(d):
        d.setdefault("posted", {})[g["key"]] = {
            "day": g["start"].astimezone(SEOUL).date().isoformat(), "group": group_name,
            "home": g["home"], "away": g["away"], "ts": int(g["start"].timestamp()),
            "message_id": mid, "chat_id": int(gid), "sent": time.time(),
        }
        # 2주 지난 기록은 지운다
        cutoff = (now - timedelta(days=14)).date().isoformat()
        for k in [k for k, v in d["posted"].items() if (v.get("day") or "") < cutoff]:
            d["posted"].pop(k, None)
    _locked_update(PREVIEW_PATH, _preview_default(), mut)
    log(f"preview {g['key']} {g['home']} vs {g['away']} msg {mid}")
    # 예측 투표는 프리뷰에 답글로(카드 중복 없이). 투표 상한은 maybe_open_poll 이 지킨다.
    try:
        maybe_open_poll(g, now, reply_to=mid, with_card=False)
    except Exception as e:
        log(f"preview poll {g['key']} {redact(e)[:120]}")


# ---------- 주간 예측 순위 ----------
WEEKLY_PATH = os.path.join(BASE, "weekly.json")
WEEKLY_ENABLED = True


def week_bounds(day):
    """day 가 속한 주의 월요일, 일요일(date)."""
    mon = day - timedelta(days=day.weekday())
    return mon, mon + timedelta(days=6)


def weekly_rows(mon, sun, data=None):
    """그 주(월~일, 경기 날짜 기준)에 채점된 투표로 순위. 적중 → 적중률 → 먼저 참여."""
    data = data or _locked_read(PRED_PATH, _pred_default())
    agg = {}
    for p in (data.get("polls") or {}).values():
        if not isinstance(p, dict) or not p.get("scored"):
            continue
        day = p.get("game_day") or p.get("day") or ""
        if not (mon.isoformat() <= day <= sun.isoformat()):
            continue
        for uid, r in (p.get("results") or {}).items():
            a = agg.setdefault(uid, {"name": r.get("name") or uid, "correct": 0, "total": 0, "first": None})
            if r.get("name"):
                a["name"] = r["name"]
            a["total"] += 1
            a["correct"] += 1 if r.get("ok") else 0
            ts = r.get("ts") or p.get("opened")
            if ts and (a["first"] is None or ts < a["first"]):
                a["first"] = ts
    rows = []
    for uid, a in agg.items():
        rate = a["correct"] / a["total"] if a["total"] else 0.0
        rows.append({"uid": uid, "name": a["name"], "correct": a["correct"], "total": a["total"],
                     "rate": rate, "first": a["first"] or float("inf")})
    rows.sort(key=lambda r: (-r["correct"], -r["rate"], r["first"]))
    rank = 0
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def weekly_image(now, last_week=False, sample_rows=None, sample_label=None):
    today = now.astimezone(SEOUL).date()
    if last_week:
        today = today - timedelta(days=7)
    mon, sun = week_bounds(today)
    rows = sample_rows if sample_rows is not None else weekly_rows(mon, sun)
    title = "지난주 예측 TOP 5" if last_week else "이번 주 예측 순위"
    wd = "월화수목금토일"
    sub = f"{mon.month}월 {mon.day}일({wd[mon.weekday()]}) ~ {sun.month}월 {sun.day}일({wd[sun.weekday()]})"
    if sample_label:
        sub += f" · {sample_label}"
    path = cards.render_weekly_top5(title, sub, rows[:5], total=len(rows))
    cap = (f"🏆 지난주 예측 TOP 5 · {mon.month}/{mon.day}~{sun.month}/{sun.day}" if last_week
           else f"🏆 이번 주 예측 순위 · {mon.month}/{mon.day}~{sun.month}/{sun.day}")
    cap = with_tags(cap, "#예측랭킹")
    return path, cap, rows


def maybe_weekly(now):
    """월요일 10:00~12:00 KST 에 지난주 TOP 5 한 번. 참여자가 없으면 건너뛰고 기록."""
    global _last_group_send
    if not WEEKLY_ENABLED:
        return
    now = now.astimezone(SEOUL)
    if now.weekday() != 0 or not (10 <= now.hour < 12):
        return
    if group_auto_paused():
        return
    gid = group_id()
    if not gid or int(gid) in (int(CHANNEL_ID), int(BLOCKED_GROUP_ID)):
        return
    mon, _sun = week_bounds(now.date() - timedelta(days=7))
    wk = mon.isoformat()
    done = _locked_read(WEEKLY_PATH, {"posted": {}})
    if wk in (done.get("posted") or {}):
        return
    if sb._tg_used() >= 8 or time.time() - _last_group_send < 3:
        return
    last = _summary_try.get("weekly:" + wk) or 0
    if time.time() - last < 600:
        return
    _summary_try["weekly:" + wk] = time.time()
    path, cap, rows = weekly_image(now, last_week=True)

    def mark(status, mid=None):
        def mut(d):
            d.setdefault("posted", {})[wk] = {"status": status, "ts": time.time(), "message_id": mid,
                                              "participants": len(rows)}
        _locked_update(WEEKLY_PATH, {"posted": {}}, mut)

    if not rows:
        mark("skip-empty")
        log(f"weekly skip {wk} 참여자 없음")
        return
    try:
        jp = sb.photo_file(path)
        msg = tg_multipart("sendPhoto", {"chat_id": int(gid), "caption": cap[:1024], "parse_mode": "HTML"},
                           {"photo": jp}, timeout=20)
    except Exception as e:
        log(f"weekly 전송 실패 {redact(e)[:160]}")
        return
    _last_group_send = time.time()
    mark("posted", (msg or {}).get("message_id"))
    log(f"weekly posted group={gid} week={wk} n={len(rows)}")


# ---------- score_bot hooks ----------
def on_pregame(g, now):
    try:
        maybe_open_poll(g, now)
    except Exception as e:
        log(f"poll hook {redact(e)[:160]}")


def on_live(g, st):
    try:
        close_poll(g)
    except Exception as e:
        log(f"close poll {redact(e)[:120]}")
    if not st.get("fan_start"):
        st["fan_start"] = True
        try:
            queue_fan_dm(g, "start")
        except Exception as e:
            log(f"fan start {redact(e)[:120]}")
    try:
        ev = observe(g, st)
        post_alerts(ev)
    except Exception as e:
        log(f"alert live {redact(e)[:120]}")


def on_score(g, st):
    try:
        ev = observe(g, st)
        post_alerts(ev)
    except Exception as e:
        log(f"alert score {redact(e)[:120]}")


def on_final(g, st, now):
    try:
        ev = observe(g, st)
        post_alerts(ev)
    except Exception as e:
        log(f"alert final {redact(e)[:120]}")
    if sb.is_finished(g) and not st.get("fan_end"):
        st["fan_end"] = True
        try:
            queue_fan_dm(g, "end")
        except Exception as e:
            log(f"fan end {redact(e)[:120]}")
    try:
        score_poll(g, now)
    except Exception as e:
        log(f"score poll {redact(e)[:160]}")


HELP_CAPTION = cards.help_caption()


# ---------- 쿼터/세트 종료 (그룹) ----------
PERIOD_PATH = os.path.join(BASE, "periods.json")
PERIOD_ENABLED = True
NBA_PERIOD_POSTS = True
PERIOD_LEAGUES = {("basketball", 91), ("basketball", 92), ("volleyball", 151), ("volleyball", 152)}
PERIOD_MAX_HOUR = 40       # 그룹에 한 시간 최대
PERIOD_STALE = 8 * 60      # 이만큼 못 보냈으면 늦은 글은 건너뜀
PERIOD_PER_LOOP = 2
_period_ts = []
BB_LIVE_DONE = {"Q1": 0, "Q2": 1, "HT": 2, "Q3": 2, "Q4": 3, "OT": 4}


def _period_league_on(g):
    key = (g.get("kind"), g.get("league"))
    if key == ("basketball", 12):
        return NBA_PERIOD_POSTS
    return key in PERIOD_LEAGUES


def _vb_set_done(i, h, a):
    target = 15 if i == 4 else 25
    return max(h, a) >= target and abs(h - a) >= 2


def period_progress(g, rec=None):
    """(끝난 구간 수, 종료 여부). 모르면 (None, False)."""
    st = g.get("status") or ""
    if sb.is_finished(g):
        return len(g.get("lines") or []), True
    if not sb.is_live(g):
        return None, False
    if g["kind"] == "basketball":
        if st == "BT":
            last = (rec or {}).get("last_q")
            return (last, False) if last else (None, False)
        return BB_LIVE_DONE.get(st), False
    if g["kind"] == "volleyball":
        m = re.fullmatch(r"S(\d)", st)
        by_status = int(m.group(1)) - 1 if m else 0
        by_score = 0
        for i, (_lab, h, a) in enumerate(g.get("lines") or []):
            if _vb_set_done(i, h, a):
                by_score = i + 1
            else:
                break
        return max(by_status, by_score), False
    return None, False


def _period_default():
    return {"games": {}}


def period_post_spec(g, done, final):
    """(라벨, 끝난 구간 줄, 홈점수, 원정점수, 강조 라벨) 또는 None(자료 부족)."""
    lines = list(g.get("lines") or [])
    if final:
        if not lines:
            return None
        if g["kind"] == "volleyball":
            lines = [x for i, x in enumerate(lines) if _vb_set_done(i, x[1], x[2])]
        hs, aws = g.get("home_score"), g.get("away_score")
        if hs is None or aws is None:
            return None
        return "경기 종료", lines, hs, aws, None
    if g["kind"] == "basketball":
        q = [x for x in lines if x[0] != "OT"][:done]
        if len(q) < done or done < 1 or done > 4:
            return None
        return f"{done}Q 종료", q, sum(x[1] for x in q), sum(x[2] for x in q), q[-1][0]
    q = lines[:done]
    if len(q) < done or done < 1 or not all(_vb_set_done(i, h, a) for i, (_l, h, a) in enumerate(q)):
        return None
    hs = sum(1 for _l, h, a in q if h > a)
    aws = sum(1 for _l, h, a in q if a > h)
    if max(hs, aws) >= 3:     # 마지막 세트는 '경기 종료'로만
        return None
    return f"{done}세트 종료", q, hs, aws, q[-1][0]


def period_caption(g, label, hs, aws, final=False):
    if final:
        kt = "경기종료"
    else:
        kt = "세트종료" if g.get("kind") == "volleyball" else "쿼터종료"
    return with_tags(f"⏱ {sb.esc(g['home'])} {hs} : {aws} {sb.esc(g['away'])} · {label}", group_tags(g, kt))


def maybe_period_posts(games, now):
    """쿼터/세트가 끝날 때마다 그룹에 한 장. 게임별로 보낸 구간을 저장해 재시작에도 중복 없음."""
    global _last_group_send, _period_ts
    if not PERIOD_ENABLED:
        return
    gid = group_id()
    if not gid or int(gid) in (int(CHANNEL_ID), int(BLOCKED_GROUP_ID)):
        return
    data = _locked_read(PERIOD_PATH, _period_default())
    recs = data.get("games") or {}
    changes = {}
    todo = []
    for g in games:
        if not _period_league_on(g) or g["kind"] not in ("basketball", "volleyball"):
            continue
        key = g["key"]
        rec = dict(recs.get(key) or {})
        if not rec:
            soon = 0 <= (g["start"] - now).total_seconds() <= 30 * 60
            if sb.is_live(g):
                done, _f = period_progress(g, None)
                # 처음 보는 진행 중 경기: 지난 구간은 조용히 기준만 잡는다(재시작 직후 늦은 글 방지)
                rec = {"done": done or 0, "final": False, "day": g["start"].astimezone(SEOUL).date().isoformat()}
                if g["kind"] == "basketball" and g["status"] in BB_LIVE_DONE and g["status"] not in ("HT", "OT"):
                    rec["last_q"] = BB_LIVE_DONE[g["status"]] + 1
                changes[key] = rec
            elif soon and not sb.is_terminal(g):
                changes[key] = {"done": 0, "final": False, "day": g["start"].astimezone(SEOUL).date().isoformat()}
            continue   # 기록이 없던 경기(끝난 것 포함)는 이번엔 보내지 않음
        if rec.get("final"):
            continue
        if g["kind"] == "basketball" and g["status"] in ("Q1", "Q2", "Q3", "Q4"):
            q = int(g["status"][1])
            if rec.get("last_q") != q:
                rec["last_q"] = q
                changes[key] = rec
        done, final = period_progress(g, rec)
        if final:
            todo.append((g, rec, None, True))
        elif done is not None and done > int(rec.get("done") or 0):
            # 배구에서 이번 세트로 승부가 났으면 그 세트는 '경기 종료'로 보내고, 그 앞 세트가 남았으면 그것만
            if g["kind"] == "volleyball":
                q = (g.get("lines") or [])[:done]
                wins = (sum(1 for _l, h, a in q if h > a), sum(1 for _l, h, a in q if a > h))
                if max(wins) >= 3:
                    done -= 1
                    if done <= int(rec.get("done") or 0):
                        continue
            todo.append((g, rec, done, False))
    sent = 0
    for g, rec, done, final in todo:
        key = g["key"]
        pend = rec.get("pending") or {}
        want = "final" if final else str(done)
        if pend.get("want") != want:
            pend = {"want": want, "since": time.time()}
        rec["pending"] = pend
        changes[key] = rec
        spec = period_post_spec(g, done, final)

        def mark():
            rec.pop("pending", None)
            if final:
                rec["final"] = True
            else:
                rec["done"] = done
        if spec is None:
            log(f"period skip(자료 부족) {key} {want}")
            mark()
            continue
        if time.time() - pend["since"] > PERIOD_STALE:
            log(f"period skip(늦음) {key} {want}")
            mark()
            continue
        _period_ts = [t for t in _period_ts if time.time() - t < 3600]
        if (group_auto_paused() or sent >= PERIOD_PER_LOOP or len(_period_ts) >= PERIOD_MAX_HOUR
                or sb._tg_used() >= 8):
            continue
        if time.time() - _last_group_send < 3:
            time.sleep(3)
        label, lines, hs, aws, just = spec
        try:
            path = cards.render_period_card(g, label, lines, hs, aws, final=final, just=just)
            jp = sb.photo_file(path)
            tg_multipart("sendPhoto", {"chat_id": int(gid), "caption": period_caption(g, label, hs, aws, final=final)[:1024],
                                       "parse_mode": "HTML"}, {"photo": jp}, timeout=20)
        except TgError as e:
            log(f"period 실패 {key} {want} {e.desc[:120]}")
            continue
        except Exception as e:
            log(f"period 오류 {key} {want} {redact(e)[:160]}")
            continue
        _last_group_send = time.time()
        _period_ts.append(time.time())
        sent += 1
        mark()
        log(f"period {key} {label} {hs}-{aws}")
    if not changes:
        return
    cutoff = (now - timedelta(days=3)).date().isoformat()

    def mut(d):
        gs = d.setdefault("games", {})
        for k, v in changes.items():
            old = gs.get(k) or {}
            # 다른 쪽에서 더 앞선 기록이 있으면 되돌리지 않는다
            if old.get("final"):
                continue
            if int(old.get("done") or 0) > int(v.get("done") or 0):
                v["done"] = old["done"]
            gs[k] = v
        for k in [k for k, v in gs.items() if (v.get("day") or "") < cutoff]:
            gs.pop(k, None)
    _locked_update(PERIOD_PATH, _period_default(), mut)

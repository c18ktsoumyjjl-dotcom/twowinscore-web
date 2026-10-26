"""스포츠뉴스 — 네이버 스포츠 '많이 본 뉴스' 목록(제목·언론사·시간·썸네일)만 보여주고 기사는 네이버로 연결해요. 본문은 가져오지 않아요."""
import json, time, threading, logging, urllib.request, urllib.parse
from datetime import datetime
from flask import abort, Blueprint, render_template, request, Response

log = logging.getLogger("news")
bp = Blueprint("news", __name__)
TTL = 600
SPORTS = [("baseball", "야구", [("kbaseball", "KBO"), ("wbaseball", "MLB·해외야구")]),
          ("football", "축구", [("kfootball", "K리그·대표팀"), ("wfootball", "해외축구")]),
          ("basketball", "농구", [("basketball", "농구")]),
          ("volleyball", "배구", [("volleyball", "배구")])]
CAT_OK = {c for _, _, ls in SPORTS for c, _ in ls}
_cache, _lk = {}, threading.Lock()


def _get(cat, day=None):
    u = f"https://api-gw.sports.naver.com/news/articles/{cat}?sort=popular&page=1&pageSize=20" + (f"&date={day}" if day else "")
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=6))
    return d["result"]["newsList"] or []


def _fetch(cat):
    from datetime import timedelta
    lst = _get(cat)
    if len(lst) < 10:   # 자정 직후엔 오늘 인기 기사가 적어요 → 어제 많이 본 뉴스로 채움
        y = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        try:
            seen = {(n.get("oid"), n.get("aid")) for n in lst}
            lst += [n for n in _get(cat, y) if (n.get("oid"), n.get("aid")) not in seen]
        except Exception as e:
            log.warning("naver %s yday: %s", cat, e)
    out = []
    for n in lst[:20]:
        oid, aid = str(n.get("oid", "")), str(n.get("aid", ""))
        if not (oid.isdigit() and aid.isdigit()):
            continue
        th = n.get("thumbnail") or ""
        out.append({"t": (n.get("title") or "").strip(), "src": n.get("sourceName") or "", "sec": n.get("sectionName") or "",
                    "th": th if th.startswith("https://") and ".pstatic.net/" in th else "",
                    "at": (n.get("dateTime") or "")[:16].replace("T", " "), "cat": cat,
                    "url": f"https://m.sports.naver.com/{cat}/article/{oid}/{aid}"})
    return out


_busy = set()


def _refresh(cat):
    try:
        v = _fetch(cat)
        with _lk:
            _cache[cat] = (time.time(), v)
    except Exception as e:
        log.warning("naver %s: %s", cat, e)
        with _lk:
            c = _cache.get(cat)
            if c:
                _cache[cat] = (time.time() - TTL + 60, c[1])   # 실패하면 1분 뒤 다시 시도, 그동안 이전 목록
    finally:
        with _lk:
            _busy.discard(cat)


def items(cat, wait=3.0):
    """요청은 네이버를 기다리지 않음: 저장된 목록을 바로 주고 만료·실패 시 뒤에서 1회 갱신.
    처음(목록 없음)에만 최대 wait 초 기다림 (10/26 21:10 Render→네이버 타임아웃으로 /news 17초·빈 화면)."""
    if cat not in CAT_OK:
        return []
    with _lk:
        c = _cache.get(cat)
        fresh = c and time.time() - c[0] < TTL
        start = not fresh and cat not in _busy
        if start:
            _busy.add(cat)
    if start:
        t = threading.Thread(target=_refresh, args=(cat,), daemon=True)
        t.start()
        if not c and wait:
            t.join(wait)
            with _lk:
                c = _cache.get(cat)
    return c[1] if c else []


def ago(s):
    try:
        d = (datetime.now() - datetime.strptime(s, "%Y-%m-%d %H:%M")).total_seconds()
    except Exception:
        return s
    if d < 3600:
        return f"{max(1, int(d // 60))}분 전"
    if d < 86400:
        return f"{int(d // 3600)}시간 전"
    return s[5:].replace("-", ".")


KIND_CATS = {"baseball": ["kbaseball", "wbaseball"], "football": ["kfootball", "wfootball"], "basketball": ["basketball"], "volleyball": ["volleyball"]}


def related(kind, names, n=3):
    """경기 상세용: 팀 이름이 제목에 들어간 많이 본 뉴스."""
    keys = set()
    for nm in names or ():
        nm = (nm or "").strip()
        if len(nm) >= 2:
            keys.add(nm)
            if " " in nm:
                p = nm.split()[-1]
                if len(p) >= 2:
                    keys.add(p)   # "서울 삼성" → "삼성" (도시 이름만으로는 안 붙임)
    out = []
    for cat in KIND_CATS.get(kind, []):
        with _lk:
            c = _cache.get(cat)
        if not c or time.time() - c[0] > TTL:   # 경기 화면은 기다리지 않음: 백그라운드로 갱신
            threading.Thread(target=items, args=(cat,), daemon=True).start()
        for it in (c[1] if c else []):
            if any(k in it["t"] for k in keys) and it not in out:
                out.append(it)
    return out[:n]


@bp.app_template_filter("ago")
def _ago(s):
    return ago(s)


@bp.route("/news")
def page():
    sp = request.args.get("s", "baseball")
    sport = next((x for x in SPORTS if x[0] == sp), SPORTS[0])
    lg = request.args.get("l", "")
    cats = [c for c, _ in sport[2]]
    if lg in cats:
        lst = items(lg)
    else:
        lg = ""
        ls = [items(c) for c in cats]
        lst = []
        for i in range(20):   # 리그별로 번갈아 (각 리그의 많이 본 순서 유지)
            for l in ls:
                if i < len(l):
                    lst.append(l[i])
        lst = lst[:24]
    return render_template("news.html", page="news", sports=SPORTS, sport=sport, lg=lg, news=lst)


@bp.route("/sitemap.xml")
def sitemap():
    """사이트맵 인덱스: 고정 페이지 + 날짜별 경기(어제·오늘·내일). 관리자 경로는 넣지 않음."""
    from datetime import datetime, timedelta
    import data
    base = "https://twowinscore.com"
    t = datetime.now(data.SEOUL)
    days = [(t.date() + timedelta(days=i)).isoformat() for i in (-1, 0, 1)]
    x = '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    x += f"<sitemap><loc>{base}/sitemap-pages.xml</loc><lastmod>{t.date().isoformat()}</lastmod></sitemap>"
    x += "".join(f"<sitemap><loc>{base}/sitemap-games-{d}.xml</loc><lastmod>{t.isoformat(timespec='seconds')}</lastmod></sitemap>" for d in days)
    x += "</sitemapindex>"
    return Response(x, mimetype="application/xml", headers={"Cache-Control": "public, max-age=1800"})


def _urlset(items):
    x = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    for loc, freq, pri in items:
        x += f"<url><loc>{loc.replace('&', '&amp;')}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
    return Response(x + "</urlset>", mimetype="application/xml", headers={"Cache-Control": "public, max-age=1800"})


@bp.route("/sitemap-pages.xml")
def sitemap_pages():
    import data
    base = "https://twowinscore.com"
    items = [(base + "/", "always", "1.0"), (base + "/standings", "daily", "0.8"), (base + "/news", "hourly", "0.7")]
    items += [(base + f"/news?s={s}", "hourly", "0.6") for s, _, _ in SPORTS[1:]]
    items += [(base + f"/standings?league={sl}", "daily", "0.7") for sl in data.STANDING_SLUGS if sl != "kbo"]
    items += [(base + "/shop", "monthly", "0.3"), (base + "/privacy", "yearly", "0.2")]
    return _urlset(items)


@bp.route("/sitemap-games-<d>.xml")
def sitemap_games(d):
    from datetime import date
    import data
    try:
        day = date.fromisoformat(d)
    except ValueError:
        abort(404)
    base = "https://twowinscore.com"
    try:
        games, _ = data.games_for(day)
    except Exception:
        games = []
    items = [(base + "/?d=" + day.isoformat(), "hourly", "0.6")]
    items += [(f"{base}/game/{g['key']}", "always" if g.get("state") == "live" else "hourly", "0.8") for g in games]
    return _urlset(items)


@bp.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /api/\nDisallow: /me\nDisallow: /login\nDisallow: /logout\nAllow: /\n\nUser-agent: Yeti\nAllow: /\nDisallow: /api/\n\nSitemap: https://twowinscore.com/sitemap.xml\n", mimetype="text/plain")

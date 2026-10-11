"""스포츠뉴스 — 네이버 스포츠 '많이 본 뉴스' 목록(제목·언론사·시간·썸네일)만 보여주고 기사는 네이버로 연결해요. 본문은 가져오지 않아요."""
import json, time, threading, logging, urllib.request, urllib.parse
from datetime import datetime
from flask import Blueprint, render_template, request, Response

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
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=8))
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


def items(cat):
    if cat not in CAT_OK:
        return []
    now = time.time()
    with _lk:
        c = _cache.get(cat)
        if c and now - c[0] < TTL:
            return c[1]
    try:
        v = _fetch(cat)
        with _lk:
            _cache[cat] = (now, v)
        return v
    except Exception as e:
        log.warning("naver %s: %s", cat, e)
        with _lk:
            if c:
                _cache[cat] = (now - TTL + 60, c[1])   # 실패하면 1분 뒤 다시 시도, 그동안 이전 목록
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
    base = "https://twowinscore.com"
    urls = ["/", "/standings", "/news"] + [f"/news?s={s}" for s, _, _ in SPORTS[1:]] + ["/shop", "/privacy"]
    x = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f"<url><loc>{base}{urllib.parse.quote(u, safe='/?=&')}</loc><changefreq>{'hourly' if 'news' in u or u == '/' else 'daily'}</changefreq></url>".replace("&", "&amp;") for u in urls) + "</urlset>"
    return Response(x, mimetype="application/xml", headers={"Cache-Control": "public, max-age=3600"})


@bp.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /api/\nAllow: /\nSitemap: https://twowinscore.com/sitemap.xml\n", mimetype="text/plain")

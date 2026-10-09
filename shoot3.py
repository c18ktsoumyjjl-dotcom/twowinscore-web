import json
from playwright.sync_api import sync_playwright
B="http://localhost:8088"
def mock(route):
    r=route.fetch(); j=r.json()
    for g in j["games"][:1]:
        g["state"]="live"; g["badge"]="5회말"; g["L"]["score"]=2; g["R"]["score"]=3
    j["upstream"]=15
    route.fulfill(response=r, body=json.dumps(j))
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,tag in ((390,"mobile"),(1280,"desktop")):
        ctx=b.new_context(viewport={"width":w,"height":844 if w<500 else 900},device_scale_factor=2 if w<500 else 1)
        ctx.add_init_script("localStorage.setItem('tw_fav',JSON.stringify(['baseball:93']))")
        pg=ctx.new_page()
        for n,u in [("home","/"),("yesterday","/?d=2026-10-09"),("baseball_detail","/game/baseball:5:182037?d=2026-10-09"),("mlb_detail","/game/baseball:1:190155?d=2026-10-09")]:
            pg.goto(B+u); pg.wait_for_timeout(1500); pg.screenshot(path=f"screens/v3_{n}_{tag}.png",full_page=True)
        if w<500:
            pg.goto(B+"/?d=2026-10-09"); pg.wait_for_timeout(1200); pg.fill("#q","롯데"); pg.wait_for_timeout(300)
            pg.screenshot(path="screens/v3_search_mobile.png")
            pg.route("**/api/games*",mock); pg.goto(B+"/"); pg.wait_for_timeout(1500)
            pg.screenshot(path="screens/v3_live_demo_mobile.png")
        ctx.close()
    b.close()

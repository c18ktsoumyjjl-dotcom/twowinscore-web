import sys, json
from playwright.sync_api import sync_playwright
B=sys.argv[1]; pre=sys.argv[2]; demo=len(sys.argv)>3
def mock(route):
    r=route.fetch(); j=r.json()
    g=j["games"][0]; g["state"]="live"; g["badge"]="7회말"; g["L"]["score"]=3; g["R"]["score"]=2
    route.fulfill(response=r, body=json.dumps(j))
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,tag in ((390,"mobile"),(1440,"desktop")):
        ctx=b.new_context(viewport={"width":w,"height":844 if w<500 else 900},device_scale_factor=2 if w<500 else 1)
        ctx.add_init_script("localStorage.setItem('tw_chat_open','0')")
        pg=ctx.new_page()
        if demo: pg.route("**/api/games*",mock)
        pg.goto(B+"/",timeout=90000); pg.wait_for_selector(".g5",timeout=60000); pg.wait_for_timeout(1000)
        pg.screenshot(path=f"screens/{pre}_{tag}.png")
        pg.mouse.wheel(0,600); pg.wait_for_timeout(800); pg.screenshot(path=f"screens/{pre}_{tag}_scrolled.png")
        ctx.close()
    b.close()

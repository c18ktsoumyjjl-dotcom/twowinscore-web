import sys
from playwright.sync_api import sync_playwright
B=sys.argv[1]; pre=sys.argv[2]
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,tag in ((390,"mobile"),(1440,"desktop")):
        ctx=b.new_context(viewport={"width":w,"height":844 if w<500 else 900},device_scale_factor=2 if w<500 else 1)
        ctx.add_init_script("localStorage.setItem('tw_chat_open','0')"+(";localStorage.setItem('tw_theme','light')" if "light" in pre else ""))
        pg=ctx.new_page(); pg.goto(B+"/",timeout=90000); pg.wait_for_selector(".g",timeout=60000); pg.wait_for_timeout(800)
        pg.screenshot(path=f"screens/{pre}_{tag}.png")
        if tag=="desktop" or "local" in pre:
            pg.mouse.wheel(0,520); pg.wait_for_timeout(800); pg.screenshot(path=f"screens/{pre}_{tag}_scrolled.png")
        ctx.close()
    b.close()

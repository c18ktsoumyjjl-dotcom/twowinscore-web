from playwright.sync_api import sync_playwright
B="http://localhost:8088"
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,tag in ((390,"mobile"),(1280,"desktop")):
        ctx=b.new_context(viewport={"width":w,"height":844 if w<500 else 900},device_scale_factor=2 if w<500 else 1)
        ctx.add_init_script("localStorage.setItem('tw_nick',JSON.stringify({nick:'야구사랑',tag:'3307'}));localStorage.setItem('tw_chat_open','1')")
        pg=ctx.new_page()
        pg.goto(B+"/?d=2026-10-09"); pg.wait_for_timeout(2500)
        pg.fill(".ch-form input","LG 내일도 이기자!"); pg.click(".ch-form button"); pg.wait_for_timeout(1500)
        pg.screenshot(path=f"screens/chat_lounge_{tag}.png")
        pg.goto(B+"/game/baseball:5:182037?d=2026-10-09"); pg.wait_for_timeout(2500)
        pg.locator("#gamechat").scroll_into_view_if_needed(); pg.wait_for_timeout(300)
        pg.screenshot(path=f"screens/chat_game_{tag}.png")
        pg.fill("#gamechat .ch-form input","오픈채팅 오세요 t.me/abc"); pg.click("#gamechat .ch-form button"); pg.wait_for_timeout(800)
        pg.locator("#gamechat").screenshot(path=f"screens/chat_blocked_{tag}.png")
        ctx.close()
    b.close()

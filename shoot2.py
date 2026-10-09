from playwright.sync_api import sync_playwright
B="http://localhost:8088"
P=[("home","/"),("yesterday","/?d=2026-10-09"),("game_kbo","/game/baseball:5:182037?d=2026-10-09"),
   ("game_nba","/game/basketball:12:506715?d=2026-10-09"),("game_mlb","/game/baseball:1:190155?d=2026-10-09"),("standings","/standings?league=kbo")]
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,tag in ((390,"mobile"),(1280,"desktop")):
        ctx=b.new_context(viewport={"width":w,"height":844 if w<500 else 900},device_scale_factor=2 if w<500 else 1)
        ctx.add_init_script("localStorage.setItem('tw_fav',JSON.stringify(['baseball:93']))")
        pg=ctx.new_page()
        for n,u in P:
            pg.goto(B+u); pg.wait_for_timeout(1500)
            pg.screenshot(path=f"screens/v2_{n}_{tag}.png",full_page=True)
        if w<500:
            pg.goto(B+"/?d=2026-10-09"); pg.wait_for_timeout(1200); pg.fill("#q","LG"); pg.wait_for_timeout(300)
            pg.screenshot(path="screens/v2_search_mobile.png")
            pg.evaluate("localStorage.setItem('tw_theme','light')"); pg.goto(B+"/?d=2026-10-09"); pg.wait_for_timeout(1200)
            pg.screenshot(path="screens/v2_light_mobile.png",full_page=True); pg.evaluate("localStorage.removeItem('tw_theme')")
        ctx.close()
    b.close()

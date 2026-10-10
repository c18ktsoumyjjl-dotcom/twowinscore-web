import sys
from playwright.sync_api import sync_playwright
B=sys.argv[1];T=sys.argv[2];K=sys.argv[3]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-proxy-server"])
    for mob in (True,False):
        ctx=b.new_context(viewport={"width":390,"height":844} if mob else {"width":1440,"height":900},device_scale_factor=3 if mob else 1,has_touch=mob,is_mobile=mob)
        ctx.add_init_script("localStorage.setItem('tw_nick',JSON.stringify({nick:'투윈',tag:'1234'}))")
        ctx.route("**/*.mp3*",lambda r:r.abort());pg=ctx.new_page();errs=[];pg.on("pageerror",lambda e:errs.append(str(e)))
        tag="m" if mob else "d"
        pg.goto(B+"/game/"+K,wait_until="domcontentloaded",timeout=90000);pg.wait_for_timeout(4000)
        if mob:
            print(tag,pg.evaluate("[document.body.className,getComputedStyle(document.documentElement).getPropertyValue('--mth'),JSON.stringify(document.getElementById('dchat').getBoundingClientRect()),JSON.stringify(document.querySelector('#gamechat .ch-form').getBoundingClientRect()),!!document.querySelector('.gm7ch'),document.querySelectorAll('.ch-m').length]"))
            pg.screenshot(path=f"screens/{T}_m_chat.png")
            pg.click(".gm7ch .L");pg.wait_for_timeout(800);print("cheer",pg.inner_text(".gm7ch"))
            pg.focus("#gamechat .ch-form input");pg.wait_for_timeout(500);print("scrollY after focus",pg.evaluate("scrollY"))
            pg.click("#gm7tab [data-m=info]");pg.wait_for_timeout(800);pg.screenshot(path=f"screens/{T}_m_info.png")
            pg.click("#gm7tab [data-m=chat]");pg.wait_for_timeout(500);print("back",pg.evaluate("document.body.className"))
        else:
            print(tag,"chat visible",pg.is_visible("#gamechat"),pg.is_visible("#gm7"),pg.is_visible("#hero"));pg.screenshot(path=f"screens/{T}_d.png")
        print(tag,"errors",errs);ctx.close()
    b.close()

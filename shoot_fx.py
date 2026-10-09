import sys, asyncio
from playwright.async_api import async_playwright
B,P=sys.argv[1],sys.argv[2]
async def main():
    async with async_playwright() as p:
        br=await p.chromium.launch();errs=[]
        for tag,w,h,mob in (("mobile",390,844,True),("desktop",1440,900,False)):
            pg=await br.new_page(viewport={"width":w,"height":h},device_scale_factor=2 if mob else 1,is_mobile=mob);pg.on("pageerror",lambda e:errs.append(str(e)))
            await pg.goto(B+"/",wait_until="networkidle")
            await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"screens/{P}_hero_{tag}.png",clip={"x":0,"y":0,"width":w,"height":360 if not mob else 260})
            # 로고 샤인 시점 (9s 주기, 2s 지연 → 78~100% 구간)
            await pg.evaluate("document.querySelector('.fx-logo').style.animationDelay='-8.2s'");await pg.wait_for_timeout(150)
            await pg.screenshot(path=f"screens/{P}_hero_shine_{tag}.png",clip={"x":0,"y":0,"width":w,"height":360 if not mob else 260})
            await pg.click("#sndBtn");await pg.wait_for_timeout(300);await pg.screenshot(path=f"screens/{P}_soundmenu_{tag}.png",clip={"x":max(0,w-420),"y":0,"width":min(420,w),"height":300})
        print("errors",errs);await br.close()
asyncio.run(main())

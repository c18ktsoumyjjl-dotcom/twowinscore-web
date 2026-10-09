import sys, asyncio
from playwright.async_api import async_playwright
B=sys.argv[1]
async def main():
    async with async_playwright() as p:
        br=await p.chromium.launch(args=["--autoplay-policy=user-gesture-required"]);errs=[]
        pg=await br.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True);pg.on("pageerror",lambda e:errs.append(str(e)))
        await pg.goto(B+"/",wait_until="networkidle")
        print("hint visible before tap:",await pg.is_visible("#sndHint"))
        await pg.tap(".tag5");await pg.wait_for_timeout(1500)
        print("after first tap: intro paused=",await pg.evaluate("TWSound._a.paused"),"t=",await pg.evaluate("TWSound._a.currentTime.toFixed(2)"),"hint visible:",await pg.is_visible("#sndHint"))
        pg2=await br.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True);await pg2.goto(B+"/",wait_until="networkidle")
        await pg2.tap("#sndHint");await pg2.wait_for_timeout(1200)
        print("test button: paused=",await pg2.evaluate("TWSound._a.paused"),"t=",await pg2.evaluate("TWSound._a.currentTime.toFixed(2)"))
        await pg2.screenshot(path="/tmp/x.png")
        print("errors",errs);await br.close()
asyncio.run(main())

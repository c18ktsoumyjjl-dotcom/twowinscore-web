import sys, asyncio, json
from playwright.async_api import async_playwright
B = sys.argv[1]; P = sys.argv[2]
async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch()
        pg0 = await br.new_page(); await pg0.goto(B + "/api/games?d=2026-10-09")
        j = json.loads(await pg0.inner_text("body"))
        key = [g["key"] for g in j["games"] if g["kind"] == "baseball" and g["state"] == "final"][0]
        fkey = [g["key"] for g in j["games"] if g["kind"] == "football" and g["state"] == "final"][0]
        u = f"{B}/game/{key}?d=2026-10-09"; errs = []
        pg = await br.new_page(viewport={"width": 1440, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(u, wait_until="networkidle"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"screens/{P}_desktop.png")
        await pg.mouse.wheel(0, 1200); await pg.wait_for_timeout(800); await pg.screenshot(path=f"screens/{P}_desktop_scrolled.png")
        await pg.click("#sndBtn"); await pg.wait_for_timeout(300); await pg.screenshot(path=f"screens/{P}_desktop_soundmenu.png")
        await pg.goto(f"{B}/game/{fkey}?d=2026-10-09", wait_until="networkidle"); await pg.wait_for_timeout(1000); await pg.screenshot(path=f"screens/{P}_desktop_football.png")
        m = await br.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True); m.on("pageerror", lambda e: errs.append(str(e)))
        await m.goto(u, wait_until="networkidle"); await m.wait_for_timeout(1000)
        await m.screenshot(path=f"screens/{P}_mobile.png")
        await m.evaluate("scrollTo(0,700)"); await m.wait_for_timeout(800); await m.screenshot(path=f"screens/{P}_mobile_scrolled.png")
        await m.click("#cfab"); await m.wait_for_timeout(1500); await m.screenshot(path=f"screens/{P}_mobile_sheet.png")
        await m.goto(B + "/?d=2026-10-09", wait_until="networkidle"); await m.evaluate("localStorage.setItem('tw_sport','축구')"); await m.reload(wait_until="networkidle"); await m.wait_for_timeout(800)
        await m.screenshot(path=f"screens/{P}_mobile_football_list.png")
        print("errors", errs); await br.close()
asyncio.run(main())

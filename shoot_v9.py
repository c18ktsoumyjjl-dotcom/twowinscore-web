import sys, asyncio
from playwright.async_api import async_playwright
B, P = sys.argv[1], sys.argv[2]
async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch()
        for tag, w, h, mob in (("mobile", 390, 844, True), ("desktop", 1440, 900, False)):
            pg = await br.new_page(viewport={"width": w, "height": h}, device_scale_factor=2 if mob else 1, is_mobile=mob)
            for sp, d in (("전체", "2026-10-09"), ("축구", "2026-10-11")):
                await pg.goto(f"{B}/?d={d}", wait_until="networkidle"); await pg.evaluate(f"localStorage.setItem('tw_sport','{sp}')"); await pg.reload(wait_until="networkidle"); await pg.wait_for_selector(".g5")
                await pg.evaluate("document.querySelector('#list section').scrollIntoView();scrollBy(0,-20)"); await pg.wait_for_timeout(500)
                await pg.screenshot(path=f"screens/{P}_list_{'all' if sp=='전체' else 'football'}_{tag}.png")
            await pg.goto(f"{B}/standings?league=epl", wait_until="networkidle"); await pg.screenshot(path=f"screens/{P}_standings_{tag}.png")
        await br.close()
asyncio.run(main())

import sys, asyncio
from playwright.async_api import async_playwright
B = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8088"
P = sys.argv[2] if len(sys.argv) > 2 else "v6"
async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch()
        for tag, w, h, mob in (("mobile", 390, 844, True), ("desktop", 1440, 900, False)):
            pg = await br.new_page(viewport={"width": w, "height": h}, device_scale_factor=2 if mob else 1, is_mobile=mob)
            await pg.goto(B + "/?d=2026-10-09", wait_until="networkidle"); await pg.wait_for_selector(".g5")
            await pg.evaluate("localStorage.setItem('tw_sport','야구')"); await pg.reload(wait_until="networkidle"); await pg.wait_for_selector(".g5.final")
            await pg.click(".g5.final .tm5.L"); await pg.wait_for_selector(".pv6.open .more6", timeout=60000); await pg.wait_for_timeout(600)
            await pg.evaluate("document.querySelector('.g5.op').scrollIntoView({block:'start'});scrollBy(0,-150)"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f"screens/{P}_expand_{tag}.png")
            for sp in ("축구", "아이스하키"):
                await pg.evaluate(f"localStorage.setItem('tw_sport','{sp}')"); await pg.reload(wait_until="networkidle"); await pg.wait_for_selector(".g5")
                await pg.click(".g5.final .tm5.L"); await pg.wait_for_selector(".pv6.open .more6", timeout=60000); await pg.wait_for_timeout(600)
                await pg.screenshot(path=f"screens/{P}_{'football' if sp=='축구' else 'hockey'}_{tag}.png")
            href = await pg.get_attribute(".pv6.open .more6", "href")
            await pg.goto(B + href, wait_until="networkidle"); await pg.screenshot(path=f"screens/{P}_detail_hockey_{tag}.png", full_page=True)
            await pg.goto(B + "/?d=2026-10-09", wait_until="networkidle"); await pg.evaluate("localStorage.setItem('tw_sport','야구')"); await pg.reload(wait_until="networkidle")
            await pg.wait_for_selector(".g5.final"); await pg.click(".g5.final .tm5.L"); await pg.wait_for_selector(".pv6.open .more6", timeout=60000)
            href = await pg.get_attribute(".pv6.open .more6", "href")
            await pg.goto(B + href, wait_until="networkidle"); await pg.screenshot(path=f"screens/{P}_detail_{tag}.png", full_page=True)
            await pg.goto(B + "/standings?league=epl", wait_until="networkidle"); await pg.screenshot(path=f"screens/{P}_standings_epl_{tag}.png")
        await br.close()
asyncio.run(main())

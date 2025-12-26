import re
import scrapy
from urllib.parse import urljoin

from kp.items import KpArticleItem


class KpArticlesSpider(scrapy.Spider):
    name = "kp_articles"
    allowed_domains = ["kp.ru"]
    start_urls = ["https://www.kp.ru/online/"]

    # Можно переопределить: scrapy crawl kp_articles -a limit=1000
    POSTS_LIMIT = 1000

    # Защита от бесконечного цикла, если "Показать еще" перестанет давать новые ссылки
    MAX_SHOW_MORE_CLICKS = 10000
    STALL_LIMIT = 10  # сколько итераций подряд допускаем без прироста уникальных ссылок

    def __init__(self, limit=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.posts_limit = int(limit) if limit is not None else int(self.POSTS_LIMIT)

    def start_requests(self):
        yield scrapy.Request(
            "https://www.kp.ru/online/",
            callback=self.parse_list,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded"},
            },
        )

    async def parse_list(self, response):
        """
        Важно: новые ссылки подгружаются JS-ом по кнопке "Показать еще".
        Поэтому:
        - держим Playwright page открытым
        - кликаем кнопку много раз
        - после каждого клика собираем href из DOM (а не из исходного HTML ответа)
        """
        page = response.meta["playwright_page"]

        def normalize_url(u: str) -> str:
            return (u or "").split("?")[0].strip()

        async def try_dismiss_overlays():
            # иногда поверх страницы всплывают баннеры/попапы, из-за них клик не проходит
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

            candidates = [
                "button:has-text('Принять')",
                "button:has-text('Согласен')",
                "button:has-text('Согласиться')",
                "button:has-text('ОК')",
            ]
            for sel in candidates:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=1500, force=True)
                        break
                except Exception:
                    pass

        async def collect_urls_from_dom():
            # берем ССЫЛКИ прямо из DOM после JS-подгрузки
            hrefs = await page.eval_on_selector_all(
                "a[href*='/online/news/']",
                "els => els.map(e => e.href)",
            )
            urls = []
            for u in hrefs or []:
                u = normalize_url(u)
                if u:
                    urls.append(u)
            return urls

        async def click_show_more_and_wait(prev_anchor_count: int):
            # кнопка может иметь разные классы, поэтому ищем по тексту, включая "ещё"
            btn = page.locator("button:has-text('Показать еще'), button:has-text('Показать ещё')").first
            if await btn.count() == 0:
                return False

            await try_dismiss_overlays()

            # докручиваем до кнопки и кликаем принудительно
            try:
                await btn.scroll_into_view_if_needed(timeout=10_000)
            except Exception:
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    return False

            try:
                await btn.click(timeout=10_000, force=True)
            except Exception:
                return False

            # ждём, что в DOM изменится количество ссылок (или хотя бы пройдут запросы)
            try:
                await page.wait_for_function(
                    "(prev) => document.querySelectorAll(\"a[href*='/online/news/']\").length !== prev",
                    prev_anchor_count,
                    timeout=25_000,
                )
            except Exception:
                # иногда количество не меняется мгновенно, но контент все равно обновляется
                pass

            # небольшая пауза на отрисовку
            try:
                await page.wait_for_timeout(600)
            except Exception:
                pass

            return True

        seen = set()
        ordered_urls = []

        try:
            await page.wait_for_selector("button:has-text('Показать еще'), button:has-text('Показать ещё')", timeout=30_000)
        except Exception:
            # даже если кнопка не найдена, соберём то, что есть
            pass

        # первичный сбор
        for u in await collect_urls_from_dom():
            if u not in seen:
                seen.add(u)
                ordered_urls.append(u)
                if len(ordered_urls) >= self.posts_limit:
                    break

        clicks = 0
        stalls = 0

        while len(ordered_urls) < self.posts_limit and clicks < self.MAX_SHOW_MORE_CLICKS and stalls < self.STALL_LIMIT:
            prev_unique = len(ordered_urls)
            prev_anchor_count = await page.locator("a[href*='/online/news/']").count()

            ok = await click_show_more_and_wait(prev_anchor_count)
            if not ok:
                break
            clicks += 1

            # после клика — собираем текущие ссылки из DOM
            current = await collect_urls_from_dom()
            for u in current:
                if u not in seen:
                    seen.add(u)
                    ordered_urls.append(u)
                    if len(ordered_urls) >= self.posts_limit:
                        break

            if len(ordered_urls) == prev_unique:
                stalls += 1
            else:
                stalls = 0

            if clicks % 10 == 0:
                self.logger.info("Collected %s/%s unique URLs (clicks=%s, stalls=%s)", len(ordered_urls), self.posts_limit, clicks, stalls)

        try:
            await page.close()
        except Exception:
            pass

        self.logger.info("Final collected URLs: %s (requested %s)", len(ordered_urls), self.posts_limit)

        # Отдаём в парсинг статей (Playwright для статей обычно не нужен)
        for url in ordered_urls[: self.posts_limit]:
            yield scrapy.Request(url, callback=self.parse_article, dont_filter=True)

    def parse_article(self, response):
        def clean_text(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "")).strip()

        source_url = response.url.split("?")[0]

        title = clean_text(
            response.xpath("normalize-space(//h1)").get()
            or response.xpath("//meta[@property='og:title']/@content").get()
        )

        description = clean_text(
            response.xpath("//meta[@name='description']/@content").get()
            or response.xpath("//meta[@property='og:description']/@content").get()
        )

        publication_datetime = clean_text(
            response.xpath("//meta[@property='article:published_time']/@content").get()
            or response.xpath("//time/@datetime").get()
        )

        header_photo_url = clean_text(response.xpath("//meta[@property='og:image']/@content").get()) or None

        kw_str = response.xpath("//meta[@name='keywords']/@content").get()
        if kw_str:
            keywords = [clean_text(x) for x in kw_str.split(",") if clean_text(x)]
        else:
            keywords = response.xpath("//a[contains(@href,'/tag/')]/text()").getall()
            keywords = [clean_text(x) for x in keywords if clean_text(x)]

        author_meta = response.xpath("//meta[@name='author']/@content").get()
        if author_meta:
            authors = [clean_text(x) for x in re.split(r",|;|&", author_meta) if clean_text(x)]
        else:
            authors = response.xpath(
                "//*[contains(@class,'author') or contains(@class,'Authors') or contains(@class,'authors')]//text()"
            ).getall()
            authors = [clean_text(x) for x in authors if clean_text(x)]
            authors = list(dict.fromkeys(authors))

        # Берём всё содержимое первого div data-gtm-el="content-body"
        # исключая то, что внутри div data-wide="true"
        content_root = response.xpath("(//div[@data-gtm-el='content-body'])[1]")
        parts = content_root.xpath(
            ".//text()[not(ancestor::div[@data-wide='true'])]"
            "[not(ancestor::script) and not(ancestor::style)]"
        ).getall()
        parts = [clean_text(x) for x in parts if clean_text(x)]
        article_text = "\n".join(parts)

        yield KpArticleItem(
            title=title,
            description=description,
            article_text=article_text,
            publication_datetime=publication_datetime,
            header_photo_url=header_photo_url,
            header_photo_base64=None,  # заполнит PhotoDownloaderPipeline
            keywords=keywords,
            authors=authors,
            source_url=source_url,
        )

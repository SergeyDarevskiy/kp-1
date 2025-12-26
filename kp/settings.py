BOT_NAME = "kp"

SPIDER_MODULES = ["kp.spiders"]
NEWSPIDER_MODULE = "kp.spiders"

ROBOTSTXT_OBEY = False

# --- Playwright ---
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 60_000

# --- Mongo (можно не трогать, если localhost:27017) ---
MONGO_HOST = "localhost"
MONGO_PORT = 27017
MONGO_COLLECTION = "kp_articles"

# --- PhotoDownloaderPipeline ---
RESULT_IMAGE_QUALITY = 35

# Важно: сначала фото (меньший номер), потом Mongo (больший номер)
ITEM_PIPELINES = {
    "kp.pipelines.PhotoDownloaderPipeline": 100,
    "kp.pipelines.MongoPipeline": 200,
}

# Рекомендуемо (чтобы не перегружать сайт)
CONCURRENT_REQUESTS = 8
DOWNLOAD_DELAY = 0.2

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Scrapy settings for scraper project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

import os
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "scraper"

SPIDER_MODULES = ["scraper.spiders"]
NEWSPIDER_MODULE = "scraper.spiders"

ADDONS = {}


# Crawl responsibly by identifying yourself (and your website) on the user-agent
USER_AGENT = "kedra-wrc-scraper/0.1"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True #

# Concurrency and throttling settings
#CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = int(os.getenv("CONCURRENT_REQUESTS_PER_DOMAIN")) # Limit the number of requests we send to the same website at once.
DOWNLOAD_DELAY = float(os.getenv("DOWNLOAD_DELAY"))
DOWNLOAD_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS"))

# Disable cookies (enabled by default)
#COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
#TELNETCONSOLE_ENABLED = False

# Override the default request headers:
#DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
#}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
#SPIDER_MIDDLEWARES = {
#    "scraper.middlewares.ScraperSpiderMiddleware": 543,
#}

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#DOWNLOADER_MIDDLEWARES = {
#    "scraper.middlewares.ScraperDownloaderMiddleware": 543,
#}

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
#EXTENSIONS = {
#    "scrapy.extensions.telnet.TelnetConsole": None,
#}

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
    "scraper.pipelines.MongoPipeline": 400,
    "scraper.pipelines.MinioPipeline": 300, # runs first bc of file_hash and file_path
}

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DATABASE = os.getenv("MONGO_DATABASE")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION")


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET_RAW = os.getenv("MINIO_BUCKET_RAW")
# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html

AUTOTHROTTLE_ENABLED = True # lets scrapy adjust the request speed automatically based on how the # server responds
# which better than choosing one fixed delay ourselves.
# The initial download delay
AUTOTHROTTLE_START_DELAY = float(os.getenv("AUTOTHROTTLE_START_DELAY"))
 # We can adjust this later if testing shows that the website can handle more or needs less traffic.


AUTOTHROTTLE_MAX_DELAY = float(os.getenv("AUTOTHROTTLE_MAX_DELAY"))
# This gives # us a reasonable upper limit if the server starts responding slowly.

# The average number of requests Scrapy should be sending in parallel to
# each remote server
AUTOTHROTTLE_TARGET_CONCURRENCY = float(os.getenv("AUTOTHROTTLE_TARGET_CONCURRENCY")) # Aim for around 2 requests being processed at the same time on average.
# This is a conservative starting point, and we can increase it after
# testing the scraper.

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
#HTTPCACHE_ENABLED = True
#HTTPCACHE_EXPIRATION_SECS = 0
#HTTPCACHE_DIR = "httpcache"
#HTTPCACHE_IGNORE_HTTP_CODES = []
#HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"


RETRY_ENABLED = True # Retry requests that fail temporarily instead of giving up immediately.
 # This helps prevent temporary network or server errors from causing lost data.
RETRY_TIMES = int(os.getenv("RETRY_TIMES")) # Try a failed request up to x more times before treating it as a failure.
RETRY_HTTP_CODES = [500, 502, 503, 504, 429, 408] # Retry errors that are usually temporary, such as server errors,
 # rate limiting (429), and request timeouts (408).
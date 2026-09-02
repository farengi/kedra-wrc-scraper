from datetime import datetime, timezone
import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import FormRequest
from scraper.items import DecisionItem
from log_utils import get_logger

json_logger = get_logger("wrc_decisions")


class WrcDecisionsSpider(scrapy.Spider):
    name = "wrc_decisions"
    allowed_domains = ["www.workplacerelations.ie"]
    start_urls = [
        "https://www.workplacerelations.ie/en/search/?advance=true"
    ]

    BODY_VALUES = {
        "employment_appeals_tribunal": (
            "ctl00$ContentPlaceHolder_Main$CB2$CB2_0",
            "2",
         ),
        "equality_tribunal": (
            "ctl00$ContentPlaceHolder_Main$CB2$CB2_1",
            "1",
        ),
        "labour_court": (
            "ctl00$ContentPlaceHolder_Main$CB2$CB2_2",
            "3",
        ),
        "workplace_relations_commission": (
            "ctl00$ContentPlaceHolder_Main$CB2$CB2_3",
            "15376",
        ),
    }
    # identified by inspecting the WRC search form's HTML and mapping each checkbox ID/name to its visible body label.

    def __init__(
        self,
        start_date=None,
        end_date=None,
        body=None,
        partition_date=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        if not start_date or not end_date or not body or not partition_date:
            raise CloseSpider(
                "Required arguments: start_date, end_date, body, "
                "and partition_date"
            )
        # these values are required so each crawl has a clear scope

        if body not in self.BODY_VALUES:
            valid_bodies = ", ".join(self.BODY_VALUES)
            raise CloseSpider(
                f"Unknown body '{body}'. Choose one of: {valid_bodies}"
            )
        # stop early if an invalid body was passed

        self.start_date = start_date
        self.end_date = end_date
        self.body = body
        self.partition_date = partition_date
        self.scraped_at = datetime.now(timezone.utc).isoformat()

        # counters for the end-of-run summary
        self.records_found = 0
        self.records_scraped = 0
        self.records_failed = 0

        json_logger.info("Spider started", extra={"extra_data": {
            "event": "spider_started",
            "partition_date": self.partition_date,
            "body": self.body,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }})

    def parse(self, response):
        body_name, body_value = self.BODY_VALUES[self.body]

        formdata = {
            "ctl00$ContentPlaceHolder_Main$TextBox2": self.start_date,
            "ctl00$ContentPlaceHolder_Main$TextBox3": self.end_date,
            body_name: body_value,
        }

        yield FormRequest.from_response(
            response,
            formid="form",
            formdata=formdata,
            clickdata={"id": "refine_btn"},
            callback=self.parse_results,
        )

    def parse_results(self, response):
        for result in response.css("li.each-item"):
            self.records_found += 1

            identifier = result.css("h2.title a::text").get()
            if not identifier:
                json_logger.warning("Missing identifier, skipping record", extra={"extra_data": {
                    "event": "extraction_failed",
                    "partition_date": self.partition_date,
                    "body": self.body,
                    "url": response.url,
                }})
                self.records_failed += 1
                continue  # skip this <li>, move to the next one in the loop
            decision_date = result.css("span.date::text").get()
            description = result.css("p.description::attr(title)").get()
            if description:
                description = " ".join(description.split())
            href = result.css("h2.title a::attr(href)").get()
            detail_url = response.urljoin(href) if href else None

            record_meta = dict(
                body=self.body,
                identifier=identifier,
                description=description,
                date=decision_date,
                partition_date=self.partition_date,
                source_url=response.url,
                detail_url=detail_url,
                scraped_at=self.scraped_at,
            )

            if detail_url:
                yield scrapy.Request(
                    detail_url,
                    callback=self.parse_document,
                    cb_kwargs={"record_meta": record_meta},
                    errback=self.handle_download_error,
                )
            else:
                # no document to fetch — still yield the metadata-only item
                json_logger.warning("No detail_url for record", extra={"extra_data": {
                    "event": "download_failed",
                    "partition_date": self.partition_date,
                    "body": self.body,
                    "identifier": identifier,
                    "url": None,
                    "error_code": None,
                    "reason": "missing detail_url",
                }})
                self.records_failed += 1
                yield DecisionItem(**record_meta)

        next_page = response.css("a.next::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse_results)

    def parse_document(self, response, record_meta):
        self.records_scraped += 1
        yield DecisionItem(
            **record_meta,
            file_bytes=response.body,
            content_type=response.headers.get("Content-Type", b"").decode(errors="ignore"),
        )

    def handle_download_error(self, failure):
        request = failure.request
        record_meta = request.cb_kwargs["record_meta"]
        status = getattr(failure.value, "response", None)
        status_code = status.status if status is not None else None

        self.records_failed += 1
        json_logger.warning("Download failed", extra={"extra_data": {
            "event": "download_failed",
            "partition_date": self.partition_date,
            "body": self.body,
            "identifier": record_meta.get("identifier"),
            "url": request.url,
            "error_code": status_code,
            "reason": str(failure.value),
        }})
        yield DecisionItem(**record_meta)  # file_bytes/content_type stay None

    def closed(self, reason):
        json_logger.info("Spider run summary", extra={"extra_data": {
            "event": "run_summary",
            "partition_date": self.partition_date,
            "body": self.body,
            "records_found": self.records_found,
            "records_scraped": self.records_scraped,
            "records_failed": self.records_failed,
            "close_reason": reason,
        }})
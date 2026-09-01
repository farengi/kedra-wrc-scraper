from datetime import datetime, timezone
import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import FormRequest
from scraper.items import DecisionItem

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
         # loop through every decision shown on the results page
            identifier = result.css("h2.title a::text").get()
            decision_date = result.css("span.date::text").get()
            description = result.css("p.description::attr(title)").get()
            if description:
                 description = " ".join(description.split())
            # collapses all whitespace/newlines into single spaces
            href = result.css("h2.title a::attr(href)").get()

            yield DecisionItem(
                body=self.body,
                #tagging which body this came from (needed once everything's mixed into one Mongo collection)
                identifier=identifier,
                description=description,
                date=decision_date,
                partition_date=self.partition_date,
                source_url=response.url,
                # good for debugging and tracing back to the original search results page
                detail_url=response.urljoin(href) if href else None,
                scraped_at=self.scraped_at,
                # when this spider run started for tracking and debugging
            )
            # extract the metadata needed for each decision

        next_page = response.css("a.next::attr(href)").get()
        if next_page:
        #pagniation
            yield response.follow(next_page, callback=self.parse_results)
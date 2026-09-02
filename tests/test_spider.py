import pytest
from scrapy.http import HtmlResponse, Request
from scrapy.exceptions import CloseSpider

from scraper.spiders.wrc_decisions import WrcDecisionsSpider


def test_spider_requires_scope_arguments( ):
    with pytest.raises(CloseSpider):
        WrcDecisionsSpider()


def test_spider_rejects_unknown_body():
    with pytest.raises(CloseSpider):
        WrcDecisionsSpider(
            start_date="1/1/2025",
            end_date="31/1/2025",
            body="unknown",
            partition_date="2025-01",
        )


def test_parse_results_extracts_metadata_and_schedules_detail_request():
    spider = WrcDecisionsSpider(
        start_date="1/1/2025",
        end_date="31/1/2025",
        body="labour_court",
        partition_date="2025-01",
    )
    html = b"""
    <html><body><ul>
      <li class='each-item'>
        <h2 class='title'><a href='/decision/123'>ABC-123</a></h2>
        <span class='date'>15/01/2025</span>
        <p class='description' title='  A   description  '></p>
      </li>
    </ul></body></html>
    """
    response = HtmlResponse(
        url="https://www.workplacerelations.ie/en/search/",
        body=html,
        encoding="utf-8",
        request=Request("https://www.workplacerelations.ie/en/search/" ),
    )

    results = list(spider.parse_results(response))

    assert spider.records_found == 1
    assert len(results) == 1
    assert results[0].url == "https://www.workplacerelations.ie/decision/123"
    assert results[0].cb_kwargs["record_meta"]["identifier"] == "ABC-123"
    assert results[0].cb_kwargs["record_meta"]["description"] == "A description"
    assert results[0].cb_kwargs["record_meta"]["partition_date"] == "2025-01"
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


def _record_meta():
    return {
        "body": "equality_tribunal",
        "identifier": "DEC-S2002-131",
        "description": "A decision",
        "date": "03/12/2002",
        "partition_date": "2002-12",
        "source_url": "https://www.workplacerelations.ie/en/search/",
        "detail_url": "https://www.workplacerelations.ie/en/cases/2002/december/dec-s2002-131.html",
        "scraped_at": "2025-01-01T00:00:00+00:00",
    }


def test_parse_detail_page_follows_decision_pdf_not_cookie_policy_pdf():
    spider = WrcDecisionsSpider(
        start_date="1/12/2002",
        end_date="31/12/2002",
        body="equality_tribunal",
        partition_date="2002-12",
    )
    html = b"""
    <html><body>
      <a href="/en/privacy-policy/cookie_policy.pdf">Cookie Policy</a>
      <div class="content">
        <a href="/en/Equality_Tribunal_Import/Database-of-Decisions/2002/Equal-Status-Decisions/DEC-S2002-131.pdf">decision PDF</a>
      </div>
    </body></html>
    """
    response = HtmlResponse(
        url="https://www.workplacerelations.ie/en/cases/2002/december/dec-s2002-131.html",
        body=html,
        encoding="utf-8",
        request=Request("https://www.workplacerelations.ie/en/cases/2002/december/dec-s2002-131.html"),
    )

    results = list(spider.parse_detail_page(response, _record_meta()))

    assert len(results) == 1
    assert results[0].url.endswith("/DEC-S2002-131.pdf")
    assert results[0].cb_kwargs["record_meta"]["identifier"] == "DEC-S2002-131"


def test_parse_detail_page_yields_metadata_only_when_no_attachment_exists():
    spider = WrcDecisionsSpider(
        start_date="1/12/2002",
        end_date="31/12/2002",
        body="equality_tribunal",
        partition_date="2002-12",
    )
    response = HtmlResponse(
        url="https://www.workplacerelations.ie/en/cases/2002/december/no-file.html",
        body=b'<div class="content"><p>Decision text</p></div>',
        encoding="utf-8",
        request=Request("https://www.workplacerelations.ie/en/cases/2002/december/no-file.html"),
    )

    results = list(spider.parse_detail_page(response, _record_meta()))

    assert len(results) == 1
    assert results[0].identifier == "DEC-S2002-131"
    assert results[0].file_bytes is None
    assert results[0].content_type is None
    assert spider.records_failed == 1

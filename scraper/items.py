# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

from dataclasses import dataclass


@dataclass
class DecisionItem:
    # define the fields for your item here like:
    # name: str | None = None
    body: str
    identifier: str
    description: str
    date: str
    partition_date: str
    source_url: str
    detail_url: str | None
    scraped_at: str

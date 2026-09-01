# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from pymongo import ASCENDING, MongoClient


class MongoPipeline:
    def __init__(self, mongo_uri, mongo_database, mongo_collection):
        self.mongo_uri = mongo_uri
        self.mongo_database = mongo_database
        self.mongo_collection = mongo_collection
        self.client = None
        self.collection = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            mongo_uri=crawler.settings.get("MONGO_URI"),
            mongo_database=crawler.settings.get("MONGO_DATABASE"),
            mongo_collection=crawler.settings.get("MONGO_COLLECTION"),
        )

    def open_spider(self, spider):
        self.client = MongoClient(self.mongo_uri)
        database = self.client[self.mongo_database]
        self.collection = database[self.mongo_collection]

        self.collection.create_index(
            [("body", ASCENDING), ("identifier", ASCENDING)],
            unique=True,
        )

    def process_item(self, item, spider):
        document = ItemAdapter(item).asdict()

        self.collection.update_one(
            {"body": document["body"], "identifier": document["identifier"]},
            {"$set": document},
            upsert=True,
        )

        return item

    def close_spider(self, spider):
        if self.client is not None:
            self.client.close()

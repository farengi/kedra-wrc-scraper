# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError
import boto3
import hashlib
import re
import requests
from botocore.exceptions import ClientError
from log_utils import get_logger

json_logger = get_logger("pipelines")


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

    # scraper/pipelines.py — MongoPipeline.process_item

    def process_item(self, item, spider):
        document = ItemAdapter(item).asdict()
        update_fields = {k: v for k, v in document.items() if v is not None}

        try:
            self.collection.update_one(
                {"body": document["body"], "identifier": document["identifier"]},
                {"$set": update_fields},
                upsert=True,
            )
        except PyMongoError as e:
            json_logger.warning("Mongo write failed", extra={"extra_data": {
                "event": "mongo_write_failed",
                "body": document.get("body"),
                "identifier": document.get("identifier"),
                "error": str(e),
            }})

        return item
        

    def close_spider(self, spider):
        if self.client is not None:
            self.client.close()

# minor duplication we can join them into one pipeline but for now we will keep them separate

class MinioPipeline:
    def __init__(
        self,
        endpoint,
        access_key,
        secret_key,
        bucket_raw,
        mongo_uri,
        mongo_database,
        mongo_collection,
    ):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_raw = bucket_raw
        self.mongo_uri = mongo_uri
        self.mongo_database = mongo_database
        self.mongo_collection_name = mongo_collection

        self.s3 = None
        self.mongo_client = None
        self.mongo_collection = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            endpoint=crawler.settings.get("MINIO_ENDPOINT"),
            access_key=crawler.settings.get("MINIO_ACCESS_KEY"),
            secret_key=crawler.settings.get("MINIO_SECRET_KEY"),
            bucket_raw=crawler.settings.get("MINIO_BUCKET_RAW"),
            mongo_uri=crawler.settings.get("MONGO_URI"),
            mongo_database=crawler.settings.get("MONGO_DATABASE"),
            mongo_collection=crawler.settings.get("MONGO_COLLECTION"),
        )

    def open_spider(self, spider):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
        try:
            self.s3.head_bucket(Bucket=self.bucket_raw)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                self.s3.create_bucket(Bucket=self.bucket_raw)
            else:
                raise

        self.mongo_client = MongoClient(self.mongo_uri)
        self.mongo_collection = self.mongo_client[self.mongo_database][
            self.mongo_collection_name
        ]

    def close_spider(self, spider):
        if self.s3 is not None:
            self.s3.close()
        if self.mongo_client is not None:
            self.mongo_client.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        file_bytes = adapter.get("file_bytes")
        adapter.pop("file_bytes", None)  # captured locally; strip immediately so no path can leak raw bytes into MongoPipeline

        if not file_bytes:
            spider.logger.warning(
                f"No file downloaded for {adapter.get('identifier')}, skipping upload"
            )
            return item

        try:
            existing = self.mongo_collection.find_one(
                {"body": adapter["body"], "identifier": adapter["identifier"]}
            )
        except PyMongoError as e:
            json_logger.warning("Mongo read failed", extra={"extra_data": {
                "event": "mongo_read_failed",
                "body": adapter.get("body"),
                "identifier": adapter.get("identifier"),
                "error": str(e),
            }})
            return item

        file_hash = hashlib.sha256(file_bytes).hexdigest()

        if existing and existing.get("file_hash") == file_hash:
            spider.logger.info(f"Unchanged, skipping upload for {adapter['identifier']}")
            adapter["file_path"] = existing.get("file_path")
            adapter["file_hash"] = file_hash
            return item

        content_type = adapter.get("content_type") or "application/octet-stream"
        detail_url = adapter.get("detail_url") or ""
        extension = "pdf" if "pdf" in content_type or detail_url.lower().endswith(".pdf") else "docx" if "docx" in content_type or detail_url.lower().endswith(".docx") else "doc" if "doc" in content_type or detail_url.lower().endswith(".doc") else "html"
        safe_identifier = re.sub(r"[\\/]", "_", adapter["identifier"].strip())
        file_key = f"{adapter['body']}/{safe_identifier}.{extension}"
        
        try:
            self.s3.put_object(
                Bucket=self.bucket_raw,
                Key=file_key,
                Body=file_bytes,
                ContentType=content_type,
            )
        except ClientError as e:
            spider.logger.warning(f"Failed to upload {file_key} to MinIO: {e}")
            return item

        adapter["file_path"] = file_key
        adapter["file_hash"] = file_hash
        return item
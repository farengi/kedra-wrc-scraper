import hashlib

from scraper.pipelines import MinioPipeline


class FakeCollection:
    def __init__(self, existing ):
        self.existing = existing

    def find_one(self, query):
        return self.existing


class FakeS3:
    def __init__(self):
        self.put_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)


class FakeSpider:
    class Logger:
        def info(self, message):
            pass

        def warning(self, message):
            pass

    logger = Logger()


def make_pipeline(existing, s3):
    pipeline = MinioPipeline(
        endpoint="http://minio",
        access_key="key",
        secret_key="secret",
        bucket_raw="raw",
        mongo_uri="mongodb://unused",
        mongo_database="db",
        mongo_collection="landing",
     )
    pipeline.mongo_collection = FakeCollection(existing)
    pipeline.s3 = s3
    return pipeline


def test_unchanged_file_is_not_reuploaded():
    payload = b"same bytes"
    digest = hashlib.sha256(payload).hexdigest()
    s3 = FakeS3()
    pipeline = make_pipeline(
        {
            "body": "labour_court",
            "identifier": "ABC123",
            "file_hash": digest,
            "file_path": "labour_court/ABC123.pdf",
        },
        s3,
    )

    item = {
        "body": "labour_court",
        "identifier": "ABC123",
        "detail_url": "https://example.test/ABC123.pdf",
        "content_type": "application/pdf",
        "file_bytes": payload,
    }

    returned = pipeline.process_item(item, FakeSpider( ))

    assert returned["file_path"] == "labour_court/ABC123.pdf"
    assert returned["file_hash"] == digest
    assert s3.put_calls == []


def test_changed_file_is_uploaded_with_hash_and_path():
    payload = b"new bytes"
    s3 = FakeS3()
    pipeline = make_pipeline(
        {
            "body": "labour_court",
            "identifier": "ABC123",
            "file_hash": "old-hash",
            "file_path": "labour_court/ABC123.pdf",
        },
        s3,
    )

    item = {
        "body": "labour_court",
        "identifier": "ABC123",
        "detail_url": "https://example.test/ABC123.pdf",
        "content_type": "application/pdf",
        "file_bytes": payload,
    }

    returned = pipeline.process_item(item, FakeSpider( ))

    assert returned["file_hash"] == hashlib.sha256(payload).hexdigest()
    assert returned["file_path"] == "labour_court/ABC123.pdf"
    assert len(s3.put_calls) == 1
    assert s3.put_calls[0]["Bucket"] == "raw"
    assert s3.put_calls[0]["Body"] == payload
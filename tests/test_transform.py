from io import BytesIO

import pytest

from transform.transform import (
    clean_html,
    document_extension,
    iter_matching_records,
    parse_date,
    safe_filename,
    transform_record,
)


def test_parse_date_accepts_supported_formats():
    assert parse_date("13/01/2025").isoformat() == "2025-01-13"
    assert parse_date("2025-01-13").isoformat() == "2025-01-13"
    assert parse_date("2025/01/13").isoformat() == "2025-01-13"
    assert parse_date("13-01-2025").isoformat() == "2025-01-13"


def test_parse_date_rejects_invalid_date():
    with pytest.raises(ValueError):
        parse_date("not-a-date")


def test_safe_filename_replaces_path_separators():
    assert safe_filename("  ABC/123\\x  ", ".html") == "ABC_123_x.html"


def test_document_extension_normalizes_supported_suffixes():
    assert document_extension("body/file.PDF") == ".pdf"
    assert document_extension("body/file.docx") == ".docx"
    assert document_extension("body/file.unknown") == ".html"


def test_clean_html_removes_site_elements_but_keeps_decision_content():
    source = b"""
    <html><body>
      <header>Header</header>
      <nav>Navigation</nav>
      <main><h1>Decision title</h1><p>Substantive decision text</p></main>
      <footer>Footer</footer>
      <script>bad()</script>
    </body></html>
    """

    result = clean_html(source).decode("utf-8")

    assert "Header" not in result
    assert "Navigation" not in result
    assert "Footer" not in result
    assert "bad()" not in result
    assert "Decision title" in result
    assert "Substantive decision text" in result


class FakeCollection:
    def __init__(self, records):
        self.records = records

    def find(self):
        return iter(self.records)


def test_iter_matching_records_filters_by_decision_date():
    collection = FakeCollection([
        {"identifier": "inside", "date": "15/01/2025"},
        {"identifier": "before", "date": "31/12/2024"},
        {"identifier": "after", "date": "01/02/2025"},
        {"identifier": "missing-date"},
    ])

    records = list(
        iter_matching_records(
            collection,
            parse_date("01/01/2025"),
            parse_date("31/01/2025"),
        )
    )

    assert [record["identifier"] for record in records] == ["inside"]


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeS3:
    def __init__(self, data, content_type="text/html"):
        self.data = data
        self.content_type = content_type
        self.put_calls = []
        self.get_calls = []

    def get_object(self, Bucket, Key):
        self.get_calls.append({"Bucket": Bucket, "Key": Key})
        return {
            "Body": FakeBody(self.data),
            "ContentType": self.content_type,
        }

    def put_object(self, **kwargs):
        body = kwargs["Body"]
        if isinstance(body, BytesIO):
            body = body.getvalue()
        self.put_calls.append({**kwargs, "Body": body})



def test_transform_record_cleans_html_and_writes_curated_metadata():
    raw = b"<html><body><nav>remove</nav><p>keep this</p></body></html>"
    s3 = FakeS3(raw)
    record = {
        "body": "wrc",
        "identifier": "ABC/123",
        "partition_date": "2025-01",
        "file_path": "wrc/body/source.html",
    }

    result = transform_record(record, s3, "raw", "curated")

    assert result["document_type"] == "html"
    assert result["curated_key"] == "wrc/2025-01/ABC_123.html"
    assert len(s3.put_calls) == 1
    uploaded = s3.put_calls[0]
    assert uploaded["Bucket"] == "curated"
    assert b"remove" not in uploaded["Body"]
    assert b"keep this" in uploaded["Body"]
    assert result["curated_hash"]


def test_transform_record_preserves_pdf_bytes():
    pdf_bytes = b"%PDF-1.7\nraw bytes"
    s3 = FakeS3(pdf_bytes, content_type="application/pdf")
    record = {
        "body": "wrc",
        "identifier": "ABC123",
        "partition_date": "2025-01",
        "file_path": "wrc/body/source.pdf",
    }

    result = transform_record(record, s3, "raw", "curated")

    assert result["document_type"] == "pdf"
    assert s3.put_calls[0]["Body"] == pdf_bytes
    assert result["file_size_bytes"] == len(pdf_bytes)


def test_transform_record_reports_missing_file_path():
    record = {"body": "wrc", "identifier": "ABC123"}

    with pytest.raises(ValueError, match="No file_path"):
        transform_record(record, FakeS3(b""), "raw", "curated")
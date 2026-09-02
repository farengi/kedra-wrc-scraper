"""Transform files from the WRC Landing Zone into the Curated Zone."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import PurePosixPath
from log_utils import get_logger

import boto3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()
logger = get_logger("transform")

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y")  # WRC uses D/M/YYYY, but we also accept ISO and Y/M/D
# wrc metadata uses dates such as 13/01/2025,
# while command-line users may reasonably provide 2025-01-13.
# this tuple tells the script to accept both formats.

def parse_date(value: str) -> date:
    """Parse either a WRC date or an ISO date."""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(
        f"Invalid date '{value}'. Use D/M/YYYY or YYYY-MM-DD."
    )


def clean_html(file_bytes: bytes) -> bytes:
    """Remove common site-level elements and return cleaned HTML bytes."""
    soup = BeautifulSoup(file_bytes, "html.parser")
    # BeautifulSoup parses the HTML so the script can find elements such
    # as nav, header, and footer instead of treating the file as one large string

    elements_to_remove = (
    "nav",
    "header",
    "footer",
    "button",
    "script",
    "style",
    "#globalCookieBar",
    ".social-banner.xs-hidden",
    ".searchbanner",
    ".col-sm-3",
    "#binderFixed")

    for selector in elements_to_remove:
        for element in soup.select(selector):
            element.decompose()
    # the cleaned HTML is converted back into bytes
    # so it can be uploaded to MinIO.

    return soup.encode(formatter="html")


def safe_filename(identifier: str, extension: str) -> str:
    """Create identifier.ext while preventing path traversal."""
    cleaned_identifier = re.sub(r"[\\/]", "_", identifier.strip()) #removes leading/trailing whitespace and replaces slash characters.
    return f"{cleaned_identifier}{extension}"


def document_extension(file_path: str) -> str:
    """Return a normalized file extension, defaulting to HTML."""
    suffix = PurePosixPath(file_path).suffix.lower()
    return suffix if suffix in {".html", ".htm", ".pdf", ".doc", ".docx"} else ".html"


def iter_matching_records(collection, start: date, end: date):
    """Yield Landing metadata whose decision date is within the range."""
    for record in collection.find():
        raw_date = record.get("date")
        if not raw_date:
            continue

        try:
            record_date = parse_date(raw_date)
        except ValueError:
            logger.warning("Skipping record: invalid date", extra={"extra_data": {
                "identifier": record.get("identifier"),
                "raw_date": raw_date,
            }})
            continue
        # filter by the legal decision date, not by the ingestion partition.
        if start <= record_date <= end:
            yield record


def transform_record(record, s3, raw_bucket, curated_bucket):
    """Read one raw object, transform it, and upload the curated object."""
    raw_key = record["file_path"]
    raw_object = s3.get_object(Bucket=raw_bucket, Key=raw_key)
    raw_bytes = raw_object["Body"].read()

    extension = document_extension(raw_key)
    if extension in {".html", ".htm"}:
        output_bytes = clean_html(raw_bytes)
        output_extension = ".html"
        document_type = "html"
    else:
        output_bytes = raw_bytes # for PDF, DOC, and DOCX, the script keeps the bytes unchanged
        output_extension = extension
        document_type = extension.lstrip(".")

    identifier = record["identifier"]
    filename = safe_filename(identifier, output_extension)
    body = record.get("body", "unknown_body")
    partition_date = record.get("partition_date", "unknown_partition")
    curated_key = f"{body}/{partition_date}/{filename}"
    curated_hash = hashlib.sha256(output_bytes).hexdigest() # calculates the hash of the curated output

    s3.put_object(
        Bucket=curated_bucket,
        Key=curated_key,
        Body=BytesIO(output_bytes),
        ContentLength=len(output_bytes),
        ContentType=(
            "text/html"
            if document_type == "html"
            else raw_object.get("ContentType", "application/octet-stream")
        ),
    )

    return {
        "curated_key": curated_key,
        "curated_hash": curated_hash,
        "document_type": document_type,
        "file_size_bytes": len(output_bytes),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transform WRC Landing Zone files into Curated Zone files."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True) # requires the user to specify a transformation range
    return parser


def main() -> None:
    args = build_parser().parse_args()
    start = parse_date(args.start_date)
    end = parse_date(args.end_date)

    if start > end:
        raise SystemExit("start date must not be after end date")

    mongo_uri = os.environ["MONGO_URI"]
    mongo_database = os.environ["MONGO_DATABASE"]
    mongo_collection = os.getenv("MONGO_COLLECTION", "landing_metadata")

    minio_endpoint = os.environ["MINIO_ENDPOINT"]
    minio_access_key = os.environ["MINIO_ACCESS_KEY"]
    minio_secret_key = os.environ["MINIO_SECRET_KEY"]
    raw_bucket = os.getenv("MINIO_BUCKET_RAW", "wrc-raw")
    curated_bucket = os.getenv("MINIO_BUCKET_CURATED", "wrc-curated")

    mongo_client = MongoClient(mongo_uri)
    database = mongo_client[mongo_database]
    landing_collection = database[mongo_collection]
    curated_collection = database["curated_metadata"]

    s3 = boto3.client(
        "s3",
        endpoint_url=minio_endpoint,
        aws_access_key_id=minio_access_key,
        aws_secret_access_key=minio_secret_key,
    )

    transformed = 0
    failed = 0

    try:
        for record in iter_matching_records(landing_collection, start, end):
            try:
                result = transform_record(
                    record,
                    s3=s3,
                    raw_bucket=raw_bucket,
                    curated_bucket=curated_bucket,
                )

                curated_metadata = {
                    **record,
                    "file_path": result["curated_key"],
                    "file_hash": result["curated_hash"],
                    "document_type": result["document_type"],
                    "file_size_bytes": result["file_size_bytes"],
                    "transformed_at": datetime.now(timezone.utc).isoformat(),
                }
                curated_metadata.pop("_id", None)

                curated_collection.update_one(
                    {
                        "body": record["body"],
                        "identifier": record["identifier"],
                    },
                    {"$set": curated_metadata},
                    upsert=True,
                )
                transformed += 1
                logger.info("Record transformed", extra={"extra_data": {
                    "identifier": record["identifier"],
                    "body": record["body"],
                    "curated_key": result["curated_key"],
                    "document_type": result["document_type"],
                }})
                
            except Exception as exc:
                failed += 1
                logger.warning("Record transform failed", extra={"extra_data": {
                    "identifier": record.get("identifier"),
                    "file_path": record.get("file_path"),
                    "error": str(exc),
                }})
    finally:
        mongo_client.close()

    logger.info("Transform run completed", extra={"extra_data": {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "transformed": transformed,
        "failed": failed,
    }})


if __name__ == "__main__":
    main()

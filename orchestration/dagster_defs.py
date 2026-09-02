"""Dagster orchestration for partitioned WRC ingestion and transformation."""

from __future__ import annotations

import calendar
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from dagster import Definitions, StaticPartitionsDefinition, asset
from dotenv import load_dotenv



# load scraper settings from environment variables
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")
BODY_NAMES = tuple(
    body.strip()
    for body in os.environ["WRC_BODIES"].split(",")
    if body.strip()
)


def parse_date(value: str) -> date:
    """Convert a configured date string into a Python date."""
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date {value!r}; use DD/MM/YYYY, DD-MM-YYYY, or YYYY-MM-DD"
    )


def format_wrc_date(value: date) -> str:
    """Format a date in the format accepted by the WRC search form."""
    return f"{value.day}/{value.month}/{value.year}"



def next_month(value: date) -> date:
    """Return the first day of the month after value."""
    if value.month == 12: # decembber
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def partition_dates(partition_key: str) -> tuple[date, date]:
    """Return the exact dates to process for one monthly partition.

    The first and last calendar months are clipped to the configured overall
    range. This allows a partition such as 2025-01 to represent either the
    full month or only part of the month for a partial-range request.
    """
    overall_start = parse_date(os.environ["WRC_START_DATE"])
    overall_end = parse_date(os.environ["WRC_END_DATE"])
    partition_start = datetime.strptime(partition_key, "%Y-%m").date()
    partition_end = date(
        partition_start.year,
        partition_start.month,
        calendar.monthrange(partition_start.year, partition_start.month)[1],
    )
    return max(overall_start, partition_start), min(overall_end, partition_end) #clips the calendar month to the user’s requested range


def create_monthly_partition_keys(start: date, end: date) -> list[str]:
    """Create one partition key for each calendar month in the range."""
    keys: list[str] = []
    current = date(start.year, start.month, 1)
    last_month = date(end.year, end.month, 1)

    while current <= last_month:
        keys.append(current.strftime("%Y-%m"))
        current = next_month(current)

    return keys


configured_start = parse_date(os.environ["WRC_START_DATE"])
configured_end = parse_date(os.environ["WRC_END_DATE"])
if configured_start > configured_end:
    raise ValueError("WRC_START_DATE must not be after WRC_END_DATE")

partition_size = os.environ["PARTITION_SIZE"].strip().lower()
if partition_size != "month":
    raise ValueError(
        f"Unsupported PARTITION_SIZE={partition_size!r}; this definition uses 'month'"
    )

if not BODY_NAMES:
    raise ValueError("WRC_BODIES must contain at least one body")

monthly_partitions = StaticPartitionsDefinition(
    partition_keys=create_monthly_partition_keys(configured_start, configured_end)
)


def run_command(command: list[str], operation: str, context) -> None:
    """Run a child process and raise a useful error if it fails."""
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.stdout:
        context.log.info(result.stdout.rstrip())
    if result.returncode != 0:
        context.log.error(
            json.dumps(
                {
                    "event": f"{operation}_failed",
                    "return_code": result.returncode,
                    "stderr": result.stderr.strip(),
                }
            )
        )
        raise RuntimeError(f"{operation} failed with return code {result.returncode}")


@asset(partitions_def=monthly_partitions)
def scrape_partition(context) -> dict:
    """Scrape every configured body for the current monthly partition."""
    partition_key = context.partition_key
    start, end = partition_dates(partition_key)

    context.log.info(
        json.dumps(
            {
                "event": "scrape_started",
                "partition_date": partition_key,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "bodies": BODY_NAMES,
            }
        )
    )

    for body in BODY_NAMES:
        command = [
            sys.executable,
            "-m",
            "scrapy",
            "crawl",
            "wrc_decisions",
            "-a",
            f"start_date={format_wrc_date(start)}",
            "-a",
            f"end_date={format_wrc_date(end)}",
            "-a",
            f"body={body}",
            "-a",
            f"partition_date={partition_key}",
        ]
        run_command(command, f"scrape_{body}", context)

    context.log.info(
        json.dumps({"event": "scrape_completed", "partition_date": partition_key})
    )
    return {"partition_date": partition_key, "bodies": BODY_NAMES}


@asset(partitions_def=monthly_partitions)
def transform_partition(
    context, scrape_partition: dict
) -> dict:
    """Transform the curated files for the same monthly partition."""
    partition_key = context.partition_key
    start, end = partition_dates(partition_key)

    context.log.info(
        json.dumps(
            {
                "event": "transform_started",
                "partition_date": partition_key,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        )
    )

    command = [
        sys.executable,
        "-m",
        "transform.transform",
        "--start-date",
        format_wrc_date(start),
        "--end-date",
        format_wrc_date(end),
    ]
    run_command(command, "transform", context)

    context.log.info(
        json.dumps({"event": "transform_completed", "partition_date": partition_key})
    )
    return {"partition_date": partition_key, "status": "completed"}


defs = Definitions(assets=[scrape_partition, transform_partition])


# Architecture

## Overview

```
WRC website
    |
    | Dagster monthly partition -> date range + body
    v
Scrapy spider  ---- document Request/Response (own crawl) ---->  MinIO / wrc-raw
    |                                                                  |
    | metadata (incl. file_path, file_hash)                           |
    v                                                                  |
MongoDB / landing_metadata                                             |
    |                                                                  |
    | transform.py, per partition                                     |
    v                                                                  v
MongoDB / curated_metadata  <---------------------------  MinIO / wrc-curated
```

## Partitioning

Monthly partitions, keyed as `YYYY-MM` via a Dagster `StaticPartitionsDefinition`. A month is small
enough to retry or backfill cheaply if one body fails, and large enough that the number of partitions
stays manageable for a source of this volume — daily partitions would multiply orchestration overhead
for no real parallelism gain at 500–1,000 documents/year. Each record stores `partition_date` (the
ingestion partition) separately from `date` (the actual decision date), so the two can diverge for a
document decided near a month boundary without losing either meaning. The full `start_date`/`end_date`
still goes to the WRC search form; `partition_date` is a labeling/dedup concern, not a search parameter.

## Downloads, retries, and rate limiting

Document downloads are issued as real `scrapy.Request` objects from the spider (`callback=parse_document`,
`errback=handle_download_error`), not synchronous HTTP calls from a pipeline. That means `AUTOTHROTTLE_*`,
`DOWNLOAD_DELAY`, `CONCURRENT_REQUESTS_PER_DOMAIN`, `RETRY_TIMES`/`RETRY_HTTP_CODES` (500/502/503/504/429/408), and
`ROBOTSTXT_OBEY` govern search, pagination, *and* document traffic identically — there's one throttling
policy for everything this spider does, not two. A failed download is caught in `handle_download_error`,
logged with the URL and HTTP status, and the record's metadata is still yielded — one bad document
degrades that one record, not the partition.

## Deduplication and idempotency

MongoDB upserts on `(body, identifier)` via a unique index, so re-running a partition can't create a
duplicate metadata record — that's a structural guarantee, not just a behavioral one. For files: every
run computes the SHA-256 of the freshly fetched bytes and compares it to the previously stored hash
before deciding to re-upload. Unchanged files are re-fetched because the source provides no cheaper
freshness check, but they are not uploaded to MinIO again. The metadata is still upserted on every run
using the existing `(body, identifier)` identity, so the write is a no-op in value (same `file_path`/
`file_hash` written back) rather than a new document — the rerun does not create a duplicate record or
churn storage, even though a Mongo write does occur. `landing_metadata` writes filter out unset fields
before `$set`, so a partial failure on a re-run can't clobber a previously-good `file_path`/`file_hash`
with `null`.

## Landing Zone immutability

`transform.py` only ever reads from `wrc-raw`/`landing_metadata` and writes to `wrc-curated`/
`curated_metadata`. It creates the curated bucket on first use if missing, so a clean `docker compose up`
works end to end without manual setup.

## Observability

The spider and the transform script use the shared structured JSON logger (`log_utils.JsonFormatter`)
for their main events and summaries — spider start, extraction/download failures, and a `run_summary`
event (`records_found`, `records_scraped`, `records_failed`) at close, so "did this partition actually
work" is a log query, not a guess. Some pipeline-level messages (e.g. "no file downloaded", "unchanged,
skipping upload") still go through Scrapy's own text logger rather than the JSON one and should be
migrated for fully uniform structured logging. `tests/` covers the parts most likely to break silently:
partition-boundary math (including a leap-year case), the hash-compare upload/skip decision, PDF
passthrough vs. HTML cleaning, and spider argument validation.

## Scaling to 50+ sources

Three things would need to change, concretely: (1) `BODY_VALUES`-style per-source constants move out of
the spider into a small `sources/<name>.py` module per source, each exposing the same interface (form
fill, result parsing, pagination) so the spider becomes a thin driver over pluggable source adapters;
(2) Dagster partitions become `(source, month)` instead of just `month`, so one slow or broken source's
retries don't block materializing the others; (3) `transform.py`'s per-partition Mongo query moves from
a full collection scan to an indexed filter on `partition_date` — cheap at 1,000 documents, real cost at
50 sources × years of history. None of this requires a new datastore or orchestrator — Mongo, MinIO, and
Dagster all scale along the dimension that matters here, which is source count and partition count, not
raw document volume.

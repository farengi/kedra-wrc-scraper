# Kedra WRC Scraping Pipeline

A Scrapy-based pipeline that scrapes legal decisions from the Irish
[Workplace Relations](https://www.workplacerelations.ie) website, partitions
the crawl by month and by adjudicating body, stores metadata in MongoDB and
raw documents in MinIO (Landing Zone), and transforms the HTML documents into
a cleaned Curated Zone. Orchestration is handled by Dagster.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- pip

## 1. Clone and install dependencies

```bash
git clone <this-repo-url>
cd <repo-folder>
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure environment variables

Copy the example file and fill in real values:

```bash
cp .env.example .env
```

`.env` must define (see `.env.example` for the storage/scraper settings):

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `MONGO_DATABASE`, `MONGO_COLLECTION` | Landing metadata store |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Object storage credentials |
| `MINIO_BUCKET_RAW`, `MINIO_BUCKET_CURATED` | Landing / Curated buckets |
| `REQUEST_TIMEOUT_SECONDS`, `CONCURRENT_REQUESTS_PER_DOMAIN`, `DOWNLOAD_DELAY` | Scrapy throttling |
| `AUTOTHROTTLE_START_DELAY`, `AUTOTHROTTLE_MAX_DELAY`, `AUTOTHROTTLE_TARGET_CONCURRENCY` | AutoThrottle tuning |
| `RETRY_TIMES` | Retry attempts on transient HTTP errors |
| `WRC_START_DATE`, `WRC_END_DATE` | Overall date range to ingest (e.g. `01/01/2024`, `01/01/2025`) |
| `WRC_BODIES` | Comma-separated list of bodies to scrape, e.g. `workplace_relations_commission,labour_court` |
| `PARTITION_SIZE` | Currently only `month` is supported |

## 3. Start the infrastructure (MongoDB + MinIO)

```bash
docker compose up -d
```

- MongoDB: `localhost:27017`
- MinIO API: `localhost:9000`
- MinIO Console: `localhost:9001` (login with `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`)

## 4. Run the pipeline

### Option A — via Dagster (recommended, handles partition + dependency ordering)

```bash
dagster dev -f orchestration/dagster_defs.py
```

Open the Dagster UI (default `http://localhost:3000`), select the
`scrape_partition` / `transform_partition` assets, and materialize the
monthly partitions you need (or materialize all partitions in the
configured `WRC_START_DATE`–`WRC_END_DATE` range). `transform_partition`
depends on `scrape_partition` for the same month, so Dagster enforces the
correct order automatically.

### Option B — run the spider directly for a single window

```bash
python -m scrapy crawl wrc_decisions \
  -a start_date=01/01/2024 \
  -a end_date=31/01/2024 \
  -a body=workplace_relations_commission \
  -a partition_date=2024-01
```

Valid values for `body`: `employment_appeals_tribunal`, `equality_tribunal`,
`labour_court`, `workplace_relations_commission`.

### Option C — run the transform script directly

```bash
python -m transform.transform --start-date 01/01/2024 --end-date 31/01/2024
```

Dates accept `D/M/YYYY` or `YYYY-MM-DD`.

## 5. Verify the results

- **Mongo**: `landing_metadata` collection holds raw metadata; after
  transform, `curated_metadata` holds the cleaned records.
- **MinIO console**: `wrc-raw` bucket has the original PDFs/HTML; `wrc-curated`
  has the cleaned/renamed files.
- **Logs**: emitted as JSON to stdout (via `log_utils.get_logger`) for the
  transform step.

## Project structure

```
scraper/
  spiders/wrc_decisions.py   # Scrapy spider: search form + pagination
  items.py                   # DecisionItem dataclass
  pipelines.py                # MongoPipeline (metadata), MinioPipeline (raw file download)
  settings.py                 # All Scrapy settings, sourced from env vars
transform/
  transform.py                 # Landing Zone -> Curated Zone transformation
orchestration/
  dagster_defs.py               # Monthly-partitioned Dagster assets
log_utils.py                    # JSON log formatter
docker-compose.yml               # MongoDB + MinIO
.env.example                     # Required environment variables
```
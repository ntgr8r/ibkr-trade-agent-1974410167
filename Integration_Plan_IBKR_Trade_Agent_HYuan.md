# Integration Plan — IBKR Trade Agent × Bursatilito History_Book

**Status:** Proposed delivery plan  
**Date:** 2026-10-11  
**Repositories:**

- Consumer: `/home/dmabee/DEV_PROJECTS/ibkr-trade-agent-1974410167`
- Source: `/home/dmabee/DEV_PROJECTS/NTGR8R_Project_Orchestrator/apps/history_book`

## 1. Outcome

Integrate Bursatilito History_Book as the authoritative source of **historical market data and reference identity** for the IBKR Trade Agent, while retaining IBKR as the source for account facts and current market state. Replace Longbridge completely after validated cutover; do not use it as a runtime fallback.

This plan implements the decisions in `Master_Data_Management.md`:

| Data domain | Authority | Trade Agent use |
|---|---|---|
| Account, positions, trades, and cash flows | IBKR Flex | Portfolio/account truth |
| Current quotes and market state | IBKR market-data entitlement | Time-sensitive current-state views |
| Historical OHLCV, benchmark/FX history, corporate actions, and instrument/listing identity | Bursatilito History_Book | Performance, research, backtests, evidence |
| Policies, agent runs, overrides, and audit records | IBKR Trade Agent | Application governance |

## 2. Compatibility baseline

History_Book already provides the necessary historical-data primitives:

- Canonical `company → instrument → listing` identity, with UUID `listing_id`, IBKR `conId`, ISIN, FIGI, exchange, symbol, currency, and effective dates.
- Daily bars keyed by `(listing_id, trade_date)` with raw OHLCV, separate `adjusted_close`, currency, source, quality flags, and ingest time.
- Exchange sessions, corporate actions, ingestion-run lineage, and immutable SHA-256-versioned historical datasets.
- An authenticated immutable daily-projection API (`history-book-daily-projection/v1`).

History_Book's per-listing daily projection is bounded to 2–101 rows and is suitable for evidence/research reads. Its existing authenticated immutable artifact API can supply bulk data when the selected export is within its 16 MiB bound. The Trade Agent must consume this API rather than read History_Book PostgreSQL tables directly; a range/chunk contract is required only when the production dataset exceeds that bound.

History_Book does not provide Longbridge-equivalent news, macro news, analyst forecasts, valuation, or financial statements. Before Longbridge removal, each dependent feature must be either removed, re-scoped, or assigned an approved replacement source.

## 3. Integration architecture

```text
History_Book PostgreSQL
        │
        ├── immutable dataset artifact / batch-range API (authenticated)
        │
        ▼
Trade Agent HistoryBookClient
        │  validates contract, digest, lifecycle, identity, and freshness
        ▼
HistoricalMarketDataRepository ──► Elasticsearch historical read models
        │                                      │
        ├── performance / benchmark services   ├── research and agent evidence
        └── provider-neutral market APIs       └── frontend provenance display

IBKR Flex ──► existing account/position/trade indices
IBKR market data ──► current quote read model (separate from history)
```

No consumer above `HistoryBookClient` may depend on History_Book table names, direct database credentials, or a source-specific symbol convention.

## 4. Source contract to establish

### 4.1 New History_Book contract

Use History_Book's authenticated immutable export contract for the initial integration. If a production export exceeds 16 MiB, History_Book should additionally publish an authenticated, read-only bulk/range or chunked-export contract. That future request must accept:

```json
{
  "listing_ids": ["uuid"],
  "conids": [123456],
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "fields": ["identity", "daily_bars", "sessions", "corporate_actions", "benchmarks", "fx"],
  "adjustment_basis": "raw|provider_adjusted",
  "dataset_id": "optional pinned dataset",
  "dataset_version": "optional pinned version"
}
```

The response/export must be versioned and contain:

- `contract_version`, `dataset_id`, `dataset_version`, lifecycle state, `cutoff_at`, and SHA-256 content digest;
- identity: `listing_id`, `instrument_id`, `conId`, local symbol, canonical exchange, currency, and identity status;
- bar: `trade_date`, decimal-string OHLC, `adjusted_close`, volume, currency, source, quality flags, `knowledge_at`/ingested timestamp;
- session and corporate-action facts needed to interpret date and adjusted values;
- benchmark and FX rows when requested;
- coverage, missing-date, partial, and error information—not silently omitted records.

The endpoint must be bounded (maximum listings/days/bytes), authenticated with a service credential, rate-limited, auditable, and idempotent for the same pinned dataset version.

### 4.2 Required source-policy decision

History_Book must document whether `adjusted_close` means split-adjusted, total-return adjusted, or provider-specific adjusted. Until confirmed, the Trade Agent stores it as `provider_adjusted`, never labels it `total_return_adjusted`, and prohibits mixed-basis calculations.

## 5. Trade Agent implementation work

### Workstream A — configuration and source-neutral contracts

**Target:** `ibkr_show_common` and `ibkr_show_backend/app/core/config.py`

1. Add versioned canonical contracts: `InstrumentIdentity`, `DailyBar`, `CorporateAction`, `MarketSession`, `DataProvenance`, and `HistoricalDatasetReceipt`.
2. Add environment-only settings:

   - `HISTORY_BOOK_BASE_URL`
   - `HISTORY_BOOK_SERVICE_TOKEN_FILE`
   - `HISTORY_BOOK_CONNECT_TIMEOUT_SECONDS`
   - `HISTORY_BOOK_READ_TIMEOUT_SECONDS`
   - `HISTORY_BOOK_REQUIRED_CONTRACT_VERSION`
   - `HISTORY_BOOK_MAX_STALENESS_SECONDS`

3. Expose configuration health without returning URLs containing secrets, tokens, account identifiers, or source payloads.
4. Remove all use of `normalize_longbridge_symbol`; introduce `InstrumentResolver` with conId-first matching and explicit `NOT_FOUND`/`AMBIGUOUS` outcomes.

**Acceptance:** contracts parse decimal strings without precision loss; settings are tested; no generic code imports a Longbridge type for market history.

### Workstream B — History_Book adapter

**Target:** add `ibkr_show_backend/app/clients/history_book_client.py` and `app/services/history_book_*`.

1. Authenticate against the source service and request only the required range/fields.
2. Validate HTTP status, content type, contract version, schema, lifecycle state, SHA-256 digest, cutoff timestamp, and response bounds before parsing rows.
3. Convert decimal strings to `Decimal`; convert to float only at the existing Elasticsearch projection boundary where required.
4. Reject unknown lifecycle states, revoked/superseded datasets unless explicitly allowed, duplicate `(listing_id, trade_date)` records, invalid OHLC relationships, invalid currencies, and identity conflicts.
5. Return typed errors that preserve safe diagnostic codes but never leak credentials or raw account facts.

**Acceptance:** fixture-based contract tests cover good data, a revoked version, digest mismatch, stale result, duplicate date, invalid OHLC, missing currency, and ambiguous identity.

### Workstream C — mappings and read models

**Target:** `ibkr_show_worker/worker/es/index_definitions.py`, worker ingestion jobs, and repositories.

1. Add `ibkr_instrument_master_v1` sourced from History_Book identity records.
2. Add `ibkr_market_price_daily_v2`, keyed by `instrument_id + trading_date + adjustment_basis + dataset_version`.
3. Add `ibkr_corporate_action_v1` and `ibkr_data_ingestion_run_v1` for source lineage and publishing decisions.
4. Keep `ibkr_symbol_price_history_v1` read-only during migration. Build a compatibility projection for current performance consumers; do not redefine the existing index in place.
5. Include `history_book_listing_id`, `conid`, canonical exchange, source, dataset ID/version/digest, `as_of_at`, `ingested_at`, quality status, and limitations in the new documents.
6. Quarantine unresolved/ambiguous mappings in `ibkr_data_quality_exception_v1`; no ticker-only upsert.

**Acceptance:** replaying the same immutable dataset version is idempotent; a corrected source version creates an auditable new projection without destroying prior lineage.

### Workstream D — replace historical consumers

**Target:** `ibkr_show_backend/app/domains/performance/price_auto_backfill.py`, `benchmark_price_backfill.py`, `benchmark_price_provider.py`, and research/evidence services.

1. Replace `LongbridgeExternalDataClient` with a `HistoricalMarketDataRepository` backed by History_Book read models.
2. Update performance and benchmark backfill to request history from History_Book through the adapter, then publish validated projections.
3. Make every price request specify `adjustment_basis` and return coverage/quality limitations.
4. Replace Longbridge symbol normalizations in outcome replay and execution alignment with canonical instrument resolution.
5. Rebuild evidence cards to include source, dataset version, digest, cutoff/as-of time, coverage, and limitations.

**Acceptance:** performance calculations, benchmark curves, replay, trade review, and decision evidence run without invoking Longbridge.

### Workstream E — current data and feature-scope replacement

1. Implement the separate IBKR current-quote adapter/read model; it must not overwrite historical bars.
2. Inventory all Longbridge functions used by `symbol_analysis_service.py`, public-market evidence, macro evidence, and the frontend.
3. For each function, make one explicit decision: **remove**, **replace with approved source**, or **retain only if History_Book/IBKR supplies a documented equivalent**.
4. Do not label an unavailable fundamental/news capability as an empty but successful result; return an explicit capability limitation.

**Acceptance:** product owner signs off on every Longbridge capability disposition before final removal.

### Workstream F — API, UI, and retirement

1. Introduce provider-neutral endpoints such as `/market-history`, `/market-data/coverage`, and `/market-data/health`.
2. Replace `/longbridge/*` frontend and backend calls and show provenance/freshness/coverage in user-facing research and performance views.
3. Replace/remove Longbridge admin pages with a History_Book/IBKR data-source health view.
4. After all gates pass, delete Longbridge OAuth/MCP tooling, SDK dependency, settings, routes, UI, fixtures, tests, prompts, and documentation.

**Acceptance:** a case-insensitive repository search for `longbridge` finds only an approved archived migration record.

## 6. Delivery sequence and decision gates

| Phase | Deliverable | Exit gate |
|---|---|---|
| 0. Contract | History_Book immutable artifact contract, auth model, adjustment policy, sample pinned dataset; range/chunk design only if needed | Consumer and source owners approve contract version and 16 MiB/range limits |
| 1. Adapter | Typed authenticated client and fixtures | Contract/security/error tests pass |
| 2. Master/read models | Instrument mapping, ingestion, audit, new ES indices | Idempotency and conId-first reconciliation pass |
| 3. Parallel validation | History_Book projections versus existing Longbridge historical output | Agreed coverage/return/benchmark thresholds pass; gaps are accepted or remediated |
| 4. Consumer migration | Performance, evidence, APIs, UI use source-neutral services | Critical flows operate with Longbridge disabled in staging |
| 5. Cutover | Production History_Book history + IBKR current data | Product, data, security, and release owners approve gates |
| 6. Retirement | Longbridge removal PR/release | Dependency inventory is zero and rollback read model is tested |

Longbridge may be used only as a time-bounded comparison source in Phase 3. It is not a fallback after cutover.

## 7. Reconciliation and quality plan

For every in-scope position and benchmark:

1. Resolve History_Book `listing_id` by IBKR conId. If unavailable, use ISIN or FIGI with exchange; otherwise quarantine.
2. Compare session dates against History_Book exchange calendars—not calendar weekdays alone.
3. Compare raw-close series separately from adjusted-close series.
4. Compare return calculations using the agreed basis and currency/FX methodology.
5. Reconcile corporate-action dates and factors; investigate material price discontinuities.
6. Confirm source dataset lifecycle is `READY`, digest matches, and cutoff is fit for the requested decision time.
7. Publish coverage, mismatch, and quarantine metrics; no automatic production acceptance of partial data.

Suggested release thresholds must be set by the product/data owner before Phase 3. At minimum, they should cover identity-resolution rate, expected-session coverage, unexplained price/return variance, benchmark coverage, dataset freshness, and zero unreviewed critical exceptions.

## 8. Security and operational controls

- Use least-privilege, read-only service credentials stored outside version control.
- Enforce TLS and authenticate every History_Book service call; the existing source endpoints use a service token pattern.
- Log request scope, contract version, dataset version/digest, counts, status, and safe error code only.
- Never log credentials, raw token values, source artifacts containing restricted content, or IBKR account data.
- Apply timeouts, bounded retries, circuit-breaking, and rate limits. A source outage returns an explicit unavailable/stale state.
- Monitor ingestion lag, source lifecycle state, coverage, mapping exceptions, endpoint error rate, and contract-version drift.
- Preserve prior immutable source versions and Trade Agent ingestion receipts for audit/replay.

## 9. Ownership

| Owner | Responsibility |
|---|---|
| History_Book owner | Support the authenticated immutable artifact contract; document adjustment semantics/lifecycle policy and add range/chunk export only if required by volume |
| Trade Agent backend owner | Build adapter, resolver, repositories, APIs, and Longbridge removal |
| Trade Agent worker/data owner | Operate mappings, ingestion/read models, reconciliation, and quality exceptions |
| IBKR owner | Confirm current-market-data entitlement and operational limits |
| Product/data owner | Approve adjustment policy, thresholds, capability reductions, and cutover |
| Security/release owner | Approve credential controls, audit evidence, and final retirement gate |

## 10. First five executable tasks

1. Source owner publishes a sample `READY` immutable dataset/export for held symbols and benchmarks, plus a range/chunk contract only if the expected production export exceeds 16 MiB.
2. Product/data owner selects the adjustment basis for performance and benchmark reporting.
3. Backend owner adds canonical History_Book contracts and configuration, then implements the authenticated client with contract fixtures.
4. Data owner creates the master/price/ingestion indices and runs conId-first mapping on the current IBKR position and benchmark universe.
5. Team runs a pinned-version reconciliation before replacing `PerformancePriceAutoBackfillService` and `BenchmarkPriceBackfillService`.

## 11. Definition of done

The integration is complete only when historical-data consumers rely on validated History_Book data, current market-state consumers rely on IBKR, every response/evidence item exposes provenance and limitations, data quality gates pass, Longbridge-only feature choices are accepted, and all Longbridge runtime and repository dependencies have been removed.

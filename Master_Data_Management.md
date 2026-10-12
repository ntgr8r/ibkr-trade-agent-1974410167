# Master Data Management: IBKR and Bursatilito History_Book

**Status:** Proposed implementation blueprint  
**Decision date:** 2026-10-11  
**Scope:** Replace Longbridge completely. This is a data-architecture and implementation plan, not an authorization to trade.

## 1. Decisions and objective

The application will retire Longbridge as a dependency. Its replacement is deliberately split by data authority:

| Domain | System of record | Permitted use |
|---|---|---|
| Account, positions, trades, cash flows, corporate-account facts | IBKR Flex | Broker-record reconciliation and portfolio workflows |
| Current quotes and intraday/current market state | IBKR market-data capability | Current-state views and time-sensitive decisions, subject to market-data entitlements |
| Historical prices, corporate actions, fundamentals, and reference history | Bursatilito History_Book | Research, backtests, performance history, and reproducible evidence |
| App-created policies, reviews, agent runs, overrides, and audit trails | Application persistence | Application governance and replay |

History_Book is authoritative for history; IBKR is authoritative for the current/account state. A record must never silently switch authority because one source is unavailable. The UI and all agent evidence must disclose source, as-of time, coverage, and data quality.

The target outcome is a complete Longbridge exit: production paths, configuration, credentials, admin UI, routes, code, tests, fixtures, documentation, and package dependencies are removed only after replacement acceptance criteria pass.

## 1.1 History_Book format compatibility assessment

**Verdict: compatible for the historical-price and instrument-master replacement, with an adapter; not compatible by itself with the full Longbridge feature set.** This assessment now includes the source project at `/home/dmabee/DEV_PROJECTS/NTGR8R_Project_Orchestrator/apps/history_book`.

History_Book is a PostgreSQL market-truth service with canonical `company → instrument → listing` identity. Its `listing` records carry a UUID `listing_id`, local symbol, exchange/MIC context, IBKR `conid` and primary exchange; its `instrument` records support ISIN, FIGI, SEDOL, CUSIP, issue currency, and effective dates. It stores daily bars keyed by `(listing_id, trade_date)`, plus exchange sessions, corporate actions, ingestion runs/items, and immutable, digest-verified workflow datasets.

| IBKR Trade Agent requirement | History_Book evidence | Assessment and adapter rule |
|---|---|---|
| Daily close for performance/benchmark calculations | `daily_bar.trade_date`, positive `close`, and separate `adjusted_close` | **Compatible.** Map `trade_date → report_date` during the transition and select `close` or `adjusted_close` explicitly by the requested performance methodology. |
| OHLCV history | `daily_bar` supplies `open`, `high`, `low`, `close`, `adjusted_close`, `volume`, `currency`, source, quality flags, and ingest time | **Compatible.** Preserve decimal precision at the boundary; do not manufacture missing open or volume. |
| Stable instrument identity | UUID listing/instrument IDs, IBKR conId, ISIN, FIGI, exchange, local symbol, validity windows, and fail-closed identity status | **Stronger than the current symbol-based Longbridge normalization.** Use `listing_id` as the History_Book foreign key and resolve through conId/ISIN/FIGI/exchange, never ticker alone. |
| Exchange/date semantics | `exchange`, `market_session`, time zone, session times/status, and canonical exchange mapping | **Compatible.** The adapter must retain the listing exchange, session time zone, and source session definition with every response. |
| Corporate-action-aware history | `corporate_action` and raw `close` separate from `adjusted_close` | **Compatible with a policy decision.** The agent must add an explicit `adjustment_basis` field; History_Book’s column names alone do not establish whether adjusted close is split-only or total-return adjusted. |
| Provenance/reproducibility | `ingestion_run`/`ingestion_item`, row ingestion IDs, and append-only workflow dataset materializations with SHA-256 content digests and lifecycle state | **Compatible and stronger than the existing price read model.** Use a `dataset_id`, `dataset_version`, digest, source, and knowledge/as-of timestamp in agent evidence. |
| Versioned API/export | Authenticated immutable artifact and bounded daily-projection endpoints (`history-book-daily-projection/v1`) | **Compatible for controlled reads and bounded bulk ingestion.** Use the digest-bound immutable artifact export for bulk data within its 16 MiB limit; the 2–101-row daily projection is evidence-only. Add range/chunk delivery only when a required export exceeds the artifact bound. |
| Current quotes/intraday state | Five-minute bars and quote-profile infrastructure exist, but the target architecture assigns current market state to IBKR | **Not used as the current quote authority.** Continue to use IBKR for current state; History_Book remains historical. |
| News, macro news, analyst forecasts, valuation, and financial statements | These datasets are not in the History_Book schema or service contract reviewed | **Not compatible.** These Longbridge capabilities need retirement, a separately approved data source, or a deliberately reduced product scope. |

### Format actually exposed by History_Book

The immutable daily projection provides a versioned, authenticated JSON contract. Its listing identity includes `listing_id`, `conId`, symbol, and currency; each row includes `trade_date`, string-encoded decimal OHLC values, `adjusted_close`, source, quality flags, knowledge timestamp, plus dataset/version and SHA-256 projection provenance. This is a safe integration boundary for agent/research reads.

The full immutable artifact additionally contains `volume`, session metadata, benchmark daily adjusted closes, and FX daily rates. A production adapter should consume the published contract—not query History_Book tables directly—and use the artifact endpoint for performance backfill and benchmark loading while the required artifact remains within the source's 16 MiB limit.

### Required compatibility controls before cutover

1. Define and test the precise mapping from History_Book decimal strings to the Trade Agent canonical price contract; no float conversion until the Elasticsearch read-model boundary.
2. Agree the adjustment policy (`close` versus `adjusted_close`) per performance calculation, benchmark, chart, and backtest; reject mixed bases.
3. Consume the authenticated immutable artifact export for bulk migration and enforce its 16 MiB bound. Add a batch/range or chunked-export endpoint only if the approved production dataset cannot fit that bound.
4. Reconcile every in-scope IBKR position and benchmark through conId first, then ISIN/FIGI plus exchange; send unresolved or ambiguous mappings to quarantine.
5. Reconcile a representative date range for coverage, currency, corporate actions, and returns; validate every dataset version/digest and lifecycle state before publishing it to agents.
6. Decide the replacement or removal of Longbridge-only research features (news, macro, forecasts, valuation, financials) before their routes and UI are retired.

## 2. Target architecture

```text
IBKR Flex --------------------> IBKR ingestion worker -----------+
IBKR current market data -----> IBKR current-data adapter -------+--> Canonical data services --> APIs / agents / UI
History_Book -----------------> History_Book ingestion adapter ---+           |
                                                                     Elasticsearch read models
                                                                             + immutable ingestion/audit records
```

Adapters are source-specific. The rest of the application consumes source-neutral contracts. No UI component, agent prompt, or business service may import an IBKR or History_Book SDK directly.

### Logical layers

1. **Source adapters** authenticate, fetch, rate-limit, validate transport responses, and capture immutable source metadata.
2. **Landing and normalization** map source fields to canonical contracts; retain the source payload fingerprint and lineage, not credentials or unnecessary personal data.
3. **Master-data services** resolve instruments, calendars, currency, corporate actions, and data-authority rules.
4. **Curated read models** serve account, prices, performance, research, and evidence queries from Elasticsearch.
5. **Consumers** (API routes, agents, UI) request canonical data and receive freshness, provenance, and limitations with it.

## 3. Master-data domains and minimum canonical keys

### 3.1 Instrument master

Create an `instrument_master_v1` read model. Its durable primary key is `instrument_id`, not a vendor-formatted symbol.

Required attributes:

| Attribute | Rule |
|---|---|
| `instrument_id` | Stable internal ID; never derived solely from ticker |
| `conid` | IBKR contract identifier where available; unique only with contract context |
| `ticker`, `listing_exchange`, `currency`, `asset_class` | Canonical listing identity |
| `isin`, `figi` | External identifiers when supplied and licensed for use |
| `history_book_instrument_id` | History_Book mapping key |
| `source_symbol` | Source-native symbol, kept per source rather than overloaded into `symbol` |
| `valid_from`, `valid_to`, `status` | Effective dating for ticker changes, mergers, and delistings |
| `mapping_confidence`, `mapping_method`, `review_status` | Prevent automatic joins when identity is ambiguous |

`normalize_longbridge_symbol()` must not be retained or renamed as a generic normalizer. Replace it with an `InstrumentResolver` that returns an explicit mapping or a typed ambiguity/not-found result.

### 3.2 Price and market-history master

The canonical historical-price grain is:

`instrument_id + trading_date + interval + adjustment_basis + source_dataset_version`

Store `open`, `high`, `low`, `close`, `volume`, currency, exchange/calendar, and `as_of_at`. `adjustment_basis` is mandatory (`raw`, `split_adjusted`, `total_return_adjusted`, or another controlled value); a consumer cannot compare or aggregate series with differing bases without an explicit conversion rule.

History_Book feeds historical data only. It must expose or provide a documented extract with dataset version, source coverage, effective session date, correction timestamp, and corporate-action basis. If it cannot, its ingestion adapter must add these fields at ingestion time and label any unavailable field as unknown.

### 3.3 Current market-state master

IBKR current data uses the same `instrument_id` but is modeled separately from history. Required fields are `observed_at`, `received_at`, `bid`, `ask`, `last`, `close`, `market_state`, `currency`, entitlement/status, and source latency. Current data must not overwrite a History_Book history row.

### 3.4 Account master

The existing IBKR Flex indices remain the broker-account authority. Account identifiers must be consistently pseudonymized or access-controlled. Account data may reference `instrument_id`, `conid`, and source identifiers, but does not create the instrument master.

## 4. Canonical data contracts

Introduce an internal package such as `ibkr_show_common/schemas/market_data.py` for versioned Pydantic contracts:

```python
class DataProvenance(BaseModel):
    source: Literal["IBKR_FLEX", "IBKR_MARKET_DATA", "HISTORY_BOOK", "APPLICATION"]
    source_record_id: str | None
    retrieved_at: datetime
    as_of_at: datetime | None
    dataset_version: str | None
    quality_status: Literal["VALID", "STALE", "PARTIAL", "REJECTED"]
    limitations: list[str]

class DailyBar(BaseModel):
    instrument_id: str
    trading_date: date
    adjustment_basis: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    currency: str
    provenance: DataProvenance
```

The external REST API may project these contracts, but its API route names must be provider-neutral (`/market-data`, `/market-history`, `/market-news`) rather than `/longbridge`.

## 5. Storage, lineage, and quality controls

Elasticsearch remains a query/read-model store. It should not be treated as the sole proof of source history. Every ingestion run needs an append-only audit record containing request scope (never tokens), record counts, source version, checksum/fingerprint, start/end times, validation outcome, and error category.

Create or version the following indices through `ibkr_show_worker/worker/es/index_definitions.py`:

| Index | Purpose |
|---|---|
| `ibkr_instrument_master_v1` | Canonical listing and identifier mappings |
| `ibkr_market_price_daily_v2` | History_Book daily history, keyed by canonical grain |
| `ibkr_market_quote_current_v1` | IBKR current-state snapshots with TTL/retention policy |
| `ibkr_corporate_action_v1` | Effective-dated split/dividend/symbol-change events |
| `ibkr_data_ingestion_run_v1` | Append-only operational lineage and quality results |
| `ibkr_data_quality_exception_v1` | Quarantined mappings, gaps, conflicts, and manual decisions |

The existing `ibkr_symbol_price_history_v1` should be migrated behind a compatibility repository, then retired after reconciliation. Do not mutate its semantic meaning in place.

Required validation gates before a batch is published:

- Instrument mapping is unique or explicitly quarantined.
- Dates belong to the appropriate exchange calendar; no duplicate canonical key.
- Price/volume values are valid and currency is known.
- Adjustment basis and provenance are present.
- A correction cannot replace a prior value without preserving the new dataset version and audit event.
- Coverage is measured against expected trading sessions, not calendar days.

## 6. Source precedence and conflict policy

1. For account facts, IBKR Flex wins.
2. For current prices, IBKR market data wins when entitled and fresh.
3. For historical observations through the approved cutoff, History_Book wins.
4. When a historical date is not covered by History_Book, return a coverage limitation; do not use a current IBKR quote as a substitute.
5. Conflicting instrument identifiers or corporate actions become data-quality exceptions requiring review. They are not silently resolved by ticker text.

Each response and agent evidence card must carry a compact provenance block. A decision agent must treat `STALE`, `PARTIAL`, or unresolved-instrument data as a limitation and apply the existing fail-closed behavior where appropriate.

## 7. Repo-specific implementation backlog

### Phase 0 — establish contracts and access (exit: buildable adapters with no production cutover)

- [ ] Obtain the History_Book integration contract: authentication, export/API form, instrument IDs, licensed fields, coverage, correction policy, corporate-action treatment, rate limits, and SLA.
- [ ] Confirm IBKR entitlement/API path for current market data. IBKR Flex alone is statement/report ingestion and is not assumed to provide real-time quotes.
- [ ] Add source-neutral canonical schemas and `DataProvenance` under `ibkr_show_common`.
- [ ] Implement source configuration with separate `HISTORY_BOOK_*` and `IBKR_MARKET_DATA_*` settings; secrets stay outside source control and health endpoints expose configuration state only.
- [ ] Define retention, access classification, and on-call ownership for account vs. market data.

### Phase 1 — master data and ingestion (exit: reproducible historical data available in parallel)

- [ ] Add `InstrumentResolver`, a reviewed mapping workflow, and `instrument_master_v1`; migrate uses of `normalize_longbridge_symbol` in `trade_decision_outcome_replay.py`, `trade_decision_execution_alignment.py`, `symbol_analysis_service.py`, and related services.
- [ ] Add a History_Book client and worker ingestion jobs with idempotent document IDs, checkpointing, retry policy, quarantine, and ingestion-run logging.
- [ ] Add IBKR current-data adapter and quote snapshot read model; make lack of entitlement an explicit unavailable status.
- [ ] Replace the direct Longbridge dependency in `domains/performance/price_auto_backfill.py` and `benchmark_price_backfill.py` with a `HistoricalPriceRepository` backed by History_Book data.
- [ ] Reconcile a representative historical window: record counts, missing-session rate, prices after normalizing adjustment basis, and benchmark return differences.

### Phase 2 — replace consumer paths (exit: feature parity without Longbridge)

- [ ] Replace `app/api/routes/longbridge.py` with provider-neutral market-data routes and migrate frontend callers.
- [ ] Replace `app/services/longbridge_service.py` with source-neutral history/current services; consumers must depend on interfaces, not vendor clients.
- [ ] Rebuild `symbol_analysis_service.py` against approved History_Book datasets and/or clearly scoped IBKR current data. Any unavailable fundamental, forecast, or news capability must be explicitly re-scoped—IBKR/History_Book parity must not be assumed.
- [ ] Rebuild public-market evidence services (`public_market_evidence_*`, daily-review evidence, research subagents) to produce provenance-aware History_Book/IBKR evidence.
- [ ] Replace Longbridge-only labels in schemas, agent prompts, fixtures, UI types, and status panels.
- [ ] Replace the Longbridge administration view with a data-source health/coverage view, or remove it if no comparable operational action remains.

### Phase 3 — validation, cutover, and decommission (exit: Longbridge fully removed)

- [ ] Add contract, ingestion, reconciliation, and end-to-end tests for both source adapters, source precedence, stale data, identifier ambiguity, gaps, corrections, and fail-closed evidence.
- [ ] Run both old and new pipelines only for validation in a time-bounded non-production comparison window. Longbridge is not a runtime fallback.
- [ ] Obtain product-owner acceptance of field-level capability gaps, especially news, forecasts, and fundamentals.
- [ ] Turn off Longbridge traffic, then remove `LONGBRIDGE_*` configuration, OAuth files/services, MCP client/tools, routes, schemas, SDK requirements, frontend route/view/types, tests, fixtures, and documentation.
- [ ] Run a repository search for `longbridge` (case-insensitive); only an archived migration record may remain.

## 8. Acceptance gates and measurable exit criteria

| Gate | Evidence required |
|---|---|
| Authority | Documented source-to-domain matrix is enforced by tests and response provenance |
| Identity | All in-scope instruments resolve to one canonical instrument or are quarantined; no ticker-only silent join |
| History quality | Coverage and price-reconciliation thresholds are agreed before cutover and met per asset class/benchmark |
| Current data | IBKR quote freshness, entitlement failures, and market-closed state are represented correctly |
| Functional parity | Defined critical flows—performance, positions, research/evidence, trade review/decision—work without Longbridge |
| Safety | Partial, stale, ambiguous, or unavailable source data is visible and does not become asserted fact in agents |
| Operations | Ingestion dashboards/alerts, runbooks, ownership, and rollback-to-prior-read-model procedure are tested |
| Retirement | No production call, credential, dependency, UI control, code path, test, or documentation depends on Longbridge |

## 9. Delivery governance

| Role | Accountable responsibility |
|---|---|
| Product/data owner | Approves domain authority, scope gaps, and reconciliation thresholds |
| Data engineering owner | Owns contracts, adapters, mappings, lineage, and quality exceptions |
| Backend owner | Owns repositories, APIs, agent evidence contracts, and removal of vendor coupling |
| Frontend owner | Owns provenance/freshness presentation and replacement/removal of Longbridge controls |
| Security owner | Reviews credentials, least privilege, access control, retention, and audit evidence |
| QA/release owner | Owns acceptance gates and validates the final dependency-removal inventory |

Use a weekly decision log for unresolved mapping, entitlement, data-license, and capability questions. Treat them as delivery risks with an owner and due date, not informal assumptions.

## 10. Known constraints and next executable decision

This repository contains a substantial Longbridge surface: direct backend services, OAuth/MCP tooling, API routes, agent tools and prompts, performance backfill, frontend administration and research views, configuration, and tests. The inspected History_Book project supplies a versioned, authenticated immutable daily-history contract, including a digest-bound artifact export with a 16 MiB limit, and the underlying identity/provenance model. The Trade Agent does not yet have an adapter. Implementation begins with the source-neutral artifact client, an optional range/chunk mechanism only for oversized production datasets, and IBKR market-data entitlement validation. It must not promise parity for Longbridge news, analyst forecasts, valuation, or fundamentals because those are absent from the reviewed History_Book contract.

The first implementation artifact should be a version-controlled History_Book adapter contract: canonical field map, adjustment-basis rule, authentication method, requested dataset/version semantics, bulk/range behavior, and conId-first mapping sample. That artifact unlocks implementation, reconciliation thresholds, and a reliable delivery estimate.

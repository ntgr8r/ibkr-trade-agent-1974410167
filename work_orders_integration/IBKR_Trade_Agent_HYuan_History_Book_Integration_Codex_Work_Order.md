# IBKR Trade Agent — Bursatilito History_Book Integration Codex Work Order

**Status:** Blocked pending authenticated `READY` History_Book artifacts  
**Mode:** Read-only market/account data integration; no trading authority  
**Primary repository:** `/home/dmabee/DEV_PROJECTS/ibkr-trade-agent-1974410167`  
**Source system:** `/home/dmabee/DEV_PROJECTS/NTGR8R_Project_Orchestrator/apps/history_book`  
**Depends on:** `Master_Data_Management.md` and `Integration_Plan_IBKR_Trade_Agent_HYuan.md`

## Confirmed decisions

| Decision | Confirmed direction |
|---|---|
| Live/current quotes | IBKR only |
| Historical data | History_Book only |
| Performance/benchmark adjustment basis | Support both raw close and History_Book `adjusted_close`; require an explicit report-level selection |
| Initial artifact volume | Must remain within the existing 16 MiB artifact limit |
| Coding start | Wait for a real authenticated `READY` History_Book artifact; do not begin production integration on invented fixtures |
| Work-order scope | Historical identity, history, performance, and benchmarks only; non-historical Longbridge features are deferred |
| Initial source dataset | Current IBKR holdings, symbols requiring prior-trade review/replay, and required benchmarks/FX only |
| Initial daily-history depth | All available History_Book daily history for the in-scope dataset |
| Initial benchmarks | SPY, QQQ, and SMH |
| Initial FX scope | Only in-scope instrument/benchmark currencies converted to the account base currency; verify conversion, missing-rate, and unrelated-pair rejection tests |
| Initial account base currency | USD |
| History_Book authentication | Existing `X-MOP-Service-Token` header, with the shared secret read from an owner-only protected token file |
| Historical-data refresh | Daily after market close |
| Refresh timing | After the latest close among in-scope exchanges |
| Failed/stale refresh behavior | Retain the last valid dataset and visibly report it as stale with limitations |
| Freshness policy | Exchange-session-aware; mark stale only after an expected source publication/session is missed |
| Cutover coverage threshold | 100% of expected exchange sessions for every in-scope holding and benchmark; any gap blocks cutover |
| Artifact-size exception | Block cutover and queue a separate History_Book capacity work order; do not shorten history or remove symbols silently |
| External reconciliation baseline | Read-only IBKR historical-data sample; no Longbridge account or stored Longbridge records exist |
| IBKR reconciliation sample | Every in-scope symbol for the latest 60 trading sessions |
| Raw-close reconciliation tolerance | Exact match; any discrepancy blocks cutover |
| Adjusted-close enablement | Requires documented adjustment semantics and successful corporate-action reconciliation |
| Production cutover approval | Manual approval by the user after review of the completion report |
| Oversized full-universe delivery | Deferred; do not introduce a range/chunk API or increase History_Book limits in this integration |
| History_Book change ownership | No external History_Book source changes under this work order |

## Goal

Replace the IBKR Trade Agent's Longbridge **historical market-data** dependency with Bursatilito History_Book, while preserving this authority model:

```text
IBKR Flex        → account, positions, trades, cash flows
IBKR market data → current quotes and current market state
History_Book     → historical prices, identity, sessions, corporate actions, benchmarks, FX
Trade Agent      → policies, evidence, decisions, application audit records
```

Longbridge must not be used as a runtime fallback or comparison source after this work; no Longbridge account or stored records exist. Do not remove Longbridge features whose replacement/disposition has not been explicitly accepted; make unsupported capabilities visible as unavailable rather than fabricating parity.

Do **not** submit, modify, cancel, transmit, or simulate live orders. Do not change investment policy, trading logic, account data, or History_Book source tables.

## Source facts that must be preserved

History_Book supplies:

- UUID `listing_id` and canonical `company → instrument → listing` identity;
- IBKR `conId`, ISIN, FIGI, exchange, symbol, currency, validity windows, and identity status;
- daily `(listing_id, trade_date)` OHLCV rows, raw `close`, separate `adjusted_close`, source, quality flags, and ingestion time;
- exchange sessions, corporate actions, ingestion-run lineage, immutable dataset versions, lifecycle state, and SHA-256 digests;
- an authenticated immutable daily projection API currently bounded to one listing and 2–101 daily rows;
- an authenticated immutable dataset-artifact API that returns digest-bound canonical historical export bytes, subject to a 16 MiB response bound.

The listing daily-projection API is insufficient for bulk performance/benchmark backfill. Use the existing immutable dataset-artifact API for the initial, limited dataset, which must remain within History_Book's current **16 MiB** response bound. Full-universe delivery, range/chunk APIs, and size-limit increases are deferred. The Trade Agent must not connect directly to History_Book PostgreSQL.

## Existing API decision

Use the following History_Book workflow APIs as the source boundary:

```text
GET /workflow/v1.1/datasets/{dataset_id}/versions/{dataset_version}
GET /workflow/v1.1/datasets/{dataset_id}/versions/{dataset_version}/artifact
GET /workflow/v1.1/datasets/{dataset_id}/versions/{dataset_version}/listings/{listing_id}/daily
```

All require the source service authentication header. The Trade Agent client must first retrieve and validate dataset status, then retrieve the immutable artifact, verify its content digest and canonical schema, and only then ingest it. The per-listing daily endpoint is for bounded evidence/research reads; it is not the performance backfill path.

Do **not** use the Bursatil endpoint `GET /api/v1/candidates/mdg/{con_id}/price-history` as the historical source. It fetches live IBKR chart history for only 1, 5, or 30 days and is neither an immutable History_Book dataset nor a suitable bulk/backfill source. Bursatil core-data listing/provider-mapping APIs may be used only as a separate reconciliation reference, never as a substitute for History_Book identity/provenance.

## Non-negotiable safety rules

1. Keep credentials out of source control, logs, fixtures, API responses, error messages, and this work order.
2. Use only read-only service credentials for History_Book and read-only IBKR data paths.
3. Use `conId` first for identity resolution. Fall back to ISIN/FIGI plus listing exchange only. Never silently join on ticker alone.
4. Preserve decimal-string values from History_Book through validation. Convert to float only at the established Elasticsearch projection boundary if unavoidable.
5. Do not mix raw close and adjusted close. Require an explicit adjustment basis in every historical request and projection.
6. Reject revoked, invalid, stale, ambiguous, duplicate, or digest-mismatched historical data; report a typed limitation instead of substituting data.
7. Do not alter unrelated existing worktree changes.

## Prerequisites

Before writing the production adapter, obtain a source-approved `READY` History_Book dataset artifact covering current IBKR holdings, symbols requiring prior-trade review/replay, and required benchmarks/FX. It must remain within the existing 16 MiB service bound. Also obtain a compact, representative `READY` artifact for automated client tests containing:

- at least two securities and one benchmark;
- identity rows with listing ID, conId, exchange, currency, and at least one external identifier;
- daily bars across at least 30 sessions;
- raw and adjusted close values;
- session/time-zone data, source/digest/version/cutoff fields, and applicable base-currency FX rows;
- one corporate action or an explicitly documented absence of one.

Also obtain the service authentication method, artifact content type/schema, lifecycle rules, 16 MiB response-bound behavior, and exact `adjusted_close` semantics. Verify artifact digest validation, bounded disk/memory use, response-time/error behavior, and service stability before approving production ingestion. If these are unavailable, implement the consumer contracts and mocked client/tests only; do not invent an endpoint or claim end-to-end readiness.

If the approved all-history artifact exceeds 16 MiB, stop before cutover and create a separate capacity work order under `work_orders_integration/`. That work must address source capacity without reducing the approved symbol scope or history depth by default.

## Scope A — Canonical contracts and configuration

### Implement

1. Add versioned common schemas for:

   - `InstrumentIdentity`
   - `DailyBar`
   - `CorporateAction`
   - `MarketSession`
   - `DataProvenance`
   - `HistoricalDatasetReceipt`
   - typed availability/validation errors

2. Add settings in `ibkr_show_backend/app/core/config.py` and safe sample values in `.env.example` files:

   ```text
   HISTORY_BOOK_BASE_URL
   HISTORY_BOOK_SERVICE_TOKEN_FILE
   HISTORY_BOOK_CONNECT_TIMEOUT_SECONDS
   HISTORY_BOOK_READ_TIMEOUT_SECONDS
   HISTORY_BOOK_REQUIRED_CONTRACT_VERSION
   HISTORY_BOOK_MAX_STALENESS_SECONDS
   ```

3. Add validation that configuration is absent/unhealthy without revealing a token, token-file content, or account identifier.
4. Define the canonical adjustment-basis enumeration. Treat current History_Book `adjusted_close` as `provider_adjusted` until the source owner documents its exact policy.

### Acceptance

- Schema and settings unit tests pass.
- Decimal-string parsing retains precision.
- No existing Longbridge schema/type is imported by the new contracts.
- Health/error responses contain safe codes and no secrets.

## Scope B — Authenticated History_Book client

### Implement

1. Add `ibkr_show_backend/app/clients/history_book_client.py` with a small source-specific interface.
2. Load the service token only from the configured owner-only token file and send it in the existing `X-MOP-Service-Token` header; make outbound timeouts, response byte limits, and retries explicit and bounded.
3. Implement immutable artifact retrieval using pinned `dataset_id` and `dataset_version`. Retrieve and validate dataset status before fetching bytes.
4. Enforce the source-approved raised maximum artifact size and stream/download to a bounded temporary file where needed; do not hold an unbounded artifact in memory.
5. Validate before returning records:

   ```text
   HTTP/authentication outcome
   content type and contract version
   response schema and byte bounds
   READY lifecycle state
   dataset/version/cutoff timestamps
   SHA-256 digest
   exact identity fields
   daily-bar uniqueness and OHLC constraints
   ISO currency and adjustment basis
   source freshness
   ```

6. Return typed outcomes for unavailable source, rejected lifecycle, contract drift, digest mismatch, artifact-size violation, stale data, coverage gap, and identity ambiguity.

### Acceptance

Fixture tests cover: valid response; authentication failure; timeout; contract-version mismatch; non-`READY` lifecycle; digest mismatch; invalid decimal; duplicate date; invalid OHLC; stale data; missing currency; and oversized response.

## Scope C — Instrument resolution and Elasticsearch read models

### Implement

1. Add an `InstrumentResolver` and replace uses of `normalize_longbridge_symbol` only in historical-data paths included in this work order.
2. Resolve in strict order:

   ```text
   1. IBKR conId
   2. ISIN plus listing exchange
   3. FIGI plus listing exchange
   4. explicit reviewed mapping
   5. quarantine
   ```

3. Add index definitions and repositories for:

   ```text
   ibkr_instrument_master_v1
   ibkr_market_price_daily_v2
   ibkr_corporate_action_v1
   ibkr_data_ingestion_run_v1
   ibkr_data_quality_exception_v1
   ```

4. Store `history_book_listing_id`, `instrument_id`, `conid`, canonical exchange, currency, adjustment basis, source, dataset ID/version/digest, cutoff/as-of, ingestion time, quality status, and limitations.
5. Use an idempotent key equivalent to:

   ```text
   instrument_id + trading_date + adjustment_basis + dataset_version
   ```

6. Preserve `ibkr_symbol_price_history_v1` during migration. Create a compatibility repository/projection instead of redefining its meaning in place.

### Acceptance

- A re-run of identical immutable data is idempotent.
- A new source dataset version retains lineage; it does not silently overwrite the prior version.
- Ambiguous or unresolved mappings enter the quality-exception index and create no price projection.
- No code path performs ticker-only automatic matching.
- FX tests prove same-currency passthrough, valid as-of conversion to the account base currency, missing-rate limitation behavior, and rejection of unrelated pairs.

## Scope D — Historical performance and benchmark migration

### Implement

1. Replace the direct Longbridge dependency in:

   ```text
   ibkr_show_backend/app/domains/performance/price_auto_backfill.py
   ibkr_show_backend/app/domains/performance/benchmark_price_backfill.py
   ibkr_show_backend/app/domains/performance/benchmark_price_provider.py
   ```

2. Introduce a provider-neutral `HistoricalMarketDataRepository` that reads validated History_Book projections.
3. Make performance/benchmark methods require the requested adjustment basis and report coverage/quality limitations.
4. Use History_Book benchmark and FX data only when their identity, lifecycle, and adjustment policy are validated; otherwise return an explicit unsupported/coverage limitation.
5. Include History_Book dataset provenance in performance outputs used by agents and UI.
6. Schedule one daily immutable-artifact ingestion after the latest close among in-scope exchanges; validate source lifecycle and freshness before publishing new projections.
7. On a missing, stale, or invalid artifact, retain the prior validated projection and emit a visible stale-data limitation; never silently present it as current.
8. Evaluate freshness against History_Book exchange-session metadata and expected source publication, not a fixed 24- or 72-hour clock.

### Acceptance

- Historical performance backfill, benchmark backfill, and benchmark retrieval operate against fixtures without Longbridge imports or network calls.
- Returned price series exclude invalid/unmapped rows and state the limitation.
- Raw-close and provider-adjusted calculations are separately tested and cannot be mixed.
- Adjusted-close reporting remains disabled until the source adjustment policy is documented and corporate actions reconcile successfully.
- Every in-scope holding and benchmark has 100% expected-session coverage; any missing session blocks production cutover.
- Every in-scope symbol's latest 60 trading sessions are reconciled to read-only IBKR historical data, with entitlement/coverage limitations documented; no Longbridge dependency is used.
- Raw closes match the IBKR comparison sample exactly; any discrepancy blocks production cutover.

## Scope E — APIs, evidence, and UI

### Implement

1. Introduce provider-neutral API contracts/routes for historical data, coverage, and data-source health. Do not add new `/longbridge/*` routes.
2. Add provenance to market-history/performance responses:

   ```text
   source
   dataset_id
   dataset_version
   content_digest
   cutoff_at / as_of_at
   adjustment_basis
   quality_status
   coverage and limitations
   ```

3. Update research/evidence services in scope to consume canonical historical facts. An unavailable fact must remain unavailable in agent output.
4. Update frontend types/components for historical provenance and data limitations where those outputs are shown.
5. Add a History_Book historical-data health/coverage panel or a minimal health endpoint if UI work cannot safely be completed in the same change. It must not present historical values as live quotes.

### Acceptance

- API contract tests validate provenance and limitations.
- UI tests/build pass for changed views.
- Agent/evidence tests prove a stale, partial, or ambiguous input is labeled rather than asserted as fact.

## Scope F — Longbridge feature inventory and retirement boundary

### Implement

1. Inventory every Longbridge dependency and categorize it:

   ```text
   historical price/benchmark → History_Book replacement in this work order
   current quote/current market state → IBKR-only separate work item
   news, macro news, forecasts, valuation, financial statements → explicit product disposition required
   admin/OAuth/MCP infrastructure → remove only after dependent paths are retired
   ```

2. Record the inventory and unresolved product decisions in the completion report.
3. Remove only the Longbridge code/configuration/tests made dead by the completed historical migration. Preserve unsupported paths until they are removed or replaced under separately approved work.

### Acceptance

- The historical performance path has zero Longbridge imports/references.
- No unsupported research feature is misrepresented as migrated.
- The completion report lists every remaining Longbridge dependency and its disposition/owner.

## Verification commands

Run the relevant tests after implementation. At minimum:

```bash
pytest ibkr_show_backend/tests
pytest ibkr_show_worker/tests
cd ibkr_show_frontend && npm run test && npm run build
scripts/check_release_safety.sh
```

If the full suites cannot run, run the narrow new/affected tests and report the exact blocking dependency, command, and failure. Do not weaken tests to obtain a pass.

## Deliverables

1. Source-neutral History_Book contracts, configuration, client, resolver, repositories, and tests.
2. Versioned Elasticsearch index definitions and idempotent ingestion/read projection.
3. History_Book-backed performance/benchmark historical-data paths.
4. Provider-neutral API and provenance/limitation propagation.
5. Updated frontend types/components if API payloads are surfaced there.
6. `work_orders_integration/IBKR_Trade_Agent_HYuan_History_Book_Integration_Completion_Report.md` containing:

   - changed files and architecture decisions;
   - exact source contract/version used;
   - mapping, coverage, reconciliation, and test results;
   - security checks performed;
   - remaining Longbridge inventory and feature gaps;
   - cutover readiness: `READY`, `NOT_READY`, or `BLOCKED` with reason.
   - the decision record from this work order, including the recommended safeguards accepted: IBKR-only live quotes, History_Book-only historical data, protected token-file authentication, 16 MiB artifact limit, all available in-scope history, SPY/QQQ/SMH benchmarks, USD FX conversion, daily exchange-session-aware refresh, stale-data disclosure, 100% expected-session coverage, 60-session IBKR reconciliation, exact raw-close matching, and deferred adjusted-close enablement;
   - an explicit manual-cutover request addressed to the user. No automatic production cutover is permitted.

## Definition of done

The work is complete when the Trade Agent can ingest and serve validated, provenance-rich History_Book historical data through source-neutral contracts; performance and benchmark historical paths no longer import/use Longbridge; unsafe or incomplete data fails closed; tests pass at the appropriate layer; and the completion report documents remaining non-historical Longbridge work. Production cutover requires the user's manual approval after reviewing that report. Full Longbridge retirement is a subsequent release gate, not an assumed outcome of this work order.

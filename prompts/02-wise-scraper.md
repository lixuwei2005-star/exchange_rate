# Goal — Fix the `wise` scraper

> Single-scraper task. Read CLAUDE.md §2 (direction/terminology) and §7 (scraper interface) first. Do not touch any other scraper or the frontend.

## Context

`backend/app/scrapers/wise.py` currently fails with `401 Unauthorized` because it calls `GET https://api.wise.com/v1/rates`, which now requires an API token. We do not want to manage a token. Switch to Wise's **unauthenticated quote endpoint**, which needs no auth and is explicitly intended for displaying example rates.

Current spec to follow: https://docs.wise.com/guides/product/send-money/quotes/unauthenticated-quote

## The fix

Replace the request with:

```
POST https://api.wise.com/v3/quotes
Content-Type: application/json

{
  "sourceCurrency": "CNY",
  "targetCurrency": "MYR",
  "sourceAmount": 1000
}
```

For the generic `fetch(base, quote)` signature: `sourceCurrency=base`, `targetCurrency=quote`, `sourceAmount=1000`.

**Before writing the parser, run this exact request with curl and confirm the real response shape.** The host or path may differ from the above — if `api.wise.com` returns 404, check the doc for the correct host. Write the parser to match the actual response, not assumptions. Paste the trimmed response in your final report.

## What to extract

From the response:

- `rate` — Wise's mid-market rate. For our query direction (source=CNY, target=MYR) this is already **MYR per 1 CNY**, which is our storage convention. Store as-is.
- `paymentOptions[]` — array of pay-in/pay-out combos, each with a `fee` object.

Rules:

- `ScrapeResult.rate` ← response `rate` (already MYR per CNY, no inversion).
- Fee: from `paymentOptions`, prefer the option where `payIn == "BANK_TRANSFER"` and `payOut == "BANK_TRANSFER"`. If that combo is absent, pick the option with the lowest `fee.total`. Document which you chose.
- `fee_estimate` ← that option's `fee.total`. `fee_currency` ← source currency (CNY), but **verify** against the actual response — confirm the fee is denominated in source currency.
- `rate_type` ← `"p2p"`.
- `raw_payload` ← the full response dict.

## Contingency (important)

Wise may not fully support **sending from CNY** (China capital controls). If the CNY→MYR quote returns an error or an empty `paymentOptions` array:

1. Still try to obtain the mid-market `rate` from the response if present.
2. If the whole request fails, retry once with the **reverse** pair (source=MYR, target=CNY), take its `rate`, and invert it (`1 / reverse_rate`) for storage. Set `fee_estimate = None`.
3. Either way, **report clearly** in your final reply whether real fee data was available for CNY→MYR, so we know whether Wise's fee column will be populated.

The goal is: at minimum, a valid mid-market rate stored and `wise` showing `fresh`. Fee is best-effort.

## Normalization & sanity

- Stored `rate` must be MYR per 1 CNY, in range `[0.5, 0.8]`. If outside, raise `ScraperError` — likely an inverted direction; re-check.

## Tests

- Add `backend/tests/test_wise_scraper.py` using `respx` to mock `POST /v3/quotes`. Use a realistic JSON sample captured from your curl (trimmed). Assert:
  - `rate` parsed correctly and equals the mocked mid rate.
  - fee extracted from the correct `paymentOption`.
  - `rate_type == "p2p"`.
  - an out-of-range rate raises `ScraperError`.
  - the reverse-pair contingency path works (one test with an empty `paymentOptions`).
- `make scrape CHANNEL=wise` must succeed and write a fresh snapshot.

## Update CLAUDE.md

- §6 data-sources table: change the Wise `Source URL` to `POST https://api.wise.com/v3/quotes (unauthenticated quote)`.
- §6 fee model: keep `WISE_FEE_DYNAMIC = True`; add a comment that the fee is captured at a 1000-CNY reference amount and treated as roughly fixed for display (Wise's real fee scales slightly with amount — acceptable approximation for V1).
- §2.5 per-channel table: confirm the Wise row note still reads "rate = response_rate (already correct)".

## Definition of done (confirm each ✅/❌ in your report)

1. curl against the new endpoint returns a valid quote (paste trimmed response).
2. `make scrape CHANNEL=wise` succeeds; `wise` shows `fresh` in the admin panel.
3. Stored rate is in `[0.5, 0.8]`.
4. Fee status reported (populated, or `None` with reason).
5. `make test` passes, including the new Wise tests.
6. `make lint` passes.
7. CLAUDE.md updated per above.

## Out of scope

- Do NOT touch any other scraper. UnionPay is the next, separate task.
- Do NOT change the frontend.
- Do NOT add an API token or any auth for Wise.

## When done, report

- The trimmed curl response.
- Which `paymentOption` you used for the fee and why.
- Whether CNY→MYR fee data was available, or you fell back to the reverse-pair mid rate.
- The done checklist with ✅/❌.

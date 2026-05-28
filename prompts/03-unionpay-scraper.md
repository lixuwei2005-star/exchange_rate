# Goal — Implement the `unionpay` scraper

> Single-scraper task. Read CLAUDE.md §2 (direction/terminology) and §7 (scraper interface) first. Do not touch any other scraper or the frontend.

## Context

UnionPay publishes its daily card-transaction exchange rates as a **static JSON file** named by date — no auth, no form POST, no signature, no cookies needed. The current `unionpay.py` stub (and the old 404) hit the wrong URL. The real endpoint is:

```
GET https://www.unionpayintl.com/upload/jfimg/{YYYYMMDD}.json
```

Example: `https://www.unionpayintl.com/upload/jfimg/20260528.json` → `200`, `application/json`, ~137 KB. It's a plain nginx static file; a normal GET with our standard User-Agent works. Do NOT send analytics cookies.

## Response structure (verified)

```json
{
  "exchangeRateJson": [
    { "transCur": "AED", "baseCur": "AUD", "rateData": 0.38477535 },
    { "transCur": "MYR", "baseCur": "CNY", "rateData": 1.71xxxxxx },
    ...
  ]
}
```

- Top-level key: `exchangeRateJson` (array of ~thousands of cross-currency entries).
- Each entry: `transCur` (transaction currency), `baseCur` (settlement/card currency), `rateData` (a JSON **number**).
- Semantics: **`1 transCur = rateData × baseCur`**. (Verified against AFN/AMD/ALL → AUD entries.)

## What to extract & normalize

For our use case (Chinese UnionPay card billed in CNY, spending MYR in Malaysia):

- Find the **single** entry where `transCur == quote` and `baseCur == base`. For V1 that is `transCur == "MYR"` and `baseCur == "CNY"`.
- That `rateData` is **CNY per 1 MYR** (≈ 1.71).
- Our storage convention is **MYR per 1 CNY**, so **invert**: `rate = 1 / rateData` (≈ 0.585).
- Use `Decimal(str(rateData))` — never float — then invert with Decimal.
- `rate_type` → `"card_network"`.
- `fee_estimate` → `None`. UnionPay's published rate is a near-mid composite rate with no built-in markup; the 1–2% real cost is an **issuer-dependent** fee added on top, which we do not model in V1. Add a code comment saying so.
- `raw_payload` → the matched entry dict (NOT the whole 137 KB file — just the MYR/CNY entry plus the file date used).

If no `transCur=MYR, baseCur=CNY` entry exists in the file, raise `ScraperError` (don't silently pick a different baseCur).

## Date logic & fallback

The file is named `YYYYMMDD` in **Asia/Shanghai** time. MYR is a non-European currency, so its rate takes effect at **11:00 Beijing time**; we scrape after that.

1. Compute today's date in `Asia/Shanghai`, format `YYYYMMDD`, GET that file.
2. If it 404s (e.g., not published yet, weekend/holiday delay), step back one day and retry — up to 3 days back.
3. Record which file date was actually used (put it in `raw_payload`).

## Schedule

This channel updates **once per day**. Schedule it with an APScheduler **cron trigger at 11:30 `Asia/Shanghai`** (= 11:30 SGT, same offset as the server), not the generic interval rotation. Re-fetching the same static file is harmless, so if wiring a dedicated cron is awkward, a low-frequency interval (e.g., every 6 h) is an acceptable fallback — but prefer the daily cron and note the choice.

Staleness: since this source is daily, do **not** treat a multi-hour-old success as stale. Per CLAUDE.md, "stale" is failure-based (consecutive fetch failures), so a successful daily fetch keeps it `fresh` regardless of data age. Confirm the existing staleness logic is failure-based, not age-based; if it's age-based with a short threshold, exclude `unionpay` or give it a ≥ 26 h threshold.

## Normalization & sanity

- Stored `rate` must be MYR per 1 CNY, in `[0.5, 0.8]`. If outside, raise `ScraperError` — almost certainly means the inversion was skipped (raw `rateData` ≈ 1.71 would land out of range and catch this).

## Tests

Add `backend/tests/test_scraper_unionpay.py` using `respx` to mock the file GET. Use a trimmed `exchangeRateJson` array with a few entries including `{transCur: "MYR", baseCur: "CNY", rateData: 1.71}`. Assert:

- The MYR/CNY entry is located and `rate` is correctly inverted (≈ 0.585), in range.
- `rate_type == "card_network"`, `fee_estimate is None`.
- A raw (non-inverted) value out of `[0.5, 0.8]` raises.
- Missing MYR/CNY entry raises `ScraperError`.
- Date fallback: today's URL mocked as 404, yesterday's returns valid JSON → scraper succeeds using yesterday's file.

`make scrape CHANNEL=unionpay` (or the local equivalent) must succeed and write a fresh snapshot.

## Update CLAUDE.md

- §6 data-sources table: change `unionpay` Source URL to `GET https://www.unionpayintl.com/upload/jfimg/{YYYYMMDD}.json (static daily JSON)`, Refresh to `daily 11:30 SGT`, Fragility to `Low`.
- §2.5 per-channel table: update the UnionPay row to: native quote `1 transCur = rateData × baseCur`; field `entry transCur=MYR, baseCur=CNY`; to stored rate `1 / rateData`.
- §6 fee model: keep `UNIONPAY_MARKUP = 0.0`; expand the comment to note the published rate is near-mid and the real 1–2% cost is issuer-dependent, not modeled in V1.

## Definition of done (confirm each ✅/❌ in your report)

1. curl/GET against today's file returns valid JSON (paste the matched MYR/CNY entry).
2. `make scrape CHANNEL=unionpay` succeeds; `unionpay` shows `fresh`.
3. Stored rate is in `[0.5, 0.8]` (inverted correctly).
4. `rate_type == "card_network"`, `fee_estimate is None`.
5. Scheduled as a daily 11:30 Asia/Shanghai cron (or documented fallback).
6. `make test` passes, including new UnionPay tests (incl. date-fallback test).
7. `make lint` passes.
8. CLAUDE.md updated per above.

## Out of scope

- Do NOT touch any other scraper or the frontend.
- Do NOT send cookies or fake browser headers — it's a static file.
- Do NOT model issuer fees in V1.

## When done, report

- The matched MYR/CNY entry (raw `rateData`) and the resulting stored `rate`.
- Which file date was used (today or a fallback day).
- The done checklist with ✅/❌.

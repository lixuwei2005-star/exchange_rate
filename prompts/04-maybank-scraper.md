# Goal — Implement the `maybank` scraper

> Single-scraper task. Read CLAUDE.md §2 (direction/terminology) and §7 (scraper interface) first. Do not touch any other scraper or the frontend.

## Context

Maybank's foreign-exchange counter rates are **server-side rendered directly into the HTML** of a public page — there is no separate JSON API or XHR. The whole rate table is a `<table>` in the page source. So the scraper is just: GET the page, parse the table with BeautifulSoup, pull the CNY row.

Endpoint (GET, no params, no auth, no POST):

```
GET https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/rates/forex_rates.page
```

## HTML structure (verified from page source)

Each currency is a `<tr>`. The CNY row looks like this:

```html
<tr>
  <td></td>
  <td class="currency">
    <div class="group-image-text">
      <img src="/maybank_gif/s_images/flags/china_flag.gif">
      <span>100 Chinese Renminbi</span>
    </div>
  </td>
  <td>59.9500</td>        <!-- col 1: TT/OD Selling -->
  <td>57.4200</td>        <!-- col 2: TT Buying      ← THIS ONE -->
  <td>57.4200</td>        <!-- col 3: OD/DD Buying   -->
  <td><p>N/A</p></td>     <!-- col 4: Notes Selling  -->
  <td><p>N/A</p></td>     <!-- col 5: Notes Buying   -->
  <td></td>
</tr>
```

Notes:
- A leading empty `<td></td>` and a trailing empty `<td></td>` wrap the row — don't index blindly from position 0.
- Rate cell text may be a bare number (`57.4200`) or `N/A` (sometimes wrapped in `<p>N/A</p>`).
- Column order after the currency cell: **[TT/OD Selling, TT Buying, OD/DD Buying, Notes Selling, Notes Buying]**.

## What to extract & normalize

For CNY→MYR (customer hands CNY to the bank, receives MYR → the bank is **buying** CNY): use the **TT Buying** rate (column 2 above) = `57.4200`.

Parsing rules:

1. Locate the table containing the rate rows (the one whose rows have `<td class="currency">`).
2. Find the row whose currency `<span>` text contains the target currency name. For V1 that's `"Chinese Renminbi"` (case-insensitive substring match). If not found, raise `ScraperError`.
3. Parse the **multiplier** from the span text — it's the leading integer (e.g., `100` in `"100 Chinese Renminbi"`). Do NOT hardcode 100; other currencies use `1`.
4. From that row, collect the rate `<td>`s **after** the `td.currency` cell, in document order, as `[tt_selling, tt_buying, od_buying, notes_selling, notes_buying]`. For each, read text; treat `N/A` (with or without `<p>` wrapper) as missing.
5. Take **`tt_buying`** (index 1). If it's `N/A`/missing, raise `ScraperError` (we need the TT buying rate).
6. The rate is quoted per `multiplier` units of CNY. Stored convention is **MYR per 1 CNY**, so:
   `rate = Decimal(tt_buying) / Decimal(multiplier)` → `57.4200 / 100 = 0.5742`.
   Use `Decimal(str(...))`, never float.
7. `rate_type` → `"tt_buy"`.
8. `fee_estimate` → `None`. The bank's spread is already baked into the buying rate; the RM TT charge applies to outbound transfers, not to this counter-rate comparison, so we don't add a fee in V1. Add a code comment saying so.
9. `raw_payload` → a small dict: `{currency_label, multiplier, tt_selling, tt_buying, od_buying, last_update}`. Also parse the page's "Last Update" timestamp (e.g., `May 28, 2026 05:20 PM`) into `raw_payload` if easy.

## WAF / anti-bot handling

Maybank sits behind Akamai. The page opens in a browser because of browser cookies/challenge tokens; a naive server-side GET may get `403` or a JS-challenge page instead of the rates HTML.

1. First attempt: plain `httpx` GET with **browser-like headers** — a realistic desktop `User-Agent`, `Accept: text/html,application/xhtml+xml`, `Accept-Language: en-US,en;q=0.9`. No cookies.
2. Detect failure: if status is `403`, or the response body does **not** contain `"Chinese Renminbi"` (i.e., you got a challenge/blocked page, not the rate table), raise `ScraperError` with a clear message and **report it** — do not retry with proxies, do not rotate User-Agents abusively, do not fake Akamai cookies.
3. If the plain GET works, great — that's the whole scraper.
4. If it's blocked: **do NOT silently add Playwright in this task.** Stop, report that server-side access is blocked by Akamai, and leave `maybank` disabled. We'll decide separately whether a headless-browser fallback is worth it.

## Normalization & sanity

- Stored `rate` must be MYR per 1 CNY, in `[0.5, 0.8]`. Maybank's retail buying rate is expected ~`0.574` (slightly below mid 0.585 — that's the retail spread, which is correct and the whole point). If outside range, raise — likely the `/multiplier` step was skipped (raw `57.42` would be way out of range and catch it).

## Tests

Add `backend/tests/test_scraper_maybank.py` using `respx` to mock the page GET with a trimmed HTML sample containing the CNY row (and a `1 US Dollar` row to verify multiplier handling). Assert:

- CNY row located; `tt_buying` parsed; multiplier 100 applied → `rate ≈ 0.5742`, in range.
- `rate_type == "tt_buy"`, `fee_estimate is None`.
- A `1`-multiplier currency parses without dividing wrongly.
- `N/A` in the tt_buying cell raises `ScraperError`.
- Missing CNY row raises `ScraperError`.
- A `403` / challenge-page body (no "Chinese Renminbi") raises `ScraperError`.

`make scrape CHANNEL=maybank` (or local equivalent) must either write a fresh snapshot (if Akamai lets the server through) or fail cleanly with the blocked-access message.

## Update CLAUDE.md

- §6 data-sources table: change `maybank` Source URL to `GET .../personal/rates/forex_rates.page (server-rendered HTML table)`, Refresh `6 h`, Fragility `Med (Akamai)`.
- §2.5 per-channel table: update Maybank row → native quote `MYR per N units (N from label)`; field `TT Buying column ÷ multiplier`; to stored rate `tt_buying / multiplier`.
- §6 fee model: keep `MAYBANK_TT_FEE_MYR` but comment that it's **not** applied to the counter-rate comparison (spread already in the buying rate); fee_estimate is None for V1.

## Definition of done (confirm each ✅/❌ in your report)

1. Plain server-side GET result: did it return the rates HTML (200 + "Chinese Renminbi" present) or get Akamai-blocked? State clearly.
2. If accessible: `make scrape CHANNEL=maybank` succeeds; `maybank` shows `fresh`; stored rate ≈ 0.574, in `[0.5, 0.8]`.
3. If blocked: scraper fails cleanly with a blocked-access message; `maybank` left disabled; no proxies/cookie-faking used.
4. `rate_type == "tt_buy"`, `fee_estimate is None`.
5. `make test` passes, including new Maybank tests.
6. `make lint` passes.
7. CLAUDE.md updated per above.

## Out of scope

- Do NOT touch any other scraper or the frontend.
- Do NOT add Playwright in this task (even if blocked — report instead).
- Do NOT use proxies or fake Akamai cookies.
- CIMB is a separate next task.

## When done, report

- Whether the server-side GET was allowed through or Akamai-blocked (this decides Maybank's fate).
- The parsed CNY TT-buying value and the resulting stored rate.
- The done checklist with ✅/❌.

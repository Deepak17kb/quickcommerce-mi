# External sources v1: company, market and competitor documents for the analyst

Built 2026-09-24. This is extension 5 of the post-chain plan. The facts themselves are in
`docs/external/MARKET_CONTEXT_EXTERNAL.md`; this page is the method.

## A fourth provenance label: EXTERNAL

| Label | Meaning |
|---|---|
| REAL | The project's observed data: the 21,949 Blinkit rows of 2026-07-10, or a REAL-only model |
| SYNTHETIC | Generated data, or a model or simulation built on it |
| METHOD | How the project works, with no market statement |
| **EXTERNAL** | A cited public web source (news report, earnings-call coverage, a store map). Not the project's data, and never checked against it |

EXTERNAL is kept apart from REAL on purpose. "Blinkit had 2,443 stores" (a news report) and "1,354 of the 21,949 REAL Blinkit
listings (6.17%) were out of stock on 2026-07-10" (the project's own observation) are different kinds of evidence. The analyst
never lets one pass for the other.

## How the facts were collected

- **Fetched pages only.** Each fact was confirmed on the fetched page itself, never taken from a search-engine summary.
  Two pages refused access (HTTP 403) and one would not render. Those facts were sourced elsewhere or left out.
- **Full citation.** Every fact records the publisher, the title (or, where none was captured, that it wasn't), the
  publication date, the URL and the retrieval date (2026-09-24).
- **No sales figures.** Revenue, GMV/GOV/NOV, order counts, profit or margin, and market share are left out even where
  sources report them. One headline that states revenue and loss figures was replaced with a neutral description, so a
  retrieved passage cannot leak them.
- **Conflicts are recorded, not resolved.** The Blinkit Bhubaneswar launch article is datelined "Jan 25" in its body
  but shows 8 October 2025 as its publication date, so no launch date is recorded.
- **Circularity is stated.** The store map that lists Bhubaneswar's 30 dark stores is the same source the project's
  store master was built from (`data/reference/STORES*.csv`, `source` = "QuickCommerceMap public store listings").
  Re-fetched, it still lists all 30 stores, with the same first name segment and PIN code. That is a freshness check on
  the store master, not independent validation. The same page shows Zepto as not operating in Bhubaneswar, which fits
  the project covering exactly these four platforms.

## What the analyst does with them

- **Knowledge base (`src/analyst/kb.py`).** It indexes `docs/external/*.md`. A document whose title declares
  "(EXTERNAL)" labels every section EXTERNAL.
- **Verifier (`src/analyst/guard.py`), three rules:**
  - A claim citing an external source is relabelled EXTERNAL, whatever it was labelled.
  - A claim labelled EXTERNAL that cites anything else is relabelled from its real source.
  - Every EXTERNAL claim must carry its source URL.
- **Banners.** Any EXTERNAL claim adds an EXTERNAL banner to the answer, next to the SYNTHETIC one.
- **Offline engine.**
  - An EXTERNAL claim is the fact paragraph of its section, with the URL in `source_detail`.
  - An EXTERNAL section whose heading matches the question ranks first.
  - A synthetic model verdict is not put ahead of it.
- **Refusal policy.** It now also refuses questions about "gross order value", "net order value", "GOV" and "NOV", the
  words company sources use for sales. The pattern ignores "Nov 2025" and "gov.in" (tested).
- **Claude engine.** The answer schema accepts EXTERNAL. The system prompt states that an EXTERNAL fact never confirms
  or contradicts a SYNTHETIC result.

## What EXTERNAL facts can and cannot do here

- **They can give context.** Examples: Eternal management called April–June 2026 "the peak of competitive intensity";
  Blinkit dropped its 10-minute branding in January 2026; the distributors' federation asked the CCI to examine deep
  discounting.
- **They cannot confirm a synthetic result.** The generator's Flipkart Minutes price level was planted by hand. No news
  report makes it more or less real.
- **They cannot fill the project's data gaps.** One REAL snapshot still cannot show a discounting trend, whatever an
  earnings call says.

## Tests and eval

`tests/test_analyst.py` checks:
- every external passage is labelled EXTERNAL;
- every fact section has a URL and a retrieval date;
- the verifier's three EXTERNAL rules hold;
- the order-value refusals fire, and the pattern does not over-reach.

Eval: the tuning set adds one question that must be answered from an EXTERNAL fact and one order-value refusal. The
held-out set adds three questions written before they were run: two answered from EXTERNAL facts and one refusal.
The docs deliberately do not quote eval questions, so their text cannot make retrieval easier for those questions.

# Digest link-quality observability

## Why this exists

Initial user feedback identified broken and paywalled links as a repeated pain
point. Before changing article UI or filtering sources, the backend measures the
news links selected during daily digest generation.

This is **observability only**. It does not suppress articles, add badges, alter
ranking, or make a second request to a publisher.

## Measurement path

The production digest already sends each selected news URL to Tavily Extract for
summary content. A deterministic Tavily target result is requested once; transient
transport/429/5xx provider failures retain one bounded retry. Two consecutive 429s open
an in-process circuit for the rest of the UTC day, preventing quota hammering; it resets
automatically the next day. No publisher HEAD/GET probe is added. `TavilyExtractor.extract_single_with_quality()` consumes the
same response's `results` and `failed_results` fields and classifies it as:

- `accessible`: extracted content passed the existing 100-character threshold;
- `suspected_paywall`: extracted content or an explicit Tavily failure contains
  a conservative subscription/sign-in/paywall marker;
- `broken`: an explicit terminal failure such as 404, 410, invalid URL/host, or
  DNS name-resolution failure;
- `unknown`: ambiguous access denial, timeout, provider error, bot protection,
  short/empty content, no extractor, or malformed response.

`unknown` is intentional: ambiguous 401/403/5xx responses are not guessed to be
paywalls or broken links. Redirect rate is not measured because Tavily does not
provide a reliable redirect chain/final URL. Measuring redirects would require
another publisher request, which this change deliberately avoids.

## Logfire event

`EnhancedDigestService._process_news_parallel()` emits one structured event per
digest:

```text
message = "Digest link quality measured"
schema_version = 1
measurement_scope = "selected_news_links"
attempted_count
accessible_count / accessible_pct
suspected_paywall_count / suspected_paywall_pct
broken_count / broken_pct
unknown_count / unknown_pct
extraction_success_count
```

Filter Logfire on the exact message, then aggregate counts/percentages over at
least 7–14 production runs before making a product decision. The event contains
no URL, domain, title, article body, user/task ID, email, profile information, or
raw provider error.

Percentages measure **selected-link generation attempts**, not confirmed recipient
exposure or unique publisher URLs. A later rendering/delivery failure can prevent a
measured link from reaching the recipient, and retries can measure it again. The same
URL appearing in several personalized digests is counted several times by design.

## Feedback CTA

New Jinja-rendered digests include a small `Help shape Paperboy` link to
`https://tally.so/r/A7G02o` before the footer. Email and Dashboard share the same
stored HTML. Set `FEEDBACK_CTA_ENABLED=false` to end the feedback window without
a template change; `FEEDBACK_FORM_URL` overrides the destination.

The rare LLM/fallback HTML path does not include the CTA. The CTA never blocks
digest generation.

## Decision rule

Do not add UI labels based on individual heuristic classifications. First review
aggregate production data and manually audit a sample of links. If the signal is
material:

1. validate suspected-paywall precision against a sample;
2. decide whether to label, filter, or substitute accessible sources;
3. separately investigate `unknown` if it dominates the metric.

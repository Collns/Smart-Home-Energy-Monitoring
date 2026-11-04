"""End-to-end latency test (target < 2 s).  OWNER: Part 3

Idea: publish readings with a known ts, then query ADX for ingestion_time() - ts:
    PowerRaw
    | where ts > ago(10m)
    | extend latency = ingestion_time() - ts
    | summarize p50 = percentile(latency, 50), p95 = percentile(latency, 95), max(latency)
Note: ingestion_time() requires the IngestionTime policy (on by default for new tables).
TODO Part 3: run for 10+ minutes, record p50/p95 in docs/test_results.md.
"""

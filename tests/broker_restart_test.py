"""Broker restart test (target: zero lost readings at QoS 1).  OWNER: Part 1

Plan:
  1. Run the pipeline, note the time.
  2. docker compose restart mosquitto  (repeat a few times)
  3. Count gaps in seq per device in ADX:
       PowerRaw
       | where ts between (start .. end)
       | summarize n = count(), expected = max(seq) - min(seq) + 1 by device_id
       | extend missing = expected - n
  Remember the simulator drops DROP_RATE of readings on purpose –
  set DROP_RATE=0 and MALFORMED_RATE=0 for this test.
TODO Part 1: automate and record results in docs/test_results.md.
"""

"""Write rows to Azure Data Explorer with a local disk buffer.  OWNER: Part 2

- Batches rows and flushes every FLUSH_S seconds (keeps latency low).
- Uses ManagedStreamingIngestClient (streaming, falls back to queued).
- If ADX is disabled or unreachable, rows go to /data/buffer_<table>.jsonl and
  are retried on the next flush.
"""
import io
import json
import os
import threading
import time

ADX_ENABLED = os.getenv("ADX_ENABLED", "false").lower() == "true"
BUFFER_DIR = os.getenv("BUFFER_DIR", "/data")
FLUSH_S = float(os.getenv("ADX_FLUSH_S", "1"))

MAPPINGS = {"PowerRaw": "PowerRawMapping", "Alerts": "AlertsMapping"}


class AdxWriter:
    def __init__(self):
        self.pending = {t: [] for t in MAPPINGS}
        self.lock = threading.Lock()
        self.client = None
        if ADX_ENABLED:
            self._connect()
        threading.Thread(target=self._flush_loop, daemon=True).start()

    def _connect(self):
        from azure.kusto.data import KustoConnectionStringBuilder
        from azure.kusto.ingest import ManagedStreamingIngestClient

        kcsb = KustoConnectionStringBuilder.with_aad_application_key_authentication(
            os.environ["ADX_CLUSTER_URI"],
            os.environ["ADX_PROCESSOR_CLIENT_ID"],
            os.environ["ADX_PROCESSOR_CLIENT_SECRET"],
            os.environ["AZURE_TENANT_ID"],
        )
        # ingest (DM) endpoint is derived automatically from the engine URI
        self.client = ManagedStreamingIngestClient(kcsb)
        print("ADX writer connected")

    def write(self, table: str, row: dict):
        row = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
        with self.lock:
            self.pending[table].append(row)

    # ---------------------------------------------------------------
    def _flush_loop(self):
        while True:
            time.sleep(FLUSH_S)
            for table in MAPPINGS:
                with self.lock:
                    rows, self.pending[table] = self.pending[table], []
                rows = self._read_buffer(table) + rows
                if not rows:
                    continue
                if self.client and self._ingest(table, rows):
                    self._clear_buffer(table)
                else:
                    self._write_buffer(table, rows)

    def _ingest(self, table, rows) -> bool:
        from azure.kusto.data.data_format import DataFormat
        from azure.kusto.ingest import IngestionProperties

        props = IngestionProperties(
            database=os.environ.get("ADX_DATABASE", "SmartHomeEnergy"),
            table=table,
            data_format=DataFormat.MULTIJSON,
            ingestion_mapping_reference=MAPPINGS[table],
        )
        data = "\n".join(json.dumps(r) for r in rows).encode()
        try:
            self.client.ingest_from_stream(io.BytesIO(data), ingestion_properties=props)
            return True
        except Exception as e:  # network down, auth error, throttling...
            print(f"ADX ingest failed for {table} ({len(rows)} rows): {e}")
            return False

    def _path(self, table):
        return os.path.join(BUFFER_DIR, f"buffer_{table}.jsonl")

    def _read_buffer(self, table):
        if not self.client:          # ADX disabled: buffer file is the output, don't re-read
            return []
        try:
            with open(self._path(table)) as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def _write_buffer(self, table, rows):
        mode = "w" if self.client else "a"   # rewrite whole backlog when retrying
        with open(self._path(table), mode) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def _clear_buffer(self, table):
        try:
            os.remove(self._path(table))
        except FileNotFoundError:
            pass

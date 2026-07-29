import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pyspark.sql import SparkSession


TABLE = "rest.published.gda_spark_commit_failure_probe"
UPSTREAM = "http://gravitino-persistence:9001"
PROXY = "http://127.0.0.1:19001"
WAREHOUSE = "s3://gda-metadata-warehouse/warehouse"
OBJECT_STORE_ENDPOINT = "http://metadata-object-store:9000"
DATA_PREFIX = WAREHOUSE + "/published/gda_spark_commit_failure_probe/data/"
BASELINE_ROWS = ["spark-baseline-a", "spark-baseline-b"]
UNCERTAIN_ROW = "spark-uncertain-commit"


class ProxyState:
    def __init__(self):
        self.lock = threading.Lock()
        self.response_drop_armed = False
        self.provider_success_responses_dropped = 0
        self.uncertain_commit_forwarded_requests = 0
        self.suppressed_duplicate_commit_requests = 0
        self.forwarded_commit_requests = 0
        self.total_requests = 0
        self.provider_success_status = None


state = ProxyState()


def is_table_commit(path, body):
    if "/tables/" not in path:
        return False
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return False
    return isinstance(payload.get("requirements"), list) and isinstance(
        payload.get("updates"), list
    )


def commit_state_unknown(message):
    return json.dumps(
        {
            "error": {
                "message": message,
                "type": "ServiceFailureException",
                "code": 504,
            }
        },
        sort_keys=True,
    ).encode("utf-8")


class UncertainCommitProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.forward()

    def do_HEAD(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def do_DELETE(self):
        self.forward()

    def send_payload(self, status, body, content_type=None):
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def forward(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        commit = self.command == "POST" and is_table_commit(self.path, body)
        with state.lock:
            state.total_requests += 1
            suppress_duplicate = (
                commit
                and state.response_drop_armed
                and state.provider_success_responses_dropped == 1
            )
            if suppress_duplicate:
                state.suppressed_duplicate_commit_requests += 1
        if suppress_duplicate:
            payload = commit_state_unknown(
                "uncertain commit response remains unavailable; reconcile before resubmit"
            )
            self.send_payload(504, payload, "application/json")
            return

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {
                "connection",
                "content-length",
                "host",
                "proxy-connection",
                "transfer-encoding",
            }
        }
        request = urllib.request.Request(
            UPSTREAM + self.path,
            data=body if self.command in {"POST", "PUT", "PATCH"} else None,
            headers=headers,
            method=self.command,
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
            status = response.status
            response_body = response.read()
            content_type = response.headers.get("Content-Type")
        except urllib.error.HTTPError as exc:
            status = exc.code
            response_body = exc.read()
            content_type = exc.headers.get("Content-Type")
        except urllib.error.URLError:
            status = 502
            response_body = json.dumps(
                {
                    "error": {
                        "message": "catalog upstream unavailable",
                        "type": "ServiceFailureException",
                        "code": 502,
                    }
                },
                sort_keys=True,
            ).encode("utf-8")
            content_type = "application/json"

        drop_success = False
        if commit:
            with state.lock:
                state.forwarded_commit_requests += 1
                drop_success = (
                    state.response_drop_armed
                    and 200 <= status < 300
                    and state.provider_success_responses_dropped == 0
                )
                if drop_success:
                    state.provider_success_responses_dropped = 1
                    state.uncertain_commit_forwarded_requests = 1
                    state.provider_success_status = status
        if drop_success:
            payload = commit_state_unknown(
                "injected response loss after provider commit success"
            )
            self.send_payload(504, payload, "application/json")
            return
        self.send_payload(status, response_body, content_type)

    def log_message(self, _format, *_args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 19001), UncertainCommitProxy)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()

spark = (
    SparkSession.builder.appName("gda-spark-uncertain-commit-reconciliation")
    .master("local[2]")
    .config(
        "spark.sql.extensions",
        "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    )
    .config("spark.jars", "/opt/spark/jars-extra/iceberg-aws-bundle-1.6.1.jar")
    .config("spark.sql.catalog.rest", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.rest.type", "rest")
    .config("spark.sql.catalog.rest.uri", PROXY + "/iceberg")
    .config(
        "spark.sql.catalog.rest.io-impl",
        "org.apache.iceberg.aws.s3.S3FileIO",
    )
    .config("spark.sql.catalog.rest.s3.endpoint", OBJECT_STORE_ENDPOINT)
    .config("spark.sql.catalog.rest.s3.path-style-access", "true")
    .config(
        "spark.sql.catalog.rest.s3.access-key-id",
        os.environ["AWS_ACCESS_KEY_ID"],
    )
    .config(
        "spark.sql.catalog.rest.s3.secret-access-key",
        os.environ["AWS_SECRET_ACCESS_KEY"],
    )
    .config("spark.sql.catalog.rest.client.region", "us-east-1")
    .config("spark.sql.catalog.rest.cache-enabled", "false")
    .config("spark.sql.catalog.rest.rest.client.max-retries", "1")
    .config("spark.sql.catalog.rest.commit.retry.num-retries", "0")
    .config("spark.sql.catalog.rest.commit.retry.total-timeout-ms", "1000")
    .config("spark.sql.shuffle.partitions", "2")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("WARN")


def snapshots():
    return [
        {
            "snapshot_id": row["snapshot_id"],
            "parent_id": row["parent_id"],
            "operation": row["operation"],
        }
        for row in spark.sql(
            f"SELECT snapshot_id, parent_id, operation FROM {TABLE}.snapshots "
            "ORDER BY committed_at, snapshot_id"
        ).collect()
    ]


def rows():
    return [
        row["probe_id"]
        for row in spark.sql(f"SELECT probe_id FROM {TABLE} ORDER BY probe_id").collect()
    ]


def data_files():
    return sorted(
        row["file_path"]
        for row in spark.sql(f"SELECT file_path FROM {TABLE}.files").collect()
    )


try:
    initial_columns = spark.table(TABLE).columns
    initial_rows = rows()
    initial_snapshots = snapshots()
    if initial_columns != ["probe_id"] or initial_rows or initial_snapshots:
        raise RuntimeError("unexpected Gravitino-created table baseline")

    (
        spark.createDataFrame([(value,) for value in BASELINE_ROWS], ["probe_id"])
        .coalesce(1)
        .writeTo(TABLE)
        .append()
    )
    baseline_snapshots = snapshots()
    baseline_rows = rows()
    baseline_files = data_files()
    if (
        len(baseline_snapshots) != 1
        or baseline_rows != BASELINE_ROWS
        or len(baseline_files) != 1
    ):
        raise RuntimeError("baseline commit did not produce one visible snapshot")

    exception_type = None
    with state.lock:
        state.response_drop_armed = True
    try:
        (
            spark.createDataFrame([(UNCERTAIN_ROW,)], ["probe_id"])
            .coalesce(1)
            .writeTo(TABLE)
            .append()
        )
    except Exception as exc:
        exception_type = type(exc).__name__
    finally:
        with state.lock:
            state.response_drop_armed = False
    if exception_type is None:
        raise RuntimeError("post-forward response loss was not observed")

    spark.catalog.refreshTable(TABLE)
    reconciled_snapshots = snapshots()
    reconciled_rows = rows()
    reconciled_files = data_files()
    expected_rows = sorted(BASELINE_ROWS + [UNCERTAIN_ROW])
    if (
        len(reconciled_snapshots) != 2
        or reconciled_snapshots[1]["parent_id"]
        != reconciled_snapshots[0]["snapshot_id"]
        or [item["operation"] for item in reconciled_snapshots]
        != ["append", "append"]
        or reconciled_rows != expected_rows
        or len(reconciled_files) != 2
        or not all(path.startswith(DATA_PREFIX) for path in reconciled_files)
    ):
        raise RuntimeError("readback could not prove the uncertain commit outcome")

    with state.lock:
        proxy = {
            "forwarded_commit_requests": state.forwarded_commit_requests,
            "uncertain_commit_forwarded_requests": (
                state.uncertain_commit_forwarded_requests
            ),
            "provider_success_responses_dropped": (
                state.provider_success_responses_dropped
            ),
            "suppressed_duplicate_commit_requests": (
                state.suppressed_duplicate_commit_requests
            ),
            "provider_success_status": state.provider_success_status,
            "total_requests": state.total_requests,
            "injection_mode": "post_forward_success_response_drop_http_504",
            "provider_commit_forwarded": True,
            "loopback_only": True,
        }
    if (
        proxy["forwarded_commit_requests"] != 2
        or proxy["uncertain_commit_forwarded_requests"] != 1
        or proxy["provider_success_responses_dropped"] != 1
        or proxy["suppressed_duplicate_commit_requests"] != 1
        or proxy["provider_success_status"] != 200
    ):
        raise RuntimeError("uncertain commit proxy boundary did not match")

    result = {
        "schema": "gda.spark_uncertain_commit_reconciliation_probe_result.v1",
        "spark_version": spark.version,
        "iceberg_runtime": "1.6.1",
        "catalog_uri": PROXY + "/iceberg",
        "catalog_upstream": UPSTREAM + "/iceberg",
        "warehouse": WAREHOUSE,
        "object_store_endpoint": OBJECT_STORE_ENDPOINT,
        "file_io": "org.apache.iceberg.aws.s3.S3FileIO",
        "table": TABLE,
        "initial_columns": initial_columns,
        "initial_rows": initial_rows,
        "initial_snapshots": initial_snapshots,
        "baseline": {
            "rows": baseline_rows,
            "snapshots": baseline_snapshots,
            "data_file_paths": baseline_files,
        },
        "uncertain_attempt": {
            "exception_observed": True,
            "exception_type": exception_type,
            "logical_row": UNCERTAIN_ROW,
        },
        "reconciliation": {
            "decision": "committed_do_not_resubmit",
            "readback_attempts": 1,
            "write_resubmitted": False,
            "rows": reconciled_rows,
            "snapshots": reconciled_snapshots,
            "data_file_paths": reconciled_files,
        },
        "proxy": proxy,
        "provider_committed_response_loss_verified": True,
        "commit_outcome_readback_verified": True,
        "duplicate_resubmission_prevented": True,
        "single_visible_commit_verified": True,
        "object_store_data_files_verified": True,
        "material_recorded": False,
    }
    print("GDA_SPARK_COMMIT_FAILURE_RESULT=" + json.dumps(result, sort_keys=True))
finally:
    server.shutdown()
    server.server_close()
    spark.stop()

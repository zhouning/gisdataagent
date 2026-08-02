import java.net.URI;
import java.util.Objects;

import org.apache.flink.api.common.RuntimeExecutionMode;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.table.api.TableResult;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;
import org.apache.flink.util.CloseableIterator;

/** Append one real road while a Spark append is already in flight. */
public final class ChongqingOsmIcebergConcurrentAppendJob {
    private ChongqingOsmIcebergConcurrentAppendJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");
        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setRuntimeMode(RuntimeExecutionMode.BATCH);
        environment.setParallelism(1);
        StreamTableEnvironment tableEnvironment =
                StreamTableEnvironment.create(environment);
        tableEnvironment.executeSql(catalogDdl(options, catalogPassword));

        long baselineRows = scalarLong(
                tableEnvironment.executeSql("SELECT COUNT(*) FROM " + options.qualifiedTable));
        if (baselineRows != options.expectedBaselineRows) {
            throw new IllegalStateException("unexpected concurrent append baseline");
        }
        System.out.printf(
                "GDA_CONCURRENT_FLINK_BASELINE rows=%d token=%s%n",
                baselineRows,
                options.commitToken);

        TableResult insertion = tableEnvironment.executeSql(insertSql(options));
        insertion.await();
        long finalRows = scalarLong(
                tableEnvironment.executeSql("SELECT COUNT(*) FROM " + options.qualifiedTable));
        long matchingRows = scalarLong(
                tableEnvironment.executeSql(
                        "SELECT COUNT(*) FROM " + options.qualifiedTable
                                + " WHERE commit_token = "
                                + sqlString(options.commitToken)));
        if (finalRows != options.expectedBaselineRows + 1 || matchingRows != 1) {
            throw new IllegalStateException("Flink concurrent append did not reconcile");
        }
        System.out.printf(
                "GDA_CONCURRENT_FLINK_COMMITTED rows=%d matching=%d token=%s%n",
                finalRows,
                matchingRows,
                options.commitToken);
    }

    private static String catalogDdl(JobArguments options, String catalogPassword) {
        return "CREATE CATALOG lakehouse WITH ("
                + "'type' = 'iceberg', "
                + "'catalog-impl' = 'org.apache.iceberg.jdbc.JdbcCatalog', "
                + "'uri' = " + sqlString(options.catalogUri) + ", "
                + "'jdbc.user' = " + sqlString(options.catalogUser) + ", "
                + "'jdbc.password' = " + sqlString(catalogPassword) + ", "
                + "'warehouse' = " + sqlString(options.warehouseUri) + ", "
                + "'io-impl' = 'org.apache.iceberg.aws.s3.S3FileIO', "
                + "'s3.endpoint' = " + sqlString(options.endpointUrl) + ", "
                + "'s3.path-style-access' = 'true', "
                + "'client.region' = 'us-east-1'"
                + ")";
    }

    private static String insertSql(JobArguments options) {
        return "INSERT INTO " + options.qualifiedTable
                + " (road_id, revision, road_name_base64, geometry_sha256, "
                + "writer_engine, commit_token) VALUES ("
                + options.roadId + ", "
                + options.revision + ", "
                + sqlString(options.roadNameBase64) + ", "
                + sqlString(options.geometrySha256) + ", "
                + "'flink-1.19.3', "
                + sqlString(options.commitToken) + ")";
    }

    private static long scalarLong(TableResult result) throws Exception {
        try (CloseableIterator<Row> rows = result.collect()) {
            if (!rows.hasNext()) {
                throw new IllegalStateException("scalar query returned no row");
            }
            Object value = rows.next().getField(0);
            if (rows.hasNext() || !(value instanceof Number)) {
                throw new IllegalStateException("scalar query returned invalid content");
            }
            return ((Number) value).longValue();
        }
    }

    private static String sqlString(String value) {
        return "'" + value.replace("'", "''") + "'";
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("missing required environment variable " + name);
        }
        return value;
    }

    private static final class JobArguments {
        final String warehouseUri;
        final String endpointUrl;
        final String catalogUri;
        final String catalogUser;
        final String qualifiedTable;
        final long expectedBaselineRows;
        final long roadId;
        final int revision;
        final String roadNameBase64;
        final String geometrySha256;
        final String commitToken;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                long expectedBaselineRows,
                long roadId,
                int revision,
                String roadNameBase64,
                String geometrySha256,
                String commitToken) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.expectedBaselineRows = expectedBaselineRows;
            this.roadId = roadId;
            this.revision = revision;
            this.roadNameBase64 = validateToken(roadNameBase64, "road name");
            this.geometrySha256 = validateHash(geometrySha256, "geometry hash");
            this.commitToken = validateHash(commitToken, "commit token");
        }

        static JobArguments parse(String[] args) {
            long expected = Long.parseLong(value(args, "--expected-baseline-rows"));
            int revision = Integer.parseInt(value(args, "--revision"));
            if (expected != 3 || revision <= 0) {
                throw new IllegalArgumentException("unexpected concurrent acceptance bounds");
            }
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    expected,
                    Long.parseLong(value(args, "--road-id")),
                    revision,
                    value(args, "--road-name-base64"),
                    value(args, "--geometry-sha256"),
                    value(args, "--commit-token"));
        }

        private static String value(String[] args, String name) {
            for (int index = 0; index < args.length - 1; index++) {
                if (Objects.equals(name, args[index])) {
                    return args[index + 1];
                }
            }
            throw new IllegalArgumentException("missing required argument " + name);
        }

        private static String validateWarehouse(String value) {
            URI uri = URI.create(value);
            if (!"s3".equals(uri.getScheme())
                    || !"gis-agent-lakehouse".equals(uri.getHost())
                    || uri.getPath() == null
                    || !uri.getPath().startsWith("/acceptance/flink-iceberg/")) {
                throw new IllegalArgumentException("warehouse is outside acceptance");
            }
            return value;
        }

        private static String validateEndpoint(String value) {
            URI uri = URI.create(value);
            if (!"http".equals(uri.getScheme()) || !"minio".equals(uri.getHost())) {
                throw new IllegalArgumentException("unexpected object store endpoint");
            }
            return value;
        }

        private static String validateCatalogUri(String value) {
            if (!value.matches(
                    "jdbc:postgresql://gda-iceberg-pg-[0-9a-f]{10}:5432/iceberg_catalog")) {
                throw new IllegalArgumentException("unexpected Iceberg catalog URI");
            }
            return value;
        }

        private static String validateCatalogUser(String value) {
            if (!"iceberg_admin".equals(value)) {
                throw new IllegalArgumentException("unexpected Iceberg catalog user");
            }
            return value;
        }

        private static String validateTable(String value) {
            if (!value.matches("lakehouse\\.gda_interop_[0-9a-f]{10}\\.chongqing_osm_roads")) {
                throw new IllegalArgumentException("unsafe Iceberg table identifier");
            }
            return value;
        }

        private static String validateToken(String value, String name) {
            if (!value.matches("[A-Za-z0-9_=/+-]{1,256}")) {
                throw new IllegalArgumentException("invalid " + name);
            }
            return value;
        }

        private static String validateHash(String value, String name) {
            if (!value.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("invalid " + name);
            }
            return value;
        }
    }
}

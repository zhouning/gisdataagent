import java.net.URI;
import java.util.Objects;

import org.apache.flink.api.common.RuntimeExecutionMode;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.table.api.TableResult;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;
import org.apache.flink.util.CloseableIterator;

/** Read one Iceberg table after a Spark position delete using a single query job. */
public final class ChongqingOsmIcebergPositionDeleteReadJob {
    private ChongqingOsmIcebergPositionDeleteReadJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");
        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setRuntimeMode(RuntimeExecutionMode.BATCH);
        environment.setParallelism(1);
        StreamTableEnvironment tableEnvironment = StreamTableEnvironment.create(environment);
        tableEnvironment.executeSql(catalogDdl(options, catalogPassword));

        String query = "SELECT COUNT(*), "
                + "COALESCE(SUM(CASE WHEN road_id = " + options.targetRoadId
                + " THEN 1 ELSE 0 END), 0), "
                + "COUNT(DISTINCT road_id) FROM " + options.qualifiedTable;
        TableResult result = tableEnvironment.executeSql(query);
        long rows;
        long targetRows;
        long distinctRoads;
        try (CloseableIterator<Row> output = result.collect()) {
            if (!output.hasNext()) {
                throw new IllegalStateException("position delete query returned no row");
            }
            Row row = output.next();
            if (output.hasNext()) {
                throw new IllegalStateException("position delete query returned multiple rows");
            }
            rows = number(row.getField(0), "row count");
            targetRows = number(row.getField(1), "target count");
            distinctRoads = number(row.getField(2), "distinct road count");
        }
        if (rows != options.expectedRows || targetRows != 0 || distinctRoads != rows) {
            throw new IllegalStateException("Flink did not apply the Spark position delete");
        }
        System.out.printf(
                "GDA_POSITION_DELETE_FLINK_READ rows=%d target_rows=%d distinct_roads=%d "
                        + "target_road_id=%d%n",
                rows,
                targetRows,
                distinctRoads,
                options.targetRoadId);
    }

    private static long number(Object value, String name) {
        if (!(value instanceof Number)) {
            throw new IllegalStateException("invalid " + name);
        }
        return ((Number) value).longValue();
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
        final long targetRoadId;
        final long expectedRows;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                long targetRoadId,
                long expectedRows) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.targetRoadId = targetRoadId;
            this.expectedRows = expectedRows;
        }

        static JobArguments parse(String[] args) {
            long targetRoadId = Long.parseLong(value(args, "--target-road-id"));
            long expectedRows = Long.parseLong(value(args, "--expected-rows"));
            if (targetRoadId <= 0 || expectedRows != 2) {
                throw new IllegalArgumentException("unexpected position delete read bounds");
            }
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    targetRoadId,
                    expectedRows);
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
    }
}

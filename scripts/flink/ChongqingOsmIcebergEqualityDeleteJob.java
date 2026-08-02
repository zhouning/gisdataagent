import java.net.URI;
import java.util.Objects;

import org.apache.flink.api.common.RuntimeExecutionMode;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.Schema;
import org.apache.flink.table.api.Table;
import org.apache.flink.table.api.TableResult;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.table.connector.ChangelogMode;
import org.apache.flink.types.Row;
import org.apache.flink.types.RowKind;

/** Commit one equality-key delete into an Iceberg table created by Spark. */
public final class ChongqingOsmIcebergEqualityDeleteJob {
    private ChongqingOsmIcebergEqualityDeleteJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");
        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setRuntimeMode(RuntimeExecutionMode.STREAMING);
        environment.setParallelism(1);
        StreamTableEnvironment tableEnvironment = StreamTableEnvironment.create(environment);
        tableEnvironment.executeSql(catalogDdl(options, catalogPassword));

        Row delete = Row.ofKind(
                RowKind.DELETE,
                options.roadId,
                options.revision,
                options.roadNameBase64,
                options.geometrySha256,
                options.writerEngine,
                null);
        DataStream<Row> changelog = environment
                .fromElements(delete)
                .returns(
                        Types.ROW_NAMED(
                                new String[] {
                                    "road_id",
                                    "revision",
                                    "road_name_base64",
                                    "geometry_sha256",
                                    "writer_engine",
                                    "commit_token"
                                },
                                Types.LONG,
                                Types.INT,
                                Types.STRING,
                                Types.STRING,
                                Types.STRING,
                                Types.STRING));
        Schema schema = Schema.newBuilder()
                .column("road_id", DataTypes.BIGINT().notNull())
                .column("revision", DataTypes.INT().notNull())
                .column("road_name_base64", DataTypes.STRING().notNull())
                .column("geometry_sha256", DataTypes.STRING().notNull())
                .column("writer_engine", DataTypes.STRING().notNull())
                .column("commit_token", DataTypes.STRING())
                .primaryKey("road_id")
                .build();
        ChangelogMode deleteOnly = ChangelogMode.newBuilder()
                .addContainedKind(RowKind.DELETE)
                .build();
        Table deleteEvent = tableEnvironment.fromChangelogStream(changelog, schema, deleteOnly);
        tableEnvironment.createTemporaryView("gda_equality_delete_event", deleteEvent);

        System.out.printf(
                "GDA_EQUALITY_DELETE_FLINK_STARTED road_id=%d token=%s%n",
                options.roadId,
                options.commitToken);
        TableResult result = tableEnvironment.executeSql(
                "INSERT INTO " + options.qualifiedTable
                        + " SELECT road_id, revision, road_name_base64, geometry_sha256, "
                        + "writer_engine, commit_token FROM gda_equality_delete_event");
        result.await();
        System.out.printf(
                "GDA_EQUALITY_DELETE_FLINK_COMMITTED road_id=%d token=%s%n",
                options.roadId,
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
        final long roadId;
        final int revision;
        final String roadNameBase64;
        final String geometrySha256;
        final String writerEngine;
        final String commitToken;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                long roadId,
                int revision,
                String roadNameBase64,
                String geometrySha256,
                String writerEngine,
                String commitToken) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.roadId = roadId;
            this.revision = revision;
            this.roadNameBase64 = validateToken(roadNameBase64, "road name");
            this.geometrySha256 = validateHash(geometrySha256, "geometry hash");
            this.writerEngine = validateToken(writerEngine, "writer engine");
            this.commitToken = validateHash(commitToken, "commit token");
        }

        static JobArguments parse(String[] args) {
            long roadId = Long.parseLong(value(args, "--road-id"));
            int revision = Integer.parseInt(value(args, "--revision"));
            if (roadId <= 0 || revision != 1) {
                throw new IllegalArgumentException("unexpected equality delete bounds");
            }
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    roadId,
                    revision,
                    value(args, "--road-name-base64"),
                    value(args, "--geometry-sha256"),
                    value(args, "--writer-engine"),
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
            if (!value.matches("[A-Za-z0-9_.=/+-]{1,256}")) {
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

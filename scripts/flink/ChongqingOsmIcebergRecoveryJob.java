import java.io.BufferedReader;
import java.io.FileReader;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

import org.apache.flink.api.common.restartstrategy.RestartStrategies;
import org.apache.flink.api.common.state.CheckpointListener;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.time.Time;
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.runtime.state.FunctionInitializationContext;
import org.apache.flink.runtime.state.FunctionSnapshotContext;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.source.RichParallelSourceFunction;
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.Schema;
import org.apache.flink.table.api.Table;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;

/** Recover a checkpointed real-data stream into an Iceberg table without duplicates. */
public final class ChongqingOsmIcebergRecoveryJob {
    private static final TypeInformation<Row> ROW_TYPE = Types.ROW_NAMED(
            new String[] {
                "road_id",
                "revision",
                "road_name_base64",
                "geometry_sha256",
                "stream_event_id",
                "flink_commit_tag"
            },
            Types.LONG,
            Types.INT,
            Types.STRING,
            Types.STRING,
            Types.STRING,
            Types.STRING);

    private ChongqingOsmIcebergRecoveryJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");

        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setParallelism(1);
        environment.setRestartStrategy(
                RestartStrategies.fixedDelayRestart(1, Time.milliseconds(500)));
        environment.enableCheckpointing(300, CheckpointingMode.EXACTLY_ONCE);
        environment.getCheckpointConfig().setMinPauseBetweenCheckpoints(100);
        environment.getCheckpointConfig().setCheckpointTimeout(15_000);
        environment.getCheckpointConfig().setCheckpointStorage(options.checkpointUri);

        StreamTableEnvironment tableEnvironment =
                StreamTableEnvironment.create(environment);
        tableEnvironment.executeSql(catalogDdl(options, catalogPassword));
        tableEnvironment.executeSql(
                "ALTER TABLE " + options.qualifiedTable
                        + " ADD stream_event_id STRING");
        tableEnvironment.executeSql(
                "ALTER TABLE " + options.qualifiedTable
                        + " ADD flink_commit_tag STRING");

        DataStream<Row> changes = environment
                .addSource(
                        new CheckpointedRoadSource(
                                options.inputPath,
                                options.expectedRecords,
                                options.failAfterOffset))
                .returns(ROW_TYPE)
                .name("checkpointed-chongqing-osm-iceberg-source")
                .uid("checkpointed-chongqing-osm-iceberg-source");
        Schema schema = Schema.newBuilder()
                .column("road_id", DataTypes.BIGINT())
                .column("revision", DataTypes.INT())
                .column("road_name_base64", DataTypes.STRING())
                .column("geometry_sha256", DataTypes.STRING())
                .column("stream_event_id", DataTypes.STRING())
                .column("flink_commit_tag", DataTypes.STRING())
                .build();
        Table changeTable = tableEnvironment.fromDataStream(changes, schema);
        changeTable.executeInsert(options.qualifiedTable).await();
        System.out.printf(
                "GDA_ICEBERG_RECOVERY_JOB_COMPLETED records=%d%n",
                options.expectedRecords);
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

    private static final class CheckpointedRoadSource extends RichParallelSourceFunction<Row>
            implements org.apache.flink.streaming.api.checkpoint.CheckpointedFunction,
                    CheckpointListener {
        private final String inputPath;
        private final int expectedRecords;
        private final int failAfterOffset;
        private final Map<Long, Integer> checkpointOffsets = new ConcurrentHashMap<>();
        private transient ListState<Integer> offsetState;
        private volatile boolean running = true;
        private volatile long completedCheckpointId = -1;
        private volatile int completedOffset;
        private int offset;
        private boolean restored;

        CheckpointedRoadSource(String inputPath, int expectedRecords, int failAfterOffset) {
            this.inputPath = inputPath;
            this.expectedRecords = expectedRecords;
            this.failAfterOffset = failAfterOffset;
        }

        @Override
        public void open(Configuration parameters) throws Exception {
            super.open(parameters);
            System.out.printf(
                    "GDA_ICEBERG_SOURCE_OPEN attempt=%d restored=%s offset=%d%n",
                    getRuntimeContext().getAttemptNumber(), restored, offset);
        }

        @Override
        public void run(SourceContext<Row> context) throws Exception {
            List<Row> records = readRecords(inputPath);
            if (records.size() != expectedRecords) {
                throw new IllegalStateException("unexpected Iceberg recovery input size");
            }
            while (running && offset < records.size()) {
                if (getRuntimeContext().getAttemptNumber() == 0
                        && offset >= failAfterOffset) {
                    while (running && completedOffset < failAfterOffset) {
                        Thread.sleep(20);
                    }
                    if (running) {
                        System.out.printf(
                                "GDA_ICEBERG_INTENTIONAL_FAILURE checkpoint=%d offset=%d%n",
                                completedCheckpointId, offset);
                        throw new RuntimeException(
                                "intentional Iceberg failure after completed checkpoint");
                    }
                }
                synchronized (context.getCheckpointLock()) {
                    context.collect(records.get(offset));
                    offset += 1;
                }
                Thread.sleep(100);
            }
            while (running && completedOffset < records.size()) {
                Thread.sleep(20);
            }
            if (running) {
                System.out.printf("GDA_ICEBERG_SOURCE_FINISHED offset=%d%n", offset);
            }
        }

        @Override
        public void cancel() {
            running = false;
        }

        @Override
        public void snapshotState(FunctionSnapshotContext context) throws Exception {
            offsetState.clear();
            offsetState.add(offset);
            checkpointOffsets.put(context.getCheckpointId(), offset);
            System.out.printf(
                    "GDA_ICEBERG_CHECKPOINT_SNAPSHOT id=%d offset=%d%n",
                    context.getCheckpointId(), offset);
        }

        @Override
        public void initializeState(FunctionInitializationContext context) throws Exception {
            offsetState = context.getOperatorStateStore().getListState(
                    new ListStateDescriptor<>("iceberg-source-offset", Types.INT));
            restored = context.isRestored();
            offset = 0;
            if (restored) {
                for (Integer value : offsetState.get()) {
                    offset = value;
                }
                completedOffset = offset;
            }
        }

        @Override
        public void notifyCheckpointComplete(long checkpointId) {
            Integer snapshotOffset = checkpointOffsets.remove(checkpointId);
            if (snapshotOffset != null) {
                completedCheckpointId = checkpointId;
                completedOffset = Math.max(completedOffset, snapshotOffset);
                System.out.printf(
                        "GDA_ICEBERG_CHECKPOINT_COMPLETED id=%d offset=%d%n",
                        checkpointId, snapshotOffset);
            }
        }

        private static List<Row> readRecords(String path) throws Exception {
            List<Row> records = new ArrayList<>();
            try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isEmpty()) {
                        continue;
                    }
                    String[] fields = line.split("\\t", -1);
                    if (fields.length != 6) {
                        throw new IllegalArgumentException("invalid Iceberg recovery input row");
                    }
                    records.add(Row.of(
                            Long.parseLong(fields[0]),
                            Integer.parseInt(fields[1]),
                            fields[2],
                            fields[3],
                            fields[4],
                            fields[5]));
                }
            }
            return records;
        }
    }

    private static final class JobArguments {
        final String warehouseUri;
        final String endpointUrl;
        final String catalogUri;
        final String catalogUser;
        final String qualifiedTable;
        final String inputPath;
        final String checkpointUri;
        final int expectedRecords;
        final int failAfterOffset;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                String inputPath,
                String checkpointUri,
                int expectedRecords,
                int failAfterOffset) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.inputPath = validateWorkspacePath(inputPath, "events.tsv");
            this.checkpointUri = validateCheckpointUri(checkpointUri);
            this.expectedRecords = expectedRecords;
            this.failAfterOffset = failAfterOffset;
        }

        static JobArguments parse(String[] args) {
            int expected = Integer.parseInt(value(args, "--expected-records"));
            int failAfter = Integer.parseInt(value(args, "--fail-after-offset"));
            if (expected != 4 || failAfter != 2) {
                throw new IllegalArgumentException("unexpected recovery acceptance bounds");
            }
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    value(args, "--input"),
                    value(args, "--checkpoints"),
                    expected,
                    failAfter);
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
                throw new IllegalArgumentException("warehouse is outside the acceptance prefix");
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

        private static String validateWorkspacePath(String value, String suffix) {
            if (!value.matches(
                    "/workspace/\\.tmp/source-sync-certification/"
                            + "flink_iceberg_recovery_[0-9a-f]{10}/" + suffix)) {
                throw new IllegalArgumentException("unsafe workspace path");
            }
            return value;
        }

        private static String validateCheckpointUri(String value) {
            String prefix = "file:///workspace/.tmp/source-sync-certification/";
            if (!value.matches(
                    "file:///workspace/\\.tmp/source-sync-certification/"
                            + "flink_iceberg_recovery_[0-9a-f]{10}/checkpoints")) {
                throw new IllegalArgumentException("unsafe checkpoint URI");
            }
            if (!value.startsWith(prefix)) {
                throw new IllegalArgumentException("checkpoint escaped the workspace");
            }
            return value;
        }
    }
}

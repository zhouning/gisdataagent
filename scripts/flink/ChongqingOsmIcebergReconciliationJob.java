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
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.runtime.state.FunctionInitializationContext;
import org.apache.flink.runtime.state.FunctionSnapshotContext;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.source.RichParallelSourceFunction;
import org.apache.flink.table.api.DataTypes;
import org.apache.flink.table.api.Schema;
import org.apache.flink.table.api.Table;
import org.apache.flink.table.api.TableResult;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;

/** Exercise pre-checkpoint cancellation and acknowledged-loss recovery on Iceberg. */
public final class ChongqingOsmIcebergReconciliationJob {
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

    private ChongqingOsmIcebergReconciliationJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");

        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setParallelism(1);
        environment.setRestartStrategy(RestartStrategies.noRestart());
        environment.enableCheckpointing(
                options.cancelMode ? 60_000 : 300,
                CheckpointingMode.EXACTLY_ONCE);
        environment.getCheckpointConfig().setMinPauseBetweenCheckpoints(100);
        environment.getCheckpointConfig().setCheckpointTimeout(15_000);
        environment.getCheckpointConfig().setCheckpointStorage(options.checkpointUri);

        StreamTableEnvironment tableEnvironment =
                StreamTableEnvironment.create(environment);
        tableEnvironment.executeSql(catalogDdl(options, catalogPassword));

        DataStream<Row> changes = environment
                .addSource(
                        new ReconciliationRoadSource(
                                options.inputPath,
                                options.expectedRecords,
                                options.cancelMode,
                                options.commitToken))
                .returns(ROW_TYPE)
                .name("chongqing-osm-iceberg-reconciliation-source")
                .uid("chongqing-osm-iceberg-reconciliation-source");
        Schema schema = Schema.newBuilder()
                .column("road_id", DataTypes.BIGINT())
                .column("revision", DataTypes.INT())
                .column("road_name_base64", DataTypes.STRING())
                .column("geometry_sha256", DataTypes.STRING())
                .column("stream_event_id", DataTypes.STRING())
                .column("flink_commit_tag", DataTypes.STRING())
                .build();
        Table changeTable = tableEnvironment.fromDataStream(changes, schema);
        TableResult insertion = changeTable.executeInsert(options.qualifiedTable);
        if (options.cancelMode) {
            System.out.printf(
                    "GDA_ICEBERG_CANCEL_JOB_SUBMITTED token=%s%n",
                    options.commitToken);
            return;
        }
        insertion.await();
        System.out.printf(
                "GDA_ICEBERG_RECONCILIATION_JOB_COMPLETED token=%s records=%d%n",
                options.commitToken,
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

    private static final class ReconciliationRoadSource extends RichParallelSourceFunction<Row>
            implements org.apache.flink.streaming.api.checkpoint.CheckpointedFunction,
                    CheckpointListener {
        private final String inputPath;
        private final int expectedRecords;
        private final boolean cancelMode;
        private final String commitToken;
        private final Map<Long, Integer> checkpointOffsets = new ConcurrentHashMap<>();
        private transient ListState<Integer> offsetState;
        private volatile boolean running = true;
        private volatile int completedOffset;
        private int offset;

        ReconciliationRoadSource(
                String inputPath,
                int expectedRecords,
                boolean cancelMode,
                String commitToken) {
            this.inputPath = inputPath;
            this.expectedRecords = expectedRecords;
            this.cancelMode = cancelMode;
            this.commitToken = commitToken;
        }

        @Override
        public void run(SourceContext<Row> context) throws Exception {
            List<Row> records = readRecords(inputPath, commitToken);
            if (records.size() != expectedRecords) {
                throw new IllegalStateException("unexpected reconciliation input size");
            }
            while (running && offset < records.size()) {
                synchronized (context.getCheckpointLock()) {
                    context.collect(records.get(offset));
                    offset += 1;
                }
                Thread.sleep(50);
            }
            if (cancelMode && running) {
                System.out.printf(
                        "GDA_ICEBERG_CANCEL_READY token=%s offset=%d%n",
                        commitToken,
                        offset);
                while (running) {
                    Thread.sleep(20);
                }
                return;
            }
            while (running && completedOffset < records.size()) {
                Thread.sleep(20);
            }
            if (running) {
                System.out.printf(
                        "GDA_ICEBERG_COMMIT_SOURCE_FINISHED token=%s offset=%d%n",
                        commitToken,
                        offset);
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
                    "GDA_ICEBERG_RECONCILE_CHECKPOINT_SNAPSHOT token=%s id=%d offset=%d%n",
                    commitToken,
                    context.getCheckpointId(),
                    offset);
        }

        @Override
        public void initializeState(FunctionInitializationContext context) throws Exception {
            offsetState = context.getOperatorStateStore().getListState(
                    new ListStateDescriptor<>("iceberg-reconciliation-offset", Types.INT));
            offset = 0;
            for (Integer value : offsetState.get()) {
                offset = value;
            }
            completedOffset = offset;
        }

        @Override
        public void notifyCheckpointComplete(long checkpointId) {
            Integer snapshotOffset = checkpointOffsets.remove(checkpointId);
            if (snapshotOffset != null) {
                completedOffset = Math.max(completedOffset, snapshotOffset);
                System.out.printf(
                        "GDA_ICEBERG_RECONCILE_CHECKPOINT_COMPLETED token=%s id=%d offset=%d%n",
                        commitToken,
                        checkpointId,
                        snapshotOffset);
            }
        }

        private static List<Row> readRecords(String path, String commitToken) throws Exception {
            List<Row> records = new ArrayList<>();
            try (BufferedReader reader = new BufferedReader(new FileReader(path))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isEmpty()) {
                        continue;
                    }
                    String[] fields = line.split("\\t", -1);
                    if (fields.length != 6 || !Objects.equals(fields[5], commitToken)) {
                        throw new IllegalArgumentException(
                                "invalid Iceberg reconciliation input row");
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
        final String commitToken;
        final boolean cancelMode;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                String inputPath,
                String checkpointUri,
                int expectedRecords,
                String commitToken,
                boolean cancelMode) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.inputPath = validateWorkspacePath(inputPath, "events.tsv");
            this.checkpointUri = validateCheckpointUri(checkpointUri, cancelMode);
            this.expectedRecords = expectedRecords;
            this.commitToken = validateHash(commitToken);
            this.cancelMode = cancelMode;
        }

        static JobArguments parse(String[] args) {
            int expected = Integer.parseInt(value(args, "--expected-records"));
            String mode = value(args, "--mode");
            if (expected != 4 || !("cancel".equals(mode) || "commit".equals(mode))) {
                throw new IllegalArgumentException("unexpected reconciliation acceptance bounds");
            }
            boolean cancelMode = "cancel".equals(mode);
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    value(args, "--input"),
                    value(args, "--checkpoints"),
                    expected,
                    value(args, "--commit-token"),
                    cancelMode);
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
                            + "flink_iceberg_reconcile_[0-9a-f]{10}/" + suffix)) {
                throw new IllegalArgumentException("unsafe workspace path");
            }
            return value;
        }

        private static String validateCheckpointUri(String value, boolean cancelMode) {
            String suffix = cancelMode ? "checkpoints-cancel" : "checkpoints-commit";
            if (!value.matches(
                    "file:///workspace/\\.tmp/source-sync-certification/"
                            + "flink_iceberg_reconcile_[0-9a-f]{10}/" + suffix)) {
                throw new IllegalArgumentException("unsafe checkpoint URI");
            }
            return value;
        }

        private static String validateHash(String value) {
            if (!value.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("invalid commit token");
            }
            return value;
        }
    }
}

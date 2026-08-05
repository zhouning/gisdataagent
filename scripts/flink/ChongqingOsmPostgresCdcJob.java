import java.nio.charset.StandardCharsets;

import org.apache.flink.api.common.restartstrategy.RestartStrategies;
import org.apache.flink.api.common.serialization.SimpleStringEncoder;
import org.apache.flink.api.common.state.CheckpointListener;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.time.Time;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.connector.file.sink.FileSink;
import org.apache.flink.core.fs.Path;
import org.apache.flink.runtime.state.FunctionInitializationContext;
import org.apache.flink.runtime.state.FunctionSnapshotContext;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.ProcessFunction;
import org.apache.flink.streaming.api.functions.sink.filesystem.rollingpolicies.OnCheckpointRollingPolicy;
import org.apache.flink.table.api.Table;
import org.apache.flink.table.api.bridge.java.StreamTableEnvironment;
import org.apache.flink.types.Row;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

/** PostgreSQL logical-replication acceptance job using the official Flink CDC connector. */
public final class ChongqingOsmPostgresCdcJob {
    private static final OutputTag<String> QUARANTINE_TAG =
            new OutputTag<String>("invalid-cdc-records") {};

    private ChongqingOsmPostgresCdcJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String password = requiredEnvironment("CDC_PASSWORD");

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
        tableEnvironment.executeSql(sourceDdl(options, password));
        Table source = tableEnvironment.sqlQuery(
                "SELECT road_id, revision, road_name_base64, geometry_sha256 "
                        + "FROM osm_road_cdc_source");
        DataStream<Row> changelog = tableEnvironment.toChangelogStream(source);

        SingleOutputStreamOperator<String> accepted = changelog
                .process(new CheckpointFailureRouter(options.failAfterCount))
                .returns(Types.STRING)
                .name("checkpointed-postgres-cdc-changelog")
                .uid("checkpointed-postgres-cdc-changelog");
        accepted
                .sinkTo(
                        FileSink.forRowFormat(
                                        new Path(options.outputUri),
                                        new SimpleStringEncoder<String>(StandardCharsets.UTF_8.name()))
                                .withRollingPolicy(OnCheckpointRollingPolicy.build())
                                .build())
                .name("postgres-cdc-versioned-silver-files")
                .uid("postgres-cdc-versioned-silver-files");
        accepted
                .getSideOutput(QUARANTINE_TAG)
                .sinkTo(
                        FileSink.forRowFormat(
                                        new Path(options.quarantineOutputUri),
                                        new SimpleStringEncoder<String>(StandardCharsets.UTF_8.name()))
                                .withRollingPolicy(OnCheckpointRollingPolicy.build())
                                .build())
                .name("postgres-cdc-quarantine-files")
                .uid("postgres-cdc-quarantine-files");

        environment.execute("gda-chongqing-osm-postgres-cdc-certification");
    }

    private static String sourceDdl(JobArguments options, String password) {
        return "CREATE TABLE osm_road_cdc_source ("
                + "road_id BIGINT NOT NULL, "
                + "revision INT NOT NULL, "
                + "road_name_base64 STRING NOT NULL, "
                + "geometry_sha256 STRING NOT NULL, "
                + "PRIMARY KEY (road_id) NOT ENFORCED"
                + ") WITH ("
                + "'connector' = 'postgres-cdc', "
                + "'hostname' = '" + sqlLiteral(options.hostname) + "', "
                + "'port' = '5432', "
                + "'username' = '" + sqlLiteral(options.username) + "', "
                + "'password' = '" + sqlLiteral(password) + "', "
                + "'database-name' = '" + sqlLiteral(options.database) + "', "
                + "'schema-name' = '" + sqlLiteral(options.schema) + "', "
                + "'table-name' = '" + sqlLiteral(options.table) + "', "
                + "'slot.name' = '" + sqlLiteral(options.slotName) + "', "
                + "'decoding.plugin.name' = 'pgoutput', "
                + "'scan.startup.mode' = 'initial', "
                + "'scan.incremental.snapshot.enabled' = 'true', "
                + "'changelog-mode' = 'all', "
                + "'heartbeat.interval.ms' = '1000', "
                + "'debezium.publication.name' = '"
                + sqlLiteral(options.publicationName) + "', "
                + "'debezium.publication.autocreate.mode' = 'disabled'"
                + ")";
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("missing required environment variable " + name);
        }
        return value;
    }

    private static String sqlLiteral(String value) {
        if (!value.matches("[A-Za-z0-9_-]+")) {
            throw new IllegalArgumentException("unsafe SQL configuration value");
        }
        return value;
    }

    private static final class CheckpointFailureRouter extends ProcessFunction<Row, String>
            implements org.apache.flink.streaming.api.checkpoint.CheckpointedFunction,
                    CheckpointListener {
        private final int failAfterCount;
        private transient ListState<Integer> countState;
        private volatile long completedCheckpointId = -1;
        private int processedCount;
        private boolean restored;

        CheckpointFailureRouter(int failAfterCount) {
            this.failAfterCount = failAfterCount;
        }

        @Override
        public void open(Configuration parameters) throws Exception {
            super.open(parameters);
            System.out.printf(
                    "GDA_CDC_PROCESS_OPEN attempt=%d restored=%s count=%d%n",
                    getRuntimeContext().getAttemptNumber(), restored, processedCount);
        }

        @Override
        public void processElement(
                Row row,
                ProcessFunction<Row, String>.Context context,
                Collector<String> output) {
            processedCount += 1;
            String encoded = String.join(
                    "\t",
                    row.getKind().shortString(),
                    String.valueOf(row.getField(0)),
                    String.valueOf(row.getField(1)),
                    String.valueOf(row.getField(2)),
                    String.valueOf(row.getField(3)));
            if (getRuntimeContext().getAttemptNumber() == 0
                    && processedCount >= failAfterCount
                    && completedCheckpointId >= 0) {
                System.out.printf(
                        "GDA_CDC_INTENTIONAL_FAILURE checkpoint=%d count=%d%n",
                        completedCheckpointId, processedCount);
                throw new RuntimeException("intentional CDC failure after completed checkpoint");
            }
            if (String.valueOf(row.getField(3)).matches("[0-9a-f]{64}")) {
                output.collect(encoded);
            } else {
                context.output(
                        QUARANTINE_TAG,
                        "invalid_geometry_sha256\t" + encoded);
            }
        }

        @Override
        public void snapshotState(FunctionSnapshotContext context) throws Exception {
            countState.clear();
            countState.add(processedCount);
            System.out.printf(
                    "GDA_CDC_CHECKPOINT_SNAPSHOT id=%d count=%d%n",
                    context.getCheckpointId(), processedCount);
        }

        @Override
        public void initializeState(FunctionInitializationContext context) throws Exception {
            countState = context.getOperatorStateStore().getListState(
                    new ListStateDescriptor<>("processed-change-count", Types.INT));
            restored = context.isRestored();
            processedCount = 0;
            if (restored) {
                for (Integer value : countState.get()) {
                    processedCount = value;
                }
            }
        }

        @Override
        public void notifyCheckpointComplete(long checkpointId) {
            completedCheckpointId = checkpointId;
            System.out.printf(
                    "GDA_CDC_CHECKPOINT_COMPLETED id=%d count=%d%n",
                    checkpointId, processedCount);
        }
    }

    private static final class JobArguments {
        final String hostname;
        final String username;
        final String database;
        final String schema;
        final String table;
        final String slotName;
        final String publicationName;
        final String checkpointUri;
        final String outputUri;
        final String quarantineOutputUri;
        final int failAfterCount;

        private JobArguments(
                String hostname,
                String username,
                String database,
                String schema,
                String table,
                String slotName,
                String publicationName,
                String checkpointUri,
                String outputUri,
                String quarantineOutputUri,
                int failAfterCount) {
            this.hostname = hostname;
            this.username = username;
            this.database = database;
            this.schema = schema;
            this.table = table;
            this.slotName = slotName;
            this.publicationName = publicationName;
            this.checkpointUri = checkpointUri;
            this.outputUri = outputUri;
            this.quarantineOutputUri = quarantineOutputUri;
            this.failAfterCount = failAfterCount;
        }

        static JobArguments parse(String[] args) {
            int failAfter = Integer.parseInt(value(args, "--fail-after-count"));
            if (failAfter <= 0) {
                throw new IllegalArgumentException("failure count must be positive");
            }
            return new JobArguments(
                    value(args, "--hostname"),
                    value(args, "--username"),
                    value(args, "--database"),
                    value(args, "--schema"),
                    value(args, "--table"),
                    value(args, "--slot-name"),
                    value(args, "--publication-name"),
                    value(args, "--checkpoints"),
                    value(args, "--output"),
                    value(args, "--quarantine-output"),
                    failAfter);
        }

        private static String value(String[] args, String name) {
            for (int index = 0; index < args.length - 1; index++) {
                if (name.equals(args[index])) {
                    return args[index + 1];
                }
            }
            throw new IllegalArgumentException("missing required argument " + name);
        }
    }
}

import java.io.BufferedReader;
import java.io.FileReader;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

import org.apache.flink.api.common.eventtime.SerializableTimestampAssigner;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.restartstrategy.RestartStrategies;
import org.apache.flink.api.common.serialization.SimpleStringEncoder;
import org.apache.flink.api.common.state.CheckpointListener;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.state.MapState;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.time.Time;
import org.apache.flink.api.common.typeinfo.TypeInformation;
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
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.streaming.api.functions.source.RichParallelSourceFunction;
import org.apache.flink.streaming.api.functions.source.SourceFunction;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

/**
 * Bounded acceptance job for event-time, recovery and exactly-once file commits.
 *
 * <p>The input is an ASCII TSV event slice derived from the governed Chongqing
 * OSM road product. The source checkpoints its byte-independent event offset,
 * deliberately fails once after a completed checkpoint, and resumes from that
 * checkpoint. Accepted changelog records and rejected late/duplicate records
 * are committed by Flink's FileSink.
 */
public final class ChongqingOsmEventStreamJob {
    private static final OutputTag<String> REJECTED_EVENTS =
            new OutputTag<String>("rejected-events", Types.STRING);

    private ChongqingOsmEventStreamJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setParallelism(1);
        environment.setRestartStrategy(
                RestartStrategies.fixedDelayRestart(1, Time.milliseconds(500)));
        environment.enableCheckpointing(300, CheckpointingMode.EXACTLY_ONCE);
        environment.getCheckpointConfig().setMinPauseBetweenCheckpoints(100);
        environment.getCheckpointConfig().setCheckpointTimeout(10_000);
        environment.getCheckpointConfig().setCheckpointStorage(options.checkpointUri);
        environment.getConfig().setAutoWatermarkInterval(100);

        DataStream<RoadEvent> source = environment
                .addSource(new CheckpointedEventSource(options.inputPath, options.failAfterOffset))
                .name("checkpointed-chongqing-osm-event-source")
                .uid("checkpointed-chongqing-osm-event-source")
                .assignTimestampsAndWatermarks(
                        WatermarkStrategy
                                .<RoadEvent>forBoundedOutOfOrderness(
                                        Duration.ofMillis(options.outOfOrdernessMs))
                                .withTimestampAssigner(
                                        (SerializableTimestampAssigner<RoadEvent>)
                                                (event, previousTimestamp) -> event.eventTimeMs))
                .name("chongqing-osm-event-time-watermarks")
                .uid("chongqing-osm-event-time-watermarks");

        SingleOutputStreamOperator<String> accepted = source
                .keyBy(event -> event.roadId)
                .process(new EventTimeChangelog())
                .name("event-time-dedupe-and-late-routing")
                .uid("event-time-dedupe-and-late-routing");

        accepted
                .sinkTo(
                        FileSink.forRowFormat(
                                        new Path(options.acceptedOutputUri),
                                        new SimpleStringEncoder<String>("UTF-8"))
                                .build())
                .name("versioned-bronze-accepted-files")
                .uid("versioned-bronze-accepted-files");

        accepted
                .getSideOutput(REJECTED_EVENTS)
                .sinkTo(
                        FileSink.forRowFormat(
                                        new Path(options.rejectedOutputUri),
                                        new SimpleStringEncoder<String>("UTF-8"))
                                .build())
                .name("versioned-bronze-rejected-files")
                .uid("versioned-bronze-rejected-files");

        environment.execute("gda-chongqing-osm-event-stream-certification");
        System.out.println("GDA_JOB_COMPLETED status=success");
    }

    public static final class RoadEvent {
        public String eventId;
        public String roadId;
        public String operation;
        public long eventTimeMs;
        public String roadNameBase64;
        public String geometrySha256;

        public RoadEvent() {}

        static RoadEvent parse(String line) {
            String[] fields = line.split("\\t", -1);
            if (fields.length != 6) {
                throw new IllegalArgumentException("event row must contain six TSV fields");
            }
            RoadEvent event = new RoadEvent();
            event.eventId = fields[0];
            event.roadId = fields[1];
            event.operation = fields[2];
            event.eventTimeMs = Long.parseLong(fields[3]);
            event.roadNameBase64 = fields[4];
            event.geometrySha256 = fields[5];
            if (!("insert".equals(event.operation)
                    || "update".equals(event.operation)
                    || "delete".equals(event.operation))) {
                throw new IllegalArgumentException("unsupported event operation");
            }
            return event;
        }

        String toTsv() {
            return String.join(
                    "\t",
                    eventId,
                    roadId,
                    operation,
                    Long.toString(eventTimeMs),
                    roadNameBase64,
                    geometrySha256);
        }
    }

    private static final class CheckpointedEventSource
            extends RichParallelSourceFunction<RoadEvent>
            implements org.apache.flink.streaming.api.checkpoint.CheckpointedFunction,
                    CheckpointListener {
        private final String inputPath;
        private final int failAfterOffset;
        private volatile boolean running = true;
        private volatile long completedCheckpointId = -1;
        private transient ListState<Integer> offsetState;
        private transient List<RoadEvent> events;
        private int nextOffset;
        private boolean restored;

        CheckpointedEventSource(String inputPath, int failAfterOffset) {
            this.inputPath = inputPath;
            this.failAfterOffset = failAfterOffset;
        }

        @Override
        public void open(Configuration parameters) throws Exception {
            super.open(parameters);
            events = new ArrayList<>();
            try (BufferedReader reader = new BufferedReader(new FileReader(inputPath))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.isEmpty()) {
                        events.add(RoadEvent.parse(line));
                    }
                }
            }
            System.out.printf(
                    "GDA_SOURCE_OPEN attempt=%d restored=%s offset=%d events=%d%n",
                    getRuntimeContext().getAttemptNumber(), restored, nextOffset, events.size());
        }

        @Override
        public void run(SourceFunction.SourceContext<RoadEvent> context) throws Exception {
            while (running && nextOffset < events.size()) {
                synchronized (context.getCheckpointLock()) {
                    context.collect(events.get(nextOffset));
                    nextOffset += 1;
                }
                Thread.sleep(350);
                if (getRuntimeContext().getAttemptNumber() == 0
                        && nextOffset >= failAfterOffset
                        && completedCheckpointId >= 0) {
                    System.out.printf(
                            "GDA_INTENTIONAL_FAILURE checkpoint=%d offset=%d%n",
                            completedCheckpointId, nextOffset);
                    throw new RuntimeException("intentional failure after completed checkpoint");
                }
            }
        }

        @Override
        public void cancel() {
            running = false;
        }

        @Override
        public void snapshotState(FunctionSnapshotContext context) throws Exception {
            offsetState.clear();
            offsetState.add(nextOffset);
            System.out.printf(
                    "GDA_CHECKPOINT_SNAPSHOT id=%d offset=%d%n",
                    context.getCheckpointId(), nextOffset);
        }

        @Override
        public void initializeState(FunctionInitializationContext context) throws Exception {
            offsetState = context.getOperatorStateStore().getListState(
                    new ListStateDescriptor<>("source-offset", Types.INT));
            restored = context.isRestored();
            nextOffset = 0;
            if (restored) {
                for (Integer value : offsetState.get()) {
                    nextOffset = value;
                }
            }
        }

        @Override
        public void notifyCheckpointComplete(long checkpointId) {
            completedCheckpointId = checkpointId;
            System.out.printf(
                    "GDA_CHECKPOINT_COMPLETED id=%d offset=%d%n",
                    checkpointId, nextOffset);
        }
    }

    private static final class EventTimeChangelog
            extends KeyedProcessFunction<String, RoadEvent, String> {
        private transient MapState<String, Boolean> seenEventIds;
        private transient MapState<Long, RoadEvent> pendingByTimestamp;

        @Override
        public void open(Configuration parameters) throws Exception {
            seenEventIds = getRuntimeContext().getMapState(
                    new MapStateDescriptor<>("seen-event-ids", Types.STRING, Types.BOOLEAN));
            pendingByTimestamp = getRuntimeContext().getMapState(
                    new MapStateDescriptor<>(
                            "pending-events",
                            Types.LONG,
                            TypeInformation.of(RoadEvent.class)));
        }

        @Override
        public void processElement(
                RoadEvent event,
                Context context,
                Collector<String> output) throws Exception {
            if (seenEventIds.contains(event.eventId)) {
                context.output(REJECTED_EVENTS, "duplicate\t" + event.toTsv());
                return;
            }
            seenEventIds.put(event.eventId, true);
            Long timestamp = context.timestamp();
            if (timestamp == null) {
                throw new IllegalStateException("event timestamp was not assigned");
            }
            if (timestamp <= context.timerService().currentWatermark()) {
                context.output(REJECTED_EVENTS, "late\t" + event.toTsv());
                return;
            }
            pendingByTimestamp.put(timestamp, event);
            context.timerService().registerEventTimeTimer(timestamp);
        }

        @Override
        public void onTimer(long timestamp, OnTimerContext context, Collector<String> output)
                throws Exception {
            RoadEvent event = pendingByTimestamp.get(timestamp);
            if (event != null) {
                output.collect(event.toTsv());
                pendingByTimestamp.remove(timestamp);
            }
        }
    }

    private static final class JobArguments {
        final String inputPath;
        final String checkpointUri;
        final String acceptedOutputUri;
        final String rejectedOutputUri;
        final long outOfOrdernessMs;
        final int failAfterOffset;

        private JobArguments(
                String inputPath,
                String checkpointUri,
                String acceptedOutputUri,
                String rejectedOutputUri,
                long outOfOrdernessMs,
                int failAfterOffset) {
            this.inputPath = inputPath;
            this.checkpointUri = checkpointUri;
            this.acceptedOutputUri = acceptedOutputUri;
            this.rejectedOutputUri = rejectedOutputUri;
            this.outOfOrdernessMs = outOfOrdernessMs;
            this.failAfterOffset = failAfterOffset;
        }

        static JobArguments parse(String[] args) {
            String input = value(args, "--input");
            String checkpoints = value(args, "--checkpoints");
            String accepted = value(args, "--accepted-output");
            String rejected = value(args, "--rejected-output");
            long outOfOrderness = Long.parseLong(value(args, "--out-of-orderness-ms"));
            int failAfter = Integer.parseInt(value(args, "--fail-after-offset"));
            if (outOfOrderness <= 0 || failAfter <= 0) {
                throw new IllegalArgumentException("timing and failure offsets must be positive");
            }
            return new JobArguments(
                    input, checkpoints, accepted, rejected, outOfOrderness, failAfter);
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

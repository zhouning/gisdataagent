import java.io.Serializable;
import java.net.URI;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;

import org.apache.flink.api.common.RuntimeExecutionMode;
import org.apache.flink.api.common.restartstrategy.RestartStrategies;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.api.common.functions.RichMapFunction;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.util.CloseableIterator;
import org.apache.iceberg.DeleteFile;
import org.apache.iceberg.FileFormat;
import org.apache.iceberg.RowDelta;
import org.apache.iceberg.Snapshot;
import org.apache.iceberg.Table;
import org.apache.iceberg.catalog.TableIdentifier;
import org.apache.iceberg.data.GenericAppenderFactory;
import org.apache.iceberg.data.Record;
import org.apache.iceberg.deletes.PositionDelete;
import org.apache.iceberg.deletes.PositionDeleteWriter;
import org.apache.iceberg.expressions.Expressions;
import org.apache.iceberg.io.OutputFileFactory;
import org.apache.iceberg.jdbc.JdbcCatalog;

/** Commit one position delete from a single non-restarting Flink task. */
public final class ChongqingOsmIcebergPositionDeleteWriteJob {
    private ChongqingOsmIcebergPositionDeleteWriteJob() {}

    public static void main(String[] args) throws Exception {
        JobArguments options = JobArguments.parse(args);
        String catalogPassword = requiredEnvironment("ICEBERG_CATALOG_PASSWORD");
        StreamExecutionEnvironment environment =
                StreamExecutionEnvironment.getExecutionEnvironment();
        environment.setRuntimeMode(RuntimeExecutionMode.BATCH);
        environment.setParallelism(1);
        environment.setRestartStrategy(RestartStrategies.noRestart());

        try (CloseableIterator<String> output = environment
                .fromElements(1L)
                .map(new PositionDeleteCommit(options, catalogPassword))
                .returns(Types.STRING)
                .setParallelism(1)
                .executeAndCollect()) {
            if (!output.hasNext()) {
                throw new IllegalStateException("position delete task returned no evidence");
            }
            String marker = output.next();
            if (output.hasNext()) {
                throw new IllegalStateException("position delete task returned duplicate evidence");
            }
            System.out.println(marker);
        }
    }

    private static final class PositionDeleteCommit extends RichMapFunction<Long, String> {
        private static final long serialVersionUID = 1L;

        private final JobArguments options;
        private final String catalogPassword;

        PositionDeleteCommit(JobArguments options, String catalogPassword) {
            this.options = options;
            this.catalogPassword = catalogPassword;
        }

        @Override
        public String map(Long ignored) throws Exception {
            JdbcCatalog catalog = new JdbcCatalog();
            catalog.initialize("lakehouse", catalogProperties(options, catalogPassword));
            try {
                Table table = catalog.loadTable(
                        TableIdentifier.parse(options.icebergTableIdentifier()));
                table.refresh();
                Snapshot baseline = table.currentSnapshot();
                if (baseline == null || baseline.snapshotId() != options.baselineSnapshotId) {
                    throw new IllegalStateException("position delete baseline snapshot changed");
                }
                if (!table.spec().isUnpartitioned()) {
                    throw new IllegalStateException("position delete requires unpartitioned table");
                }

                GenericAppenderFactory appenderFactory = new GenericAppenderFactory(
                        table.schema(), table.spec(), null, null, null);
                appenderFactory.setAll(table.properties());
                OutputFileFactory outputFactory = OutputFileFactory
                        .builderFor(table, 0, 0)
                        .operationId(options.commitToken)
                        .format(FileFormat.PARQUET)
                        .build();
                PositionDeleteWriter<Record> writer = appenderFactory.newPosDeleteWriter(
                        outputFactory.newOutputFile(), FileFormat.PARQUET, null);
                DeleteFile deleteFile;
                try (PositionDeleteWriter<Record> closeable = writer) {
                    closeable.write(PositionDelete.<Record>create().set(
                            options.dataFilePath, options.rowPosition));
                }
                deleteFile = writer.toDeleteFile();

                RowDelta delta = table.newRowDelta()
                        .addDeletes(deleteFile)
                        .validateFromSnapshot(options.baselineSnapshotId)
                        .validateDataFilesExist(Collections.singleton(options.dataFilePath))
                        .validateDeletedFiles()
                        .conflictDetectionFilter(
                                Expressions.equal("road_id", options.targetRoadId))
                        .validateNoConflictingDataFiles()
                        .validateNoConflictingDeleteFiles()
                        .set("gda.commit-token", options.commitToken)
                        .set("gda.operation", "flink-position-delete");
                delta.commit();
                table.refresh();
                Snapshot committed = table.currentSnapshot();
                if (committed == null
                        || committed.parentId() == null
                        || committed.parentId() != options.baselineSnapshotId
                        || !"delete".equals(committed.operation())) {
                    throw new IllegalStateException("position delete snapshot is not baseline child");
                }
                return String.format(
                        "GDA_POSITION_DELETE_FLINK_COMMITTED snapshot_id=%d "
                                + "delete_file=%s data_file=%s position=%d "
                                + "target_road_id=%d token=%s",
                        committed.snapshotId(),
                        deleteFile.path(),
                        options.dataFilePath,
                        options.rowPosition,
                        options.targetRoadId,
                        options.commitToken);
            } finally {
                catalog.close();
            }
        }
    }

    private static Map<String, String> catalogProperties(
            JobArguments options, String catalogPassword) {
        Map<String, String> properties = new HashMap<>();
        properties.put("uri", options.catalogUri);
        properties.put("jdbc.user", options.catalogUser);
        properties.put("jdbc.password", catalogPassword);
        properties.put("warehouse", options.warehouseUri);
        properties.put("io-impl", "org.apache.iceberg.aws.s3.S3FileIO");
        properties.put("s3.endpoint", options.endpointUrl);
        properties.put("s3.path-style-access", "true");
        properties.put("client.region", "us-east-1");
        return properties;
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("missing required environment variable " + name);
        }
        return value;
    }

    private static final class JobArguments implements Serializable {
        private static final long serialVersionUID = 1L;

        final String warehouseUri;
        final String endpointUrl;
        final String catalogUri;
        final String catalogUser;
        final String qualifiedTable;
        final long baselineSnapshotId;
        final String dataFilePath;
        final long rowPosition;
        final long targetRoadId;
        final String commitToken;

        private JobArguments(
                String warehouseUri,
                String endpointUrl,
                String catalogUri,
                String catalogUser,
                String qualifiedTable,
                long baselineSnapshotId,
                String dataFilePath,
                long rowPosition,
                long targetRoadId,
                String commitToken) {
            this.warehouseUri = validateWarehouse(warehouseUri);
            this.endpointUrl = validateEndpoint(endpointUrl);
            this.catalogUri = validateCatalogUri(catalogUri);
            this.catalogUser = validateCatalogUser(catalogUser);
            this.qualifiedTable = validateTable(qualifiedTable);
            this.baselineSnapshotId = baselineSnapshotId;
            this.dataFilePath = validateDataFile(dataFilePath, warehouseUri);
            this.rowPosition = rowPosition;
            this.targetRoadId = targetRoadId;
            this.commitToken = validateHash(commitToken, "commit token");
            if (baselineSnapshotId <= 0 || rowPosition < 0 || targetRoadId <= 0) {
                throw new IllegalArgumentException("unexpected position delete bounds");
            }
        }

        static JobArguments parse(String[] args) {
            return new JobArguments(
                    value(args, "--warehouse-uri"),
                    value(args, "--endpoint-url"),
                    value(args, "--catalog-uri"),
                    value(args, "--catalog-user"),
                    value(args, "--table"),
                    Long.parseLong(value(args, "--baseline-snapshot-id")),
                    value(args, "--data-file-path"),
                    Long.parseLong(value(args, "--row-position")),
                    Long.parseLong(value(args, "--target-road-id")),
                    value(args, "--commit-token"));
        }

        String icebergTableIdentifier() {
            return qualifiedTable.substring("lakehouse.".length());
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

        private static String validateDataFile(String value, String warehouseUri) {
            URI uri = URI.create(value);
            String warehousePrefix = warehouseUri + "/";
            if (!"s3".equals(uri.getScheme())
                    || !"gis-agent-lakehouse".equals(uri.getHost())
                    || !value.startsWith(warehousePrefix)
                    || !value.endsWith(".parquet")) {
                throw new IllegalArgumentException("data file is outside acceptance table");
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

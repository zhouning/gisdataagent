# Windows 离线材料目录

这个目录是联网 staging 机的输入，不是生产主机的下载目录。构建器只从这里读取
已经核验过的安装介质、Windows x64 wheel 和模型，不会联网，也不会调用 Docker。

推荐目录：

```text
vendor/
  python/python-3.11.11-amd64.exe
  wheelhouse/core/*.whl
  wheelhouse/production/*.whl
  middleware/postgresql/postgresql-16.*-windows-x64.exe
  middleware/postgis/postgis-bundle-pg16-3.*-x64.exe
  middleware/pgvector/pgvector-pg16-windows-x64.zip or extracted vector.dll/vector.control/vector--*.sql
  middleware/minio/minio.exe + mc.exe
  middleware/java/OpenJDK17U-jre_x64_windows_hotspot_*.msi
  middleware/jena/apache-jena-*.zip
  middleware/fuseki/apache-jena-fuseki-*.zip
  middleware/ollama/OllamaSetup.exe
  models/ollama/gemma4-26b/Modelfile + model weights
  models/embedding/nomic-embed-text-v2-moe/Modelfile + model weights
  paper9/source/* or paper9/farmland_mpc-*.whl
  paper9/wheelhouse/*.whl
  paper9/models/...
  monitoring/prometheus/prometheus-*.windows-amd64.zip
  monitoring/grafana/grafana-*.windows-amd64.zip
```

文件名允许带补丁版本，`bundle-manifest.json` 中的 glob 要求每项恰好匹配一个安装介质。
pgvector ZIP 必须在压缩包内包含 `vector.dll`、`vector.control` 和至少一个
`vector--*.sql`；安装器会在现场解压并复制到 PostgreSQL 的 `lib`/`share\extension`。
构建前要从官方发布页或项目批准的制品库取得文件，并把供应商校验值写入 staging 记录；
最终 ZIP 中的 `manifest.json` 和 `SHA256SUMS` 是安装时唯一的完整性依据。

构建器不会替你下载软件，也不会把 macOS wheel 当成 Windows wheel。没有真实的 Windows
x64 wheel、PostGIS 扩展、模型权重或 Paper9 制品时，构建会失败并列出缺口。

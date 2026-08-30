# Design Document Regeneration Inventory

- Generated: `2026-07-15T06:00:18.510631+00:00`
- Working directory: `/Users/zhouning/gisdataagent`

## Existing DOCX

- Path: `docs/semantic_fusion_engine_technical_spec.docx`
- Exists: `True`
- Size bytes: `43035`
- Headings: `12`
- Tables: `5`
- Images: `0`
- Tracked insertions/deletions: `0` / `0`
  - 一、总体架构：7 阶段流水线 (`heading 1`)
  - 二、10 种融合策略 (`heading 1`)
  - 三、4 层渐进式语义字段匹配（核心创新） (`heading 1`)
  - Layer 1 — 精确匹配 (`heading 2`)
  - Layer 1.5 — 本体推理匹配（opt-in） (`heading 2`)
  - Layer 2 — 等价组匹配 (`heading 2`)
  - Layer 2.5 — 两条可选路径 (`heading 2`)
  - Layer 3 — 单位感知匹配 (`heading 2`)
  - Layer 4 — 分词模糊匹配 (`heading 2`)
  - 四、10 项融合质量验证（S7 阶段详情） (`heading 1`)
  - 五、v2.0 增强模块 (`heading 1`)
  - 六、关键数字摘要 (`heading 1`)

## Code Roots

### `/Users/zhouning/gisdataagent`

- Exists: `True`
- Git commit: `1421e005b227524ce35d537688a140bd2d8d16e7`
- Files: `113943`
- Top extensions: `{'.py': 40814, '.md': 37079, '.json': 7443, '.npy': 6802, '.png': 4467, '.csv': 3242, '.tsx': 2756, '.sql': 2470, '.yaml': 2007, '.dita': 858, '.txt': 556, '[no extension]': 445, '.pdf': 397, '.docx': 353, '.svg': 338, '.xml': 338, '.sh': 286, '.tif': 280, '.geojson': 253, '.ts': 237, '.yml': 208, '.html': 198, '.zip': 184, '.pptx': 107, '.jsonl': 105, '.toml': 105, '.dbf': 90, '.prj': 88, '.shp': 88, '.shx': 88, '.atx': 85, '.js': 79, '.pt': 78, '.cpg': 53, '.ditamap': 52, '.example': 52, '.dot': 44, '.gdbtable': 41, '.gdbtablx': 41, '.gdbindexes': 36}`
- Marker files: `[{'path': 'requirements.txt', 'kind': 'python'}, {'path': 'Dockerfile', 'kind': 'docker'}, {'path': 'pyproject.toml', 'kind': 'python'}, {'path': 'docker-compose.yml', 'kind': 'docker-compose'}, {'path': 'docker/mmfe-spark-runtime/Dockerfile', 'kind': 'docker'}, {'path': 'docker/postgis-pgvector/Dockerfile', 'kind': 'docker'}, {'path': 'frontend/package.json', 'kind': 'node'}, {'path': 'k8s/overlays/local-kind/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'k8s/overlays/docker-desktop/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'k8s/base/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'gis-skill-sdk/pyproject.toml', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/blender-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/qgis-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/arcgis-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/reference-data/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/reference-data/Dockerfile', 'kind': 'docker'}, {'path': 'subsystems/cad-parser/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/cad-parser/Dockerfile', 'kind': 'docker'}, {'path': 'subsystems/cv-service/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/cv-service/Dockerfile', 'kind': 'docker'}]`

## EA Artifacts

## Additional Design Inputs (V1.3 Refresh)

- `docs/reports/gis-data-agent-brain-vs-palantir-objective-comparison-2026-07-15.md`：Operational Ontology、动态安全、对象行动和 typed consumption benchmark。
- `docs/reports/gis-data-agent-heavy-ontology-production-architecture-2026-07-15.md`：用户要求形成的企业级重型本体条件目标架构。
- Repository dependency/deployment search on 2026-07-15：未发现专用 RDF/SHACL/Fuseki、OPA/Cedar、Kafka/Redpanda Ontology Platform 的生产配置；相关内容按 target design / `needs-owner-input` 处理。

## Recommended Next Steps

1. Convert binary EA repositories to XMI/XML exports when detailed model parsing is needed.
2. Build an evidence pack from code, schemas, configs, EA elements, and legacy-doc claims.
3. Audit unsupported and conflicting legacy-document content before rewriting.
4. Generate editable diagram sources and keep screenshots only when unavoidable.

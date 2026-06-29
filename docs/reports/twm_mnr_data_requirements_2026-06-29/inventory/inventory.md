# Design Document Regeneration Inventory

- Generated: `2026-06-29T09:21:40.140164+00:00`
- Working directory: `/Users/zhouning/gisdataagent`

## Code Roots

### `/Users/zhouning/gisdataagent`

- Exists: `True`
- Git commit: `583699b6ca9c1bd68f36556f2f139ada9f5ae812`
- Files: `8393`
- Top extensions: `{'.md': 2577, '.py': 2233, '.json': 538, '.npy': 524, '.csv': 280, '.tif': 245, '.png': 221, '.sql': 190, '.tsx': 176, '.yaml': 159, '.geojson': 90, '.atx': 85, '.xml': 74, '.dita': 66, '.pdf': 57, '[no extension]': 54, '.txt': 43, '.dbf': 42, '.gdbtable': 41, '.gdbtablx': 41, '.prj': 40, '.shp': 40, '.shx': 40, '.docx': 38, '.gdbindexes': 36, '.jpg': 34, '.sbn': 31, '.sbx': 31, '.cpg': 29, '.svg': 26, '.parquet': 22, '.sh': 22, '.ts': 18, '.dwg': 17, '.html': 16, '.yml': 16, '.xlsx': 14, '.original': 12, '.properties': 12, '.jar': 11}`
- Marker files: `[{'path': 'requirements.txt', 'kind': 'python'}, {'path': 'Dockerfile', 'kind': 'docker'}, {'path': 'pyproject.toml', 'kind': 'python'}, {'path': 'docker-compose.yml', 'kind': 'docker-compose'}, {'path': 'docker/mmfe-spark-runtime/Dockerfile', 'kind': 'docker'}, {'path': 'docker/postgis-pgvector/Dockerfile', 'kind': 'docker'}, {'path': 'frontend/package.json', 'kind': 'node'}, {'path': 'k8s/overlays/local-kind/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'k8s/overlays/docker-desktop/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'k8s/base/kustomization.yaml', 'kind': 'kustomize'}, {'path': 'gis-skill-sdk/pyproject.toml', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/blender-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/qgis-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/tool-mcp-servers/arcgis-mcp/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/reference-data/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/reference-data/Dockerfile', 'kind': 'docker'}, {'path': 'subsystems/cad-parser/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/cad-parser/Dockerfile', 'kind': 'docker'}, {'path': 'subsystems/cv-service/requirements.txt', 'kind': 'python'}, {'path': 'subsystems/cv-service/Dockerfile', 'kind': 'docker'}]`

## EA Artifacts

## Recommended Next Steps

1. Convert binary EA repositories to XMI/XML exports when detailed model parsing is needed.
2. Build an evidence pack from code, schemas, configs, EA elements, and legacy-doc claims.
3. Audit unsupported and conflicting legacy-document content before rewriting.
4. Generate editable diagram sources and keep screenshots only when unavoidable.

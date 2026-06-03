# Standards Platform Wave 8b EA-compatible XMI Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Standards Platform P3 by exporting the active `std_data_model_snapshot` PDM layer as an EA-compatible UML/XMI XML download.

**Architecture:** Add a pure Python XMI exporter next to `data_model_renderer.py`, then expose it through the existing `/api/std/data-model/*` route family and existing frontend data-model modal. The exporter has no DB, filesystem, REST, ADK, or logging side effects, so it can be tested with small PDM dictionaries and the existing XMI parser round-trip.

**Tech Stack:** Python 3.13, stdlib `xml.etree.ElementTree`, Starlette routes/responses, SQLAlchemy text queries via existing helpers, React 18 + TypeScript, pytest.

---

## File Structure

- Create `data_agent/standards_platform/derivation/data_model_xmi_exporter.py`
  - Pure exporter from PDM JSON to EA-compatible XMI XML.
  - Owns stable ID generation, PDM type to EAJava type mapping, multiplicity rendering, and XML serialization.
- Create `data_agent/standards_platform/tests/test_data_model_xmi_exporter.py`
  - Pure unit tests plus parser round-trip using `parse_xmi_file()`.
- Modify `data_agent/api/standards_routes.py`
  - Add `Response` import.
  - Import `export_pdm_to_ea_xmi`.
  - Add `data_model_xmi_handler`.
  - Register `GET /api/std/data-model/{version_id}/xmi`.
- Modify `data_agent/standards_platform/tests/test_api_data_model.py`
  - Extend existing Wave 8 data-model API tests with XMI auth, 404, and happy path coverage.
- Modify `frontend/src/components/datapanel/standards/standardsApi.ts`
  - Add `getDataModelXmiDownloadUrl(versionId)`.
- Modify `frontend/src/components/datapanel/standards/derive/DataModelPreviewModal.tsx`
  - Add `Download XMI` action beside the existing DDL controls.
- Modify `docs/roadmap.md`
  - Add v25.3 Wave 8b completed section after implementation passes.

---

### Task 1: Pure XMI Exporter Tests

**Files:**
- Create: `data_agent/standards_platform/tests/test_data_model_xmi_exporter.py`

- [x] **Step 1: Write the failing exporter tests**

Create `data_agent/standards_platform/tests/test_data_model_xmi_exporter.py`:

```python
"""Pure-function tests for EA-compatible XMI export from PDM snapshots."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from data_agent.standards.xmi_parser import parse_xmi_file
from data_agent.standards_platform.derivation.data_model_xmi_exporter import (
    export_pdm_to_ea_xmi,
)


def _pdm() -> dict:
    return {
        "layer": "PDM",
        "dialect": "postgresql",
        "entities": [
            {
                "physical_table": "cq_dltb",
                "name_zh": "土地利用图斑",
                "name_en": "land_parcel",
                "attributes": [
                    {
                        "physical_column": "DLBM",
                        "name_zh": "地类编码",
                        "physical_type": "VARCHAR(64)",
                        "nullable": False,
                        "is_geometry": False,
                        "constraints": ["CHECK (\"DLBM\" IN ('01'))"],
                    },
                    {
                        "physical_column": "MJ",
                        "name_zh": "面积",
                        "physical_type": "NUMERIC(18,4)",
                        "nullable": True,
                        "is_geometry": False,
                        "constraints": [],
                    },
                    {
                        "physical_column": "geometry",
                        "name_zh": "几何图形",
                        "physical_type": "GEOMETRY(POLYGON, 4490)",
                        "nullable": False,
                        "is_geometry": True,
                        "constraints": [],
                    },
                ],
            },
            {
                "physical_table": "std_region",
                "name_zh": "行政区",
                "name_en": "region",
                "attributes": [
                    {
                        "physical_column": "enabled",
                        "name_zh": "是否启用",
                        "physical_type": "BOOLEAN",
                        "nullable": True,
                        "is_geometry": False,
                        "constraints": [],
                    }
                ],
            },
        ],
    }


def test_export_pdm_to_ea_xmi_emits_minimal_uml_document():
    xml = export_pdm_to_ea_xmi(
        _pdm(),
        model_name="Standards Platform Data Model",
        package_name="自然资源数据模型",
    )

    root = ET.fromstring(xml)
    assert root.tag.endswith("XMI")
    assert "uml:Model" in xml
    assert "自然资源数据模型" in xml
    assert "土地利用图斑" in xml
    assert "地类编码" in xml

    class_count = xml.count('xmi:type="uml:Class"')
    attr_count = xml.count('xmi:type="uml:Property"')
    assert class_count == 2
    assert attr_count == 4


def test_export_pdm_to_ea_xmi_is_deterministic():
    first = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")
    second = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")

    assert first == second
    assert "CLASS_" in first
    assert "ATTR_" in first


def test_export_pdm_to_ea_xmi_round_trips_through_existing_parser(tmp_path: Path):
    xml = export_pdm_to_ea_xmi(_pdm(), package_name="自然资源数据模型")
    target = tmp_path / "exported_model.xml"
    target.write_text(xml, encoding="utf-8")

    parsed = parse_xmi_file(target)

    assert parsed.top_package_name == "自然资源数据模型"
    assert parsed.stats.total_classes == 2
    assert parsed.stats.total_attributes == 4
    class_by_name = {c.name_decoded: c for c in parsed.classes}
    assert "土地利用图斑" in class_by_name

    attrs = {a.name_decoded: a for a in class_by_name["土地利用图斑"].attributes}
    assert attrs["地类编码"].lower == "1"
    assert attrs["地类编码"].upper == "1"
    assert attrs["地类编码"].type_name == "string"
    assert attrs["面积"].lower == "0"
    assert attrs["面积"].upper == "1"
    assert attrs["面积"].type_name == "numeric"
    assert attrs["几何图形"].type_name == "string"
```

- [x] **Step 2: Run tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_data_model_xmi_exporter.py -q
```

Expected: FAIL during import with `ModuleNotFoundError` or `No module named ... data_model_xmi_exporter`.

---

### Task 2: Pure XMI Exporter Implementation

**Files:**
- Create: `data_agent/standards_platform/derivation/data_model_xmi_exporter.py`
- Test: `data_agent/standards_platform/tests/test_data_model_xmi_exporter.py`

- [x] **Step 1: Write minimal exporter implementation**

Create `data_agent/standards_platform/derivation/data_model_xmi_exporter.py`:

```python
"""EA-compatible XMI export for Standards Platform data-model snapshots.

The exporter is intentionally pure: no DB calls, no filesystem access, no REST
objects. It accepts the PDM JSON shape emitted by data_model_renderer.render_pdm
and returns a minimal UML/XMI XML document that the existing xmi_parser can
round-trip.
"""
from __future__ import annotations

from hashlib import sha1
import re
import xml.etree.ElementTree as ET


UML_NS = "http://www.omg.org/spec/UML/20161101"
XMI_NS = "http://www.omg.org/spec/XMI/20131001"

ET.register_namespace("uml", UML_NS)
ET.register_namespace("xmi", XMI_NS)


def _stable_id(prefix: str, seed: str) -> str:
    digest = sha1(seed.encode("utf-8")).hexdigest()[:16].upper()
    safe_prefix = re.sub(r"[^A-Za-z0-9_]", "_", prefix).strip("_") or "ID"
    if not safe_prefix[0].isalpha():
        safe_prefix = f"X_{safe_prefix}"
    return f"{safe_prefix}_{digest}"


def _xmi_attr(name: str) -> str:
    return f"{{{XMI_NS}}}{name}"


def _physical_type_to_eajava(attr: dict) -> str:
    physical = str(attr.get("physical_type") or "").upper()
    if attr.get("is_geometry") or "GEOMETRY" in physical:
        return "EAJava_String"
    if any(marker in physical for marker in ("NUMERIC", "DECIMAL", "DOUBLE", "FLOAT", "REAL")):
        return "EAJava_double"
    if any(marker in physical for marker in ("BIGINT", "INTEGER", "SMALLINT", "INT")):
        return "EAJava_long"
    if "BOOLEAN" in physical or physical == "BOOL":
        return "EAJava_boolean"
    return "EAJava_String"


def _multiplicity(nullable: bool) -> tuple[str, str]:
    return ("0", "1") if nullable else ("1", "1")


def _add_multiplicity(parent: ET.Element, attr_id: str, nullable: bool) -> None:
    lower, upper = _multiplicity(nullable)
    ET.SubElement(parent, "lowerValue", {
        _xmi_attr("type"): "uml:LiteralInteger",
        _xmi_attr("id"): _stable_id("LOWER", attr_id),
        "value": lower,
    })
    ET.SubElement(parent, "upperValue", {
        _xmi_attr("type"): "uml:LiteralUnlimitedNatural",
        _xmi_attr("id"): _stable_id("UPPER", attr_id),
        "value": upper,
    })


def export_pdm_to_ea_xmi(
    pdm: dict,
    *,
    model_name: str = "Standards Platform Data Model",
    package_name: str | None = None,
) -> str:
    """Return an EA-compatible UML/XMI XML document for a PDM snapshot."""
    effective_package = package_name or model_name or "Standards Platform Data Model"

    root = ET.Element(f"{{{XMI_NS}}}XMI")
    model = ET.SubElement(root, f"{{{UML_NS}}}Model", {
        _xmi_attr("type"): "uml:Model",
        "name": "EA_Model",
    })
    package = ET.SubElement(model, "packagedElement", {
        _xmi_attr("type"): "uml:Package",
        _xmi_attr("id"): _stable_id("PKG", effective_package),
        "name": effective_package,
    })

    for entity in pdm.get("entities", []) or []:
        table = str(entity.get("physical_table") or entity.get("name_en") or "entity")
        class_name = str(entity.get("name_zh") or table)
        klass = ET.SubElement(package, "packagedElement", {
            _xmi_attr("type"): "uml:Class",
            _xmi_attr("id"): _stable_id("CLASS", table),
            "name": class_name,
        })

        for attr in entity.get("attributes", []) or []:
            column = str(attr.get("physical_column") or attr.get("name_zh") or "attribute")
            attr_name = str(attr.get("name_zh") or column)
            attr_seed = f"{table}.{column}"
            attr_id = _stable_id("ATTR", attr_seed)
            prop = ET.SubElement(klass, "ownedAttribute", {
                _xmi_attr("type"): "uml:Property",
                _xmi_attr("id"): attr_id,
                "name": attr_name,
                "visibility": "private",
            })
            _add_multiplicity(prop, attr_id, bool(attr.get("nullable", True)))
            ET.SubElement(prop, "type", {
                _xmi_attr("idref"): _physical_type_to_eajava(attr),
            })

    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
```

- [x] **Step 2: Run exporter tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_data_model_xmi_exporter.py -q
```

Expected: PASS.

- [x] **Step 3: Commit exporter**

Run:

```powershell
git add data_agent/standards_platform/derivation/data_model_xmi_exporter.py data_agent/standards_platform/tests/test_data_model_xmi_exporter.py
git commit -m "feat(std-platform): export data model snapshots as XMI"
```

---

### Task 3: XMI API Tests

**Files:**
- Modify: `data_agent/standards_platform/tests/test_api_data_model.py`

- [x] **Step 1: Add failing API tests**

Append these tests to `data_agent/standards_platform/tests/test_api_data_model.py`:

```python
def test_data_model_xmi_requires_auth(monkeypatch):
    monkeypatch.setattr(
        "data_agent.api.helpers._get_user_from_request", lambda r: None
    )
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}/xmi")
    assert r.status_code == 401


def test_data_model_xmi_unknown_version_404(monkeypatch):
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{uuid.uuid4()}/xmi")
    assert r.status_code == 404


def test_data_model_xmi_no_active_snapshot_404(monkeypatch, fresh_clause):
    _, _, ver_id = fresh_clause
    _auth_user(monkeypatch, role="admin")
    r = _client().get(f"/api/std/data-model/{ver_id}/xmi")
    assert r.status_code == 404
    assert "no active data-model snapshot" in r.json()["error"]


def test_data_model_xmi_returns_xml_attachment(monkeypatch, engine, fresh_clause):
    _, _, ver_id = fresh_clause
    _seed_one_element(engine, ver_id)
    DataModelStrategy().run(version_id=ver_id)
    _auth_user(monkeypatch, role="viewer")

    r = _client().get(f"/api/std/data-model/{ver_id}/xmi")

    assert r.status_code == 200
    assert "application/xml" in r.headers.get("content-type", "")
    assert "content-disposition" in {k.lower() for k in r.headers.keys()}
    assert f"data_model_{ver_id[:8]}.xml" in r.headers["content-disposition"]
    assert "<uml:Model" in r.text
    assert 'xmi:type="uml:Class"' in r.text
```

- [x] **Step 2: Run API tests to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_data_model.py -q
```

Expected: new XMI route tests FAIL with `404 Not Found` because the route is not registered.

---

### Task 4: XMI API Implementation

**Files:**
- Modify: `data_agent/api/standards_routes.py`
- Test: `data_agent/standards_platform/tests/test_api_data_model.py`

- [x] **Step 1: Add imports**

In `data_agent/api/standards_routes.py`, change:

```python
from starlette.responses import JSONResponse, PlainTextResponse
```

to:

```python
from starlette.responses import JSONResponse, PlainTextResponse, Response
```

Add near the derivation imports:

```python
from ..standards_platform.derivation.data_model_xmi_exporter import (
    export_pdm_to_ea_xmi,
)
```

- [x] **Step 2: Add XMI handler**

Place this after `data_model_ddl_handler` and before `data_model_snapshots_handler`:

```python
async def data_model_xmi_handler(request: Request):
    """GET /api/std/data-model/{vid}/xmi — returns EA-compatible XMI XML."""
    _, _, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    not_found = _data_model_version_or_404(vid)
    if not_found: return not_found

    snap = _active_snapshot_or_404(vid)
    if isinstance(snap, JSONResponse): return snap

    try:
        xmi = export_pdm_to_ea_xmi(
            snap["pdm_json"],
            model_name=f"Standards Platform Data Model {vid[:8]}",
            package_name=f"Data Model {vid[:8]}",
        )
    except Exception as e:
        logger.exception("failed to export data-model XMI")
        return JSONResponse({"error": f"failed to export XMI: {e}"},
                            status_code=500)

    return Response(
        xmi,
        media_type="application/xml",
        headers={
            "Content-Disposition":
                f'attachment; filename="data_model_{vid[:8]}.xml"',
        },
    )
```

- [x] **Step 3: Register route**

In the route list near the existing Wave 8 data-model routes, add this route
between `/ddl` and `/snapshots`:

```python
    Route("/api/std/data-model/{version_id}/xmi",
          endpoint=data_model_xmi_handler, methods=["GET"]),
```

- [x] **Step 4: Run API tests to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_data_model.py -q
```

Expected: PASS.

- [x] **Step 5: Commit API**

Run:

```powershell
git add data_agent/api/standards_routes.py data_agent/standards_platform/tests/test_api_data_model.py
git commit -m "feat(std-platform): expose data model XMI download API"
```

---

### Task 5: Frontend XMI Download

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`
- Modify: `frontend/src/components/datapanel/standards/derive/DataModelPreviewModal.tsx`

- [x] **Step 1: Add SDK helper**

In `frontend/src/components/datapanel/standards/standardsApi.ts`, add below
`getDataModelDdlDownloadUrl`:

```typescript
export const getDataModelXmiDownloadUrl = (versionId: string) =>
  `/api/std/data-model/${versionId}/xmi`;
```

- [x] **Step 2: Wire modal download action**

In `DataModelPreviewModal.tsx`, update the import:

```typescript
import {
  DataModelPayload,
  getDataModel,
  getDataModelDdlDownloadUrl,
  getDataModelXmiDownloadUrl,
} from "../standardsApi";
```

In the DDL toolbar, add this anchor after the `.sql` download anchor:

```tsx
            <a href={getDataModelXmiDownloadUrl(versionId)}
               style={{ padding: "4px 12px",
                        background: "#2f6f4e", color: "#fff",
                        textDecoration: "none", borderRadius: 4 }}>
              下载 XMI
            </a>
```

- [x] **Step 3: Build frontend**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits 0.

- [x] **Step 4: Commit frontend**

Run:

```powershell
git add frontend/src/components/datapanel/standards/standardsApi.ts frontend/src/components/datapanel/standards/derive/DataModelPreviewModal.tsx
git commit -m "feat(std-platform-fe): add XMI download action"
```

---

### Task 6: Roadmap and Verification

**Files:**
- Modify: `docs/roadmap.md`

- [x] **Step 1: Update roadmap after implementation**

Update the top roadmap header:

```markdown
**Current version**: v25.3 &nbsp;|&nbsp; **Next**: P4 (Standards Platform review workflow templates / batch rollback / cross-standard impact)
```

Add a section before `v25.3-eval`:

```markdown
## v25.3 — Standards Platform Wave 8b (P3 收口, 已完成, 2026-06-03)

- [x] **EA-compatible XMI 导出** — 新增 `data_model_xmi_exporter.py`，从 active `std_data_model_snapshot.pdm_json` 导出 UML/XMI XML，稳定 ID、PDM 类型映射、nullable multiplicity。
- [x] **XMI 下载 API** — `GET /api/std/data-model/{vid}/xmi`，任何已登录角色可读，返回 `application/xml` + `.xml` attachment。
- [x] **前端下载入口** — `DataModelPreviewModal.tsx` 在 DDL 工具栏增加「下载 XMI」，复用既有数据模型预览 modal，不新增独立建模 sub-tab。
- [x] **Round-trip 验证** — 导出的 XMI 可被现有 `parse_xmi_file()` 解析出 class / attribute / multiplicity。

> P3 首个生产级闭环完成：CDM/LDM/PDM + PostgreSQL DDL + EA-compatible XMI export。下一步进入 P4：审定流模板可视化、批量回滚、跨标准影响图谱。
```

- [x] **Step 2: Run focused backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_data_model_xmi_exporter.py data_agent/standards_platform/tests/test_api_data_model.py -q
```

Expected: PASS.

- [x] **Step 3: Run standards platform suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -q
```

Expected: PASS, with the same known skip count as before unless unrelated dirty worktree changes alter test state.

- [x] **Step 4: Commit docs**

Run:

```powershell
git add docs/roadmap.md docs/superpowers/plans/2026-06-03-std-platform-wave8b-ea-xmi-export.md
git commit -m "docs(std-platform): mark Wave 8b XMI export complete"
```

---

## Self-Review Notes

- Spec coverage: exporter, API, frontend, error handling, round-trip test, and roadmap closure are all mapped to tasks.
- Scope: P4/P5 remain out of implementation scope; roadmap update only points to them as next work.
- TDD: backend exporter and API both start with failing tests before production code.
- Frontend: no existing focused TS test harness for this modal; verification uses `npm run build`.

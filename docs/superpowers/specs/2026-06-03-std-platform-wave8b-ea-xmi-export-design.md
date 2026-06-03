# Standards Platform Wave 8b — EA-compatible XMI Export (P3 Closure)

- **Status**: Design
- **Date**: 2026-06-03
- **Scope**: v25.3 mainline, P3 data-modeling closure
- **Related roadmap**: `docs/roadmap.md` v25.x Standards Platform, Wave 8b / P3
- **Builds on**: `docs/superpowers/specs/2026-06-01-std-platform-wave8-data-model-design.md`

## 1. Goal

Close the P3 data-modeling stage of the Standards Platform lifecycle by turning
the already-derived `std_data_model_snapshot` into an EA-compatible XMI export.

The platform already supports:

- standard lifecycle management: ingestion, drafting, review, publish, derive;
- six active derivation strategies, including `to_data_model`;
- CDM / LDM / PDM JSON and PostgreSQL DDL snapshots;
- EA XMI parsing and compilation for the existing EA-to-platform direction.

Wave 8b adds the missing reverse direction:

```text
released standard version
  -> to_data_model snapshot
  -> EA-compatible UML/XMI XML
  -> downloadable modeling artifact
```

This should be positioned as a Standards Platform export capability, not as a
new dependency on Enterprise Architect.

## 2. Non-goals

This slice does not implement:

- full EA repository synchronization;
- a visual model editor;
- CDM/LDM/PDM manual override or JSON patch editing;
- associations, inheritance, or relationship inference beyond existing snapshot
  information;
- one-click database DDL execution;
- P4 review-template visualization, batch rollback, or cross-standard impact
  operations.

Those remain follow-up slices after P3 is closed.

## 3. Design

### 3.1 Exporter module

Add a pure exporter beside the existing renderer:

```text
data_agent/standards_platform/derivation/data_model_xmi_exporter.py
```

Public contract:

```python
def export_pdm_to_ea_xmi(
    pdm: dict,
    *,
    model_name: str = "Standards Platform Data Model",
    package_name: str | None = None,
) -> str:
    """Return an EA-compatible UML/XMI XML document."""
```

The exporter uses only Python standard XML APIs. It does not call the database,
ADK, REST, logging, or filesystem APIs. This keeps it testable like
`data_model_renderer.py`.

### 3.2 XMI shape

Use the same minimal UML/XMI structure that the existing
`data_agent.standards.xmi_parser.parse_xmi_file()` already understands:

```xml
<xmi:XMI xmlns:uml="http://www.omg.org/spec/UML/20161101"
         xmlns:xmi="http://www.omg.org/spec/XMI/20131001">
  <uml:Model xmi:type="uml:Model" name="EA_Model">
    <packagedElement xmi:type="uml:Package" xmi:id="..." name="...">
      <packagedElement xmi:type="uml:Class" xmi:id="..." name="...">
        <ownedAttribute xmi:type="uml:Property" xmi:id="..."
                        name="..." visibility="private">
          <type xmi:idref="EAJava_String"/>
        </ownedAttribute>
      </packagedElement>
    </packagedElement>
  </uml:Model>
</xmi:XMI>
```

Mapping:

| PDM field | XMI target |
|---|---|
| entity `physical_table` | class stable id seed |
| entity `name_zh` or `physical_table` | class `name` |
| attribute `physical_column` | property stable id seed |
| attribute `name_zh` or `physical_column` | property `name` |
| attribute `nullable=false` | lower/upper multiplicity `1..1` |
| attribute `nullable=true` | lower/upper multiplicity `0..1` |
| attribute `physical_type` / `is_geometry` | EAJava primitive alias |

Type mapping:

| PDM type marker | XMI type ref |
|---|---|
| `VARCHAR`, `TEXT`, unknown | `EAJava_String` |
| `BIGINT`, `INTEGER`, `SMALLINT` | `EAJava_long` |
| `NUMERIC`, `DECIMAL`, `DOUBLE`, `FLOAT` | `EAJava_double` |
| `BOOLEAN` | `EAJava_boolean` |
| `TIMESTAMP`, `DATE`, `TIME` | `EAJava_String` |
| `GEOMETRY(...)` or `is_geometry=true` | `EAJava_String` |

Dates and geometries are exported as strings in the first slice because the
current parser already normalizes EAJava primitives and the PDM/DDL remains the
authoritative source for exact physical typing.

### 3.3 Stable IDs

Generate deterministic IDs so repeated exports of the same snapshot produce the
same structural identifiers:

```text
PKG_<hash(package_name)>
CLASS_<hash(physical_table)>
ATTR_<hash(physical_table + "." + physical_column)>
LOWER_<hash(attribute_id)>
UPPER_<hash(attribute_id)>
```

IDs must start with a letter and contain only letters, numbers, and `_`.

### 3.4 API

Add a read-only route to `data_agent/api/standards_routes.py`:

| Route | Method | Behavior | Auth |
|---|---|---|---|
| `/api/std/data-model/{version_id}/xmi` | GET | returns active snapshot as `application/xml` attachment | any authenticated user |

Error handling:

- `401` when unauthenticated;
- `404` when version does not exist;
- `404` when no active data-model snapshot exists;
- `500` only for unexpected export errors.

Download filename:

```text
data_model_<version_prefix>.xml
```

### 3.5 Frontend

Extend the existing Wave 8 modal instead of adding a new sub-tab:

```text
frontend/src/components/datapanel/standards/derive/DataModelPreviewModal.tsx
frontend/src/components/datapanel/standards/standardsApi.ts
```

Changes:

- add `getDataModelXmiDownloadUrl(versionId)`;
- add a compact `Download XMI` action next to the existing DDL controls;
- keep the existing CDM/LDM/PDM/DDL preview behavior unchanged.

No visual model editor is added in this slice.

## 4. Data Flow

```text
GET /api/std/data-model/{version_id}/xmi
  -> auth check
  -> verify std_document_version exists
  -> fetch latest active std_data_model_snapshot
  -> export_pdm_to_ea_xmi(snapshot.pdm_json)
  -> return XML attachment
```

The exporter reads the PDM layer only. CDM/LDM remain available in the existing
preview API but are not required to produce class/attribute XML.

## 5. Testing

Add focused tests:

| Test file | Coverage |
|---|---|
| `test_data_model_xmi_exporter.py` | pure exporter structure, deterministic IDs, type mapping, multiplicity |
| `test_api_data_model.py` | extend existing data-model API tests with auth, 404s, XML response, attachment headers |
| `test_data_model_xmi_exporter.py` | write exported XML to tmp file and parse with `parse_xmi_file()` |

Acceptance:

- exporter output parses as valid XML;
- parser round-trip sees expected class and attribute counts;
- `GET /api/std/data-model/{version_id}/xmi` returns `200` and XML for a seeded snapshot;
- standards platform tests pass.

## 6. Roadmap Closure

After this slice:

- P3 can be marked closed for first production-grade scope:
  CDM/LDM/PDM + DDL + EA-compatible XMI export.
- P4 should become the next mainline spec:
  review workflow templates, batch rollback, and cross-standard impact graph.

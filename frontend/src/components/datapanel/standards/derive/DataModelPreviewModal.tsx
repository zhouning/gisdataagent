import React, { useEffect, useMemo, useState } from "react";
import { Download, Maximize2, Minimize2, X } from "lucide-react";
import {
  DataModelPayload,
  getDataModel,
  getDataModelDdlDownloadUrl,
  getDataModelXmiDownloadUrl,
} from "../standardsApi";
import DataModelErCanvas from "./DataModelErCanvas";

interface Props {
  versionId: string;
  onClose?: () => void;
  embedded?: boolean;
}

type JsonObject = Record<string, any>;
type TabKey = "canvas" | "browser" | "relations" | "pdm" | "ldm" | "cdm" | "ddl";

const TABS: { key: TabKey; label: string }[] = [
  { key: "canvas", label: "ER 画布" },
  { key: "browser", label: "模型浏览" },
  { key: "relations", label: "关系视图" },
  { key: "pdm", label: "PDM 物理层" },
  { key: "ldm", label: "LDM 逻辑层" },
  { key: "cdm", label: "CDM 概念层" },
  { key: "ddl", label: "DDL" },
];

const emptyArray = (value: unknown): any[] =>
  Array.isArray(value) ? value : [];

const objectArray = (value: unknown): JsonObject[] =>
  emptyArray(value).filter(
    (item): item is JsonObject => !!item && typeof item === "object",
  );

const layerEntities = (layer: unknown): JsonObject[] =>
  objectArray((layer as JsonObject | null)?.entities);

const entityKey = (entity: JsonObject, index = 0): string =>
  String(
    entity.id ??
      entity.physical_table ??
      entity.table ??
      entity.name_en ??
      entity.name_zh ??
      `entity-${index}`,
  );

const entityName = (entity: JsonObject): string =>
  String(entity.name_zh || entity.name_en || entity.physical_table || entity.id || "未命名实体");

const entityNameEn = (entity: JsonObject): string =>
  String(entity.name_en || entity.physical_table || entity.id || "");

const entityDomain = (entity: JsonObject): string =>
  String(entity.domain || (entity.physical_table || "").split(".")[0] || "未分域");

const isMetadataEntity = (entity: JsonObject): boolean => {
  const domain = entityDomain(entity).toLowerCase();
  const table = String(entity.physical_table || "").toLowerCase();
  return domain === "gda_meta" || domain.startsWith("gda_") || table.startsWith("gda_meta.");
};

const attributeName = (attribute: JsonObject): string =>
  String(
    attribute.name_zh ||
      attribute.name ||
      attribute.code ||
      attribute.physical_column ||
      attribute.name_en ||
      "未命名字段",
  );

const attributeCode = (attribute: JsonObject): string =>
  String(
    attribute.physical_column ||
      attribute.code ||
      attribute.name_en ||
      attribute.name ||
      "",
  );

const attributeType = (attribute: JsonObject): string =>
  String(attribute.physical_type || attribute.logical_type || attribute.datatype || "—");

const relationEntities = (payload: DataModelPayload): JsonObject[] =>
  layerEntities(payload.pdm).length
    ? layerEntities(payload.pdm)
    : layerEntities(payload.ldm).length
      ? layerEntities(payload.ldm)
      : layerEntities(payload.cdm);

const relationList = (payload: DataModelPayload): JsonObject[] => {
  const layers = [payload.pdm, payload.ldm, payload.cdm];
  const seen = new Set<string>();
  const result: JsonObject[] = [];
  for (const layer of layers) {
    for (const relation of objectArray((layer as JsonObject | null)?.relationships)) {
      const key = JSON.stringify([
        relation.source,
        relation.target,
        relation.source_field,
        relation.type,
      ]);
      if (!seen.has(key)) {
        seen.add(key);
        result.push(relation);
      }
    }
  }
  return result;
};

function labelForReference(reference: unknown, entities: JsonObject[]): string {
  const raw = String(reference || "");
  const match = entities.find((entity, index) => {
    const key = entityKey(entity, index);
    return key === raw || entity.physical_table === raw || entity.id === raw;
  });
  return match ? `${entityName(match)} (${match.physical_table || entityKey(match)})` : raw || "—";
}

function statusLabel(status: string): string {
  if (status === "manual") return "候选 · 手工整理";
  if (status === "active") return "正式 · 自动派生";
  return status || "未知状态";
}

function modelLayer(payload: DataModelPayload, layer: "pdm" | "ldm" | "cdm") {
  return (payload[layer] || {}) as JsonObject;
}

/**
 * Browse a Standards Platform data-model snapshot as a usable model catalog.
 * Raw JSON and DDL remain available for export and backward compatibility;
 * the default view is a domain/entity/attribute master-detail browser.
 */
export default function DataModelPreviewModal({
  versionId,
  onClose,
  embedded = false,
}: Props) {
  const [payload, setPayload] = useState<DataModelPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("canvas");
  const [copyHint, setCopyHint] = useState<string>("");
  const [domain, setDomain] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [activeEntityKey, setActiveEntityKey] = useState<string>("");
  const [relationSearch, setRelationSearch] = useState<string>("");
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    setError(null);
    setPayload(null);
    setDomain("");
    setSearch("");
    setActiveEntityKey("");
    getDataModel(versionId).then(setPayload).catch((e) => {
      setError(typeof e?.message === "string" ? e.message : String(e));
    });
  }, [versionId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (isMaximized) {
        setIsMaximized(false);
      } else if (!embedded) {
        onClose?.();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [embedded, isMaximized, onClose]);

  const entities = useMemo(
    () => (payload ? relationEntities(payload) : []),
    [payload],
  );

  const domains = useMemo(() => {
    const values = new Set<string>();
    for (const entity of entities) values.add(entityDomain(entity));
    for (const domainEntry of objectArray((payload?.cdm as JsonObject | null)?.domains)) {
      if (domainEntry.id || domainEntry.name_en || domainEntry.name_zh) {
        values.add(String(domainEntry.id || domainEntry.name_en || domainEntry.name_zh));
      }
    }
    return Array.from(values).sort((a, b) => a.localeCompare(b));
  }, [entities, payload]);

  const domainLabels = useMemo(() => {
    const labels = new Map<string, string>();
    for (const domainEntry of objectArray((payload?.cdm as JsonObject | null)?.domains)) {
      const key = String(domainEntry.id || domainEntry.name_en || domainEntry.name_zh || "");
      if (!key) continue;
      const name = String(domainEntry.name_zh || domainEntry.name_en || key);
      labels.set(key, name === key ? key : `${name} (${key})`);
    }
    return labels;
  }, [payload]);

  const filteredEntities = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entities.filter((entity, index) => {
      if (domain && entityDomain(entity) !== domain) return false;
      if (!q) return true;
      const haystack = [
        entityKey(entity, index),
        entityName(entity),
        entityNameEn(entity),
        entity.physical_table,
        ...objectArray(entity.attributes).flatMap((attribute) => [
          attributeName(attribute),
          attributeCode(attribute),
        ]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [domain, entities, search]);

  useEffect(() => {
    if (!filteredEntities.some((entity, index) => entityKey(entity, index) === activeEntityKey)) {
      const preferred = filteredEntities.find((entity) => !isMetadataEntity(entity)) || filteredEntities[0];
      setActiveEntityKey(preferred ? entityKey(preferred, filteredEntities.indexOf(preferred)) : "");
    }
  }, [activeEntityKey, filteredEntities]);

  const activeEntity = useMemo(
    () =>
      filteredEntities.find((entity, index) => entityKey(entity, index) === activeEntityKey) ||
      filteredEntities[0] ||
      null,
    [activeEntityKey, filteredEntities],
  );

  const relations = useMemo(() => (payload ? relationList(payload) : []), [payload]);
  const filteredRelations = useMemo(() => {
    const q = relationSearch.trim().toLowerCase();
    if (!q) return relations;
    return relations.filter((relation) =>
      [
        relation.source,
        relation.target,
        relation.source_field,
        relation.type,
        relation.method,
        relation.confidence,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [relationSearch, relations]);

  const onCopyDdl = async () => {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload.ddl_postgresql);
      setCopyHint("已复制");
      setTimeout(() => setCopyHint(""), 1500);
    } catch {
      setCopyHint("复制失败");
      setTimeout(() => setCopyHint(""), 1500);
    }
  };

  const renderAttributeTable = (entity: JsonObject | null) => {
    if (!entity) return <div style={{ padding: 20, color: "#777" }}>没有匹配的实体。</div>;
    const attributes = objectArray(entity.attributes);
    return (
      <div style={{ overflow: "auto", flex: 1 }}>
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12, color: "#243447", background: "#fff" }}>
          <thead>
            <tr style={{ background: "#f7f9fb", color: "#526273", position: "sticky", top: 0, zIndex: 1 }}>
              {[
                "字段",
                "代码 / 列名",
                "类型",
                "角色",
                "可空",
                "敏感级别",
                "引用",
                "说明",
              ].map((heading) => (
                <th key={heading} style={{ padding: "8px 7px", textAlign: "left", borderBottom: "1px solid #dde3e8", whiteSpace: "nowrap" }}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {attributes.map((attribute, index) => (
              <tr key={`${attributeCode(attribute)}-${index}`} style={{ color: "#243447", background: index % 2 ? "#fcfdff" : "#fff" }}>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#243447", fontWeight: 600 }}>
                  {attributeName(attribute)}{attribute.is_geometry ? " ◈" : ""}
                </td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#526273", fontFamily: "Menlo, Consolas, monospace" }}>
                  {attributeCode(attribute) || "—"}
                </td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#334155", whiteSpace: "nowrap" }}>{attributeType(attribute)}</td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#475569" }}>{attribute.role || "attribute"}</td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#475569", whiteSpace: "nowrap" }}>
                  {attribute.nullable === undefined ? "—" : attribute.nullable ? "是" : "否"}
                </td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#475569" }}>{attribute.sensitivity || "—"}</td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#2563a6" }}>{attribute.ref || "—"}</td>
                <td style={{ padding: "7px", borderBottom: "1px solid #eef1f4", color: "#5f6974", minWidth: 160 }}>
                  {attribute.description || attribute.comment || attribute.value_domain_code || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!attributes.length && <div style={{ padding: 20, color: "#777" }}>该实体暂无字段定义。</div>}
      </div>
    );
  };

  const renderBrowser = () => (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 32%) 1fr", height: "100%", minHeight: 0 }}>
      <div style={{ borderRight: "1px solid #e5e9ed", display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ padding: 10, borderBottom: "1px solid #eef1f4" }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 7 }}>
            <select value={domain} onChange={(event) => setDomain(event.target.value)} style={{ flex: 1, minWidth: 0, padding: "6px 7px", fontSize: 12, border: "1px solid #cbd4dd", borderRadius: 4 }}>
              <option value="">全部业务域 ({entities.length})</option>
              {domains.map((value) => (
                <option key={value} value={value}>
                  {domainLabels.get(value) || value} ({entities.filter((entity) => entityDomain(entity) === value).length})
                </option>
              ))}
            </select>
          </div>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索实体、表名或字段…" style={{ boxSizing: "border-box", width: "100%", padding: "7px 8px", fontSize: 12, border: "1px solid #cbd4dd", borderRadius: 4 }} />
        </div>
        <div style={{ overflow: "auto", flex: 1 }}>
          {filteredEntities.map((entity, index) => {
            const key = entityKey(entity, index);
            const selected = key === activeEntityKey;
            return (
              <button key={key} onClick={() => setActiveEntityKey(key)} style={{ display: "block", width: "100%", textAlign: "left", border: "none", borderLeft: selected ? "3px solid #007aff" : "3px solid transparent", background: selected ? "#eef6ff" : "#fff", padding: "9px 10px", cursor: "pointer" }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: "#213142", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entityName(entity)}</div>
                <div style={{ fontSize: 10, color: "#72808e", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {entityDomain(entity)} · {entity.physical_table || entityNameEn(entity)} · {objectArray(entity.attributes).length} 字段
                </div>
              </button>
            );
          })}
          {!filteredEntities.length && <div style={{ padding: 20, color: "#777", fontSize: 12 }}>没有匹配的实体。</div>}
        </div>
      </div>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
        {activeEntity ? (
          <>
            <div style={{ padding: "12px 14px", borderBottom: "1px solid #eef1f4" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 16, fontWeight: 600, color: "#1e2d3d" }}>{entityName(activeEntity)}</span>
                <span style={{ fontSize: 11, color: "#657382" }}>{entityNameEn(activeEntity)}</span>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 7, fontSize: 11 }}>
                <span style={{ padding: "3px 6px", borderRadius: 3, background: "#f0f3f6", color: "#566575" }}>{domainLabels.get(entityDomain(activeEntity)) || entityDomain(activeEntity)}</span>
                <span style={{ padding: "3px 6px", borderRadius: 3, background: "#f0f3f6", color: "#566575", fontFamily: "Menlo, Consolas, monospace" }}>{activeEntity.physical_table || entityKey(activeEntity)}</span>
                {activeEntity.wave && <span style={{ padding: "3px 6px", borderRadius: 3, background: "#edf8f1", color: "#287043" }}>{activeEntity.wave}</span>}
                {activeEntity.sensitivity && <span style={{ padding: "3px 6px", borderRadius: 3, background: "#fff5e8", color: "#8a5a15" }}>敏感度：{activeEntity.sensitivity}</span>}
              </div>
              {activeEntity.description && <div style={{ marginTop: 8, color: "#606d79", fontSize: 12 }}>{activeEntity.description}</div>}
            </div>
            {renderAttributeTable(activeEntity)}
          </>
        ) : (
          <div style={{ padding: 24, color: "#777" }}>暂无实体定义。</div>
        )}
      </div>
    </div>
  );

  const renderRelations = () => (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{ padding: 10, borderBottom: "1px solid #eef1f4", display: "flex", gap: 8, alignItems: "center" }}>
        <input value={relationSearch} onChange={(event) => setRelationSearch(event.target.value)} placeholder="搜索源实体、目标实体、字段或关系方法…" style={{ flex: 1, padding: "7px 8px", fontSize: 12, border: "1px solid #cbd4dd", borderRadius: 4 }} />
        <span style={{ fontSize: 11, color: "#71808d", whiteSpace: "nowrap" }}>{filteredRelations.length} / {relations.length} 条关系</span>
      </div>
      <div style={{ overflow: "auto", flex: 1, padding: 10 }}>
        {filteredRelations.map((relation, index) => (
          <div key={`${String(relation.source)}-${String(relation.target)}-${index}`} style={{ border: "1px solid #e2e7ec", borderRadius: 5, padding: "9px 10px", marginBottom: 8, background: "#fff" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12, flexWrap: "wrap" }}>
              <span style={{ color: "#1d567f", fontWeight: 500 }}>{labelForReference(relation.source, entities)}</span>
              <span style={{ color: "#9aa5af" }}>→</span>
              <span style={{ color: "#1d567f", fontWeight: 500 }}>{labelForReference(relation.target, entities)}</span>
              {relation.cardinality && <span style={{ marginLeft: "auto", color: "#586575", fontSize: 11 }}>{relation.cardinality}</span>}
            </div>
            <div style={{ marginTop: 5, display: "flex", gap: 12, color: "#6c7884", fontSize: 11, flexWrap: "wrap" }}>
              {relation.source_field && <span>字段：{relation.source_field}</span>}
              {relation.type && <span>类型：{relation.type}</span>}
              {relation.method && <span>方法：{relation.method}</span>}
              {relation.confidence && <span>置信度：{relation.confidence}</span>}
            </div>
          </div>
        ))}
        {!filteredRelations.length && <div style={{ padding: 20, color: "#777", fontSize: 12 }}>该快照没有关系定义或没有匹配结果。</div>}
      </div>
    </div>
  );

  const renderRawLayer = (layer: "pdm" | "ldm" | "cdm") => (
    <pre style={{ overflow: "auto", padding: 12, margin: 0, background: "#f7f7f7", fontSize: 12, height: "100%", fontFamily: "Menlo, Consolas, monospace" }}>
      {JSON.stringify(modelLayer(payload as DataModelPayload, layer), null, 2)}
    </pre>
  );

  const renderBody = () => {
    if (error) {
      return (
        <div style={{ padding: 16, color: "#c33", fontSize: 13 }}>
          加载失败：{error}
          <div style={{ marginTop: 8, color: "#666", fontSize: 12 }}>
            如果该版本尚未导入候选模型，请先运行手工模型导入脚本；正式模型则可在派生面板执行「重新派生」。
          </div>
        </div>
      );
    }
    if (!payload) return <div style={{ padding: 16, color: "#888" }}>加载中...</div>;
    if (tab === "canvas") {
      return (
        <DataModelErCanvas
          entities={entities}
          relationships={relations}
          domainLabels={domainLabels}
          onEntityOpen={(key) => {
            setDomain("");
            setSearch("");
            setActiveEntityKey(key);
            setTab("browser");
          }}
        />
      );
    }
    if (tab === "browser") return renderBrowser();
    if (tab === "relations") return renderRelations();
    if (tab === "ddl") {
      return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div style={{ padding: "8px 12px", borderBottom: "1px solid #eee", display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={onCopyDdl} style={{ padding: "4px 12px" }}>复制</button>
            <a href={getDataModelDdlDownloadUrl(versionId)} style={{ padding: "4px 12px", background: "#007aff", color: "#fff", textDecoration: "none", borderRadius: 4 }}>下载 .sql</a>
            <a href={getDataModelXmiDownloadUrl(versionId)} download style={{ padding: "4px 12px", background: "#2f6f4e", color: "#fff", textDecoration: "none", borderRadius: 4 }}>下载 EA XMI</a>
            {copyHint && <span style={{ color: "#0a7", fontSize: 12 }}>{copyHint}</span>}
          </div>
          <pre style={{ flex: 1, overflow: "auto", padding: 12, margin: 0, background: "#f7f7f7", fontSize: 12, fontFamily: "Menlo, Consolas, monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{payload.ddl_postgresql}</pre>
        </div>
      );
    }
    return renderRawLayer(tab);
  };

  const overlay = !embedded || isMaximized;
  return (
    <div
      role={embedded ? "region" : "dialog"}
      aria-modal={embedded ? undefined : true}
      aria-label="统一数据模型工作台"
      onClick={overlay && !embedded ? onClose : undefined}
      style={{
        position: overlay ? "fixed" : "relative",
        inset: overlay ? 0 : undefined,
        width: overlay ? undefined : "100%",
        height: overlay ? undefined : "100%",
        minHeight: overlay ? 0 : 620,
        padding: overlay && !isMaximized ? 24 : 0,
        boxSizing: "border-box",
        background: overlay ? "rgba(15,23,42,0.66)" : "transparent",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: overlay ? 9999 : 0,
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          background: "#fff",
          border: embedded && !isMaximized ? "1px solid #dbe3ea" : "none",
          borderRadius: isMaximized ? 0 : embedded ? 6 : 12,
          width: isMaximized ? "100%" : embedded ? "100%" : "min(1320px, 100%)",
          height: isMaximized ? "100%" : embedded ? "100%" : "min(840px, 100%)",
          minHeight: embedded && !isMaximized ? 620 : 0,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: isMaximized || embedded ? "none" : "0 24px 70px rgba(15,23,42,0.34)",
          transition: "width 150ms ease, height 150ms ease, border-radius 150ms ease",
        }}
      >
        <div style={{ padding: "12px 14px", borderBottom: "1px solid #eee", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#1e2d3d" }}>
              {embedded ? "ER 数据模型工作台" : "数据模型预览"}
            </div>
            {payload && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 11, color: "#687582", marginTop: 5 }}>
                <span style={{ padding: "3px 6px", borderRadius: 3, background: payload.derived_status === "manual" ? "#fff3d9" : "#eaf7ee", color: payload.derived_status === "manual" ? "#815d19" : "#287043", fontWeight: 500 }}>{statusLabel(payload.derived_status)}</span>
                <span>{payload.stats.entity_count} 实体</span>
                <span>{payload.stats.attribute_count} 属性</span>
                <span>{payload.stats.constraint_count} 约束</span>
                {payload.source_tag && <span style={{ fontFamily: "Menlo, Consolas, monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 360 }} title={payload.source_tag}>{payload.source_tag}</span>}
                {payload.generated_at && <span>导入于 {payload.generated_at.slice(0, 19).replace("T", " ")}</span>}
              </div>
            )}
            {payload?.derived_status === "manual" && <div style={{ marginTop: 8, padding: "7px 9px", borderRadius: 4, background: "#fff9ed", border: "1px solid #f2dfb3", color: "#795d27", fontSize: 11 }}>这是 DMT 候选结构模型：当前只有数据结构和关系假设，没有客户数据记录；字段、来源和权限仍需客户确认。</div>}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flex: "0 0 auto" }}>
            <a
              href={getDataModelXmiDownloadUrl(versionId)}
              download
              title="EA：Publish → Model Exchange → Import XMI。导入后可在包中创建类图并放入元素。"
              style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 30, boxSizing: "border-box", padding: "0 10px", borderRadius: 5, background: "#2f6f4e", color: "#fff", fontSize: 11, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
            >
              <Download size={13} />
              EA XMI
            </a>
            <button
              type="button"
              onClick={() => setIsMaximized((value) => !value)}
              title={isMaximized ? "退出全屏" : "全屏查看"}
              aria-label={isMaximized ? "还原数据模型预览窗口" : "最大化数据模型预览窗口"}
              style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 30, padding: 0, background: "#fff", border: "1px solid #d8e0e7", borderRadius: 5, cursor: "pointer", color: "#526273" }}
            >
              {isMaximized ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            {!embedded && (
              <button
                type="button"
                onClick={onClose}
                title="关闭"
                aria-label="关闭数据模型预览窗口"
                style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 30, padding: 0, background: "transparent", border: "none", borderRadius: 5, cursor: "pointer", color: "#666" }}
              >
                <X size={17} />
              </button>
            )}
          </div>
        </div>
        <div style={{ display: "flex", borderBottom: "1px solid #eee", background: "#fafafa", overflowX: "auto" }}>
          {TABS.map((item) => (
            <button key={item.key} onClick={() => setTab(item.key)} style={{ flex: "0 0 auto", padding: "8px 14px", fontSize: 12, border: "none", borderBottom: tab === item.key ? "2px solid #007aff" : "2px solid transparent", background: "transparent", color: tab === item.key ? "#007aff" : "#333", fontWeight: tab === item.key ? 500 : 400, cursor: "pointer" }}>{item.label}</button>
          ))}
        </div>
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", minHeight: 0 }}>{renderBody()}</div>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Eye, Network, Search } from "lucide-react";

type JsonObject = Record<string, any>;

interface Props {
  entities: JsonObject[];
  relationships: JsonObject[];
  domainLabels: Map<string, string>;
  onEntityOpen: (entityKey: string) => void;
}

interface EntityNodeData extends Record<string, unknown> {
  label: string;
  physicalTable: string;
  domain: string;
  domainLabel: string;
  attributes: JsonObject[];
  color: string;
  showFields: boolean;
  external: boolean;
}

const DOMAIN_COLORS = [
  "#2563eb",
  "#0f766e",
  "#7c3aed",
  "#b45309",
  "#be185d",
  "#0369a1",
  "#4d7c0f",
  "#c2410c",
  "#4338ca",
  "#047857",
];

function entityKey(entity: JsonObject, index = 0): string {
  return String(
    entity.id
      ?? entity.physical_table
      ?? entity.table
      ?? entity.name_en
      ?? entity.name_zh
      ?? `entity-${index}`,
  );
}

function entityDomain(entity: JsonObject): string {
  return String(
    entity.domain || String(entity.physical_table || "").split(".")[0] || "unassigned",
  );
}

function entityName(entity: JsonObject): string {
  return String(
    entity.name_zh || entity.name_en || entity.physical_table || entity.id || "未命名实体",
  );
}

function objectArray(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonObject => Boolean(item) && typeof item === "object")
    : [];
}

function attributeCode(attribute: JsonObject): string {
  return String(
    attribute.physical_column
      || attribute.code
      || attribute.name
      || attribute.name_en
      || "未命名字段",
  );
}

function attributeType(attribute: JsonObject): string {
  return String(
    attribute.physical_type || attribute.logical_type || attribute.datatype || "—",
  );
}

function domainColor(domain: string): string {
  let hash = 0;
  for (let index = 0; index < domain.length; index += 1) {
    hash = (hash * 31 + domain.charCodeAt(index)) >>> 0;
  }
  return DOMAIN_COLORS[hash % DOMAIN_COLORS.length];
}

function ErEntityNode({ data }: NodeProps) {
  const node = data as EntityNodeData;
  const visibleAttributes = node.showFields ? node.attributes.slice(0, 8) : [];
  const hiddenCount = node.attributes.length - visibleAttributes.length;
  return (
    <article
      style={{
        width: 274,
        overflow: "hidden",
        borderRadius: 8,
        border: `1px solid ${node.external ? "#cbd5e1" : node.color}`,
        borderTop: `4px solid ${node.color}`,
        background: node.external ? "#f8fafc" : "#fff",
        boxShadow: "0 3px 12px rgba(15,23,42,0.12)",
        opacity: node.external ? 0.78 : 1,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: node.color }} />
      <header style={{ padding: "8px 10px 7px", borderBottom: "1px solid #e8edf2" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 6,
          }}
        >
          <strong
            title={node.label}
            style={{
              minWidth: 0,
              overflow: "hidden",
              color: "#172b3a",
              fontSize: 12,
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {node.label}
          </strong>
          <span
            style={{
              flex: "0 0 auto",
              padding: "1px 5px",
              borderRadius: 8,
              background: `${node.color}18`,
              color: node.color,
              fontSize: 9,
              fontWeight: 700,
            }}
          >
            {node.external ? "外域" : node.attributes.length}
          </span>
        </div>
        <div
          title={node.physicalTable}
          style={{
            marginTop: 4,
            overflow: "hidden",
            color: "#64748b",
            fontFamily: "Menlo, Consolas, monospace",
            fontSize: 9,
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {node.physicalTable}
        </div>
        <div style={{ marginTop: 3, color: node.color, fontSize: 9 }}>
          {node.domainLabel}
        </div>
      </header>
      {visibleAttributes.length > 0 && (
        <div style={{ padding: "5px 0 6px" }}>
          {visibleAttributes.map((attribute, index) => {
            const role = String(attribute.role || "attribute").toLowerCase();
            return (
              <div
                key={`${attributeCode(attribute)}-${index}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "26px minmax(0, 1fr) auto",
                  alignItems: "center",
                  gap: 4,
                  minHeight: 20,
                  padding: "0 9px",
                  color: "#334155",
                  fontSize: 9,
                }}
              >
                <span
                  style={{
                    color: role === "pk" ? "#b45309" : role === "fk" ? "#2563eb" : "#94a3b8",
                    fontWeight: 800,
                  }}
                >
                  {role === "pk" ? "PK" : role === "fk" ? "FK" : "·"}
                </span>
                <span
                  title={attributeCode(attribute)}
                  style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                >
                  {attributeCode(attribute)}
                </span>
                <span
                  title={attributeType(attribute)}
                  style={{
                    maxWidth: 94,
                    overflow: "hidden",
                    color: "#7c8795",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {attributeType(attribute)}
                </span>
              </div>
            );
          })}
          {hiddenCount > 0 && (
            <div style={{ padding: "3px 10px 0 35px", color: "#94a3b8", fontSize: 9 }}>
              另有 {hiddenCount} 个字段 · 双击查看完整定义
            </div>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: node.color }} />
    </article>
  );
}

const nodeTypes = { erEntity: ErEntityNode };

function layoutNodes(
  entities: JsonObject[],
  domainLabels: Map<string, string>,
  focusDomain: string,
  showFields: boolean,
  baseKeys: Set<string>,
): Node[] {
  const groups = new Map<string, JsonObject[]>();
  for (const entity of entities) {
    const domain = entityDomain(entity);
    const values = groups.get(domain) || [];
    values.push(entity);
    groups.set(domain, values);
  }
  const orderedGroups = Array.from(groups.entries()).sort(([left], [right]) => {
    if (left === focusDomain) return -1;
    if (right === focusDomain) return 1;
    return left.localeCompare(right);
  });

  const groupColumnHeights = [0, 0, 0];
  const nodes: Node[] = [];
  for (const [domain, groupEntities] of orderedGroups) {
    groupEntities.sort((left, right) => entityName(left).localeCompare(entityName(right)));
    const groupColumn = groupColumnHeights.indexOf(Math.min(...groupColumnHeights));
    const groupX = groupColumn * 1040;
    const groupY = groupColumnHeights[groupColumn];
    const columns = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(groupEntities.length))));
    const rowHeight = showFields ? 286 : 142;
    groupEntities.forEach((entity, index) => {
      const key = entityKey(entity, index);
      const entityDomainValue = entityDomain(entity);
      nodes.push({
        id: key,
        type: "erEntity",
        position: {
          x: groupX + (index % columns) * 326,
          y: groupY + Math.floor(index / columns) * rowHeight,
        },
        data: {
          label: entityName(entity),
          physicalTable: String(entity.physical_table || key),
          domain: entityDomainValue,
          domainLabel: domainLabels.get(entityDomainValue) || entityDomainValue,
          attributes: objectArray(entity.attributes),
          color: domainColor(entityDomainValue),
          showFields,
          external: focusDomain !== "" && !baseKeys.has(key),
        } satisfies EntityNodeData,
        draggable: true,
      });
    });
    const rows = Math.ceil(groupEntities.length / columns);
    groupColumnHeights[groupColumn] += Math.max(1, rows) * rowHeight + 110;
  }
  return nodes;
}

function buildEdges(relationships: JsonObject[], visibleKeys: Set<string>): Edge[] {
  return relationships.flatMap((relationship, index) => {
    const source = String(relationship.source || "");
    const target = String(relationship.target || "");
    if (!visibleKeys.has(source) || !visibleKeys.has(target)) return [];
    const reference = String(relationship.type || "") === "references";
    const candidate = String(relationship.confidence || "").toLowerCase() === "medium";
    const color = candidate ? "#d97706" : reference ? "#2563eb" : "#0f766e";
    const name = String(
      relationship.source_field || relationship.type || relationship.method || "关联",
    );
    const cardinality = String(relationship.cardinality || "");
    return [{
      id: `relation-${index}-${source}-${target}`,
      source,
      target,
      type: "smoothstep",
      label: cardinality ? `${name} · ${cardinality}` : name,
      labelStyle: { fill: "#596777", fontSize: 9 },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.88 },
      labelBgPadding: [3, 2] as [number, number],
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      style: {
        stroke: color,
        strokeWidth: reference ? 1.5 : 1.2,
        strokeDasharray: reference ? undefined : "5 4",
      },
    } satisfies Edge];
  });
}

export default function DataModelErCanvas({
  entities,
  relationships,
  domainLabels,
  onEntityOpen,
}: Props) {
  const domains = useMemo(
    () => Array.from(new Set(entities.map(entityDomain))).sort((left, right) => left.localeCompare(right)),
    [entities],
  );
  const [focusDomain, setFocusDomain] = useState(
    domains.includes("dmt_geo") ? "dmt_geo" : domains[0] || "",
  );
  const [query, setQuery] = useState("");
  const [includeNeighbours, setIncludeNeighbours] = useState(false);
  const [showFields, setShowFields] = useState(true);

  useEffect(() => {
    if (focusDomain && !domains.includes(focusDomain)) {
      setFocusDomain(domains.includes("dmt_geo") ? "dmt_geo" : domains[0] || "");
    }
  }, [domains, focusDomain]);

  const graph = useMemo(() => {
    const queryValue = query.trim().toLowerCase();
    const base = entities.filter((entity, index) => {
      if (focusDomain && entityDomain(entity) !== focusDomain) return false;
      if (!queryValue) return true;
      return [
        entityKey(entity, index),
        entityName(entity),
        entity.physical_table,
        ...objectArray(entity.attributes).flatMap(attribute => [
          attributeCode(attribute),
          attribute.name_zh,
        ]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(queryValue);
    });
    const baseKeys = new Set(base.map((entity, index) => entityKey(entity, index)));
    const visibleKeys = new Set(baseKeys);
    if (includeNeighbours && focusDomain) {
      for (const relationship of relationships) {
        const source = String(relationship.source || "");
        const target = String(relationship.target || "");
        if (baseKeys.has(source)) visibleKeys.add(target);
        if (baseKeys.has(target)) visibleKeys.add(source);
      }
    }
    const visibleEntities = entities.filter((entity, index) =>
      visibleKeys.has(entityKey(entity, index)),
    );
    const nodes = layoutNodes(
      visibleEntities,
      domainLabels,
      focusDomain,
      showFields,
      baseKeys,
    );
    return {
      nodes,
      edges: buildEdges(relationships, new Set(nodes.map(node => node.id))),
      baseCount: base.length,
    };
  }, [domainLabels, entities, focusDomain, includeNeighbours, query, relationships, showFields]);

  const graphKey = `${focusDomain}|${query}|${includeNeighbours}|${showFields}|${graph.nodes.length}`;
  return (
    <div style={{ display: "flex", flex: 1, flexDirection: "column", minHeight: 0 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
          padding: "8px 10px",
          borderBottom: "1px solid #e5eaf0",
          background: "#fbfcfd",
        }}
      >
        <Network size={15} color="#315d78" aria-hidden="true" />
        <select
          value={focusDomain}
          onChange={event => setFocusDomain(event.target.value)}
          aria-label="ER画布业务域"
          style={{ minWidth: 210, padding: "6px 8px", border: "1px solid #cbd5df", borderRadius: 5 }}
        >
          <option value="">全部业务域</option>
          {domains.map(domain => (
            <option key={domain} value={domain}>
              {domainLabels.get(domain) || domain} ({entities.filter(entity => entityDomain(entity) === domain).length})
            </option>
          ))}
        </select>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            minWidth: 240,
            flex: "1 1 280px",
            border: "1px solid #cbd5df",
            borderRadius: 5,
            background: "#fff",
          }}
        >
          <Search size={13} color="#778594" style={{ marginLeft: 8 }} aria-hidden="true" />
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="搜索实体、表名或字段"
            style={{ minWidth: 0, flex: 1, padding: "6px 8px", border: "none", outline: "none" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 5, color: "#526273", fontSize: 11 }}>
          <input
            type="checkbox"
            checked={includeNeighbours}
            disabled={!focusDomain}
            onChange={event => setIncludeNeighbours(event.target.checked)}
          />
          包含一跳外域实体
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 5, color: "#526273", fontSize: 11 }}>
          <input
            type="checkbox"
            checked={showFields}
            onChange={event => setShowFields(event.target.checked)}
          />
          显示字段
        </label>
        <span
          title="节点可拖拽调整当前视图；模型内容仍为不可变快照。"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "3px 7px",
            borderRadius: 10,
            background: "#eaf2f8",
            color: "#315d78",
            fontSize: 10,
            fontWeight: 700,
          }}
        >
          <Eye size={11} aria-hidden="true" />
          只读画布
        </span>
        <span style={{ color: "#748292", fontSize: 10 }}>
          {graph.baseCount} 个域内实体 · {graph.nodes.length} 个可见实体 · {graph.edges.length} 条关系
        </span>
      </div>
      <div style={{ position: "relative", flex: 1, minHeight: 0, background: "#f5f7fa" }}>
        {graph.nodes.length ? (
          <ReactFlow
            key={graphKey}
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.16, minZoom: 0.18, maxZoom: 1 }}
            minZoom={0.08}
            maxZoom={2}
            nodesConnectable={false}
            deleteKeyCode={null}
            onNodeDoubleClick={(_, node) => onEntityOpen(node.id)}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d7dee7" gap={22} size={1} />
            <MiniMap
              pannable
              zoomable
              nodeColor={node => String((node.data as EntityNodeData).color || "#64748b")}
              maskColor="rgba(241,245,249,0.76)"
              style={{ width: 180, height: 112, border: "1px solid #d7dee7" }}
            />
            <Controls showInteractive={false} />
          </ReactFlow>
        ) : (
          <div
            style={{
              display: "grid",
              height: "100%",
              placeItems: "center",
              color: "#7a8794",
              fontSize: 12,
            }}
          >
            没有匹配的实体，请调整业务域或搜索条件。
          </div>
        )}
        <div
          style={{
            position: "absolute",
            left: 12,
            bottom: 12,
            zIndex: 5,
            padding: "5px 8px",
            border: "1px solid #dbe2e8",
            borderRadius: 5,
            background: "rgba(255,255,255,0.92)",
            color: "#657382",
            fontSize: 10,
          }}
        >
          蓝色实线：规范引用 · 绿色虚线：业务关系 · 橙色：候选关系 · 双击实体查看完整字段
        </div>
      </div>
    </div>
  );
}

import React, { useEffect, useState } from "react";
import {
  MarketDiffResponse,
  MarketStandardItem,
  getMarketDiff,
  listMarketStandards,
} from "./standardsApi";

interface Props {
  selectedVersionId: string | null;
  onSelectVersion: (vid: string) => void;
}

export default function MarketSubTab({selectedVersionId, onSelectVersion}: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MarketStandardItem[]>([]);
  const [selected, setSelected] = useState<MarketStandardItem | null>(null);
  const [sourceVersionId, setSourceVersionId] = useState(selectedVersionId || "");
  const [targetVersionId, setTargetVersionId] = useState("");
  const [diff, setDiff] = useState<MarketDiffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [diffBusy, setDiffBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCatalog = () => {
    setLoading(true);
    setError(null);
    listMarketStandards({query: query.trim() || undefined, limit: 50})
      .then(r => {
        setItems(r.items);
        setSelected(current => {
          if (current && r.items.some(i => i.version_id === current.version_id)) {
            return current;
          }
          return r.items[0] || null;
        });
      })
      .catch((e: any) => setError(e?.message || "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(loadCatalog, []);

  useEffect(() => {
    setSourceVersionId(selectedVersionId || "");
  }, [selectedVersionId]);

  useEffect(() => {
    if (selected) setTargetVersionId(selected.version_id);
  }, [selected]);

  const runDiff = async () => {
    if (!sourceVersionId || !targetVersionId) return;
    setDiffBusy(true);
    setError(null);
    try {
      const result = await getMarketDiff(sourceVersionId, targetVersionId);
      setDiff(result);
    } catch (e: any) {
      setDiff(null);
      setError(e?.message || "diff 失败");
    } finally {
      setDiffBusy(false);
    }
  };

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "36% 64%",
      height: "100%", minHeight: 0,
    }}>
      <div style={{
        padding: 10, borderRight: "1px solid #e5e7eb",
        overflow: "auto",
      }}>
        <div style={{display: "flex", gap: 6, marginBottom: 8}}>
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") loadCatalog(); }}
            placeholder="搜索标准、编码、版本"
            style={{
              flex: 1, minWidth: 0, padding: "6px 8px",
              border: "1px solid #d1d5db", borderRadius: 4,
              fontSize: 12,
            }}
          />
          <button
            onClick={loadCatalog}
            disabled={loading}
            style={buttonStyle}>
            搜索
          </button>
        </div>
        {error && (
          <div style={{
            marginBottom: 8, padding: 8, border: "1px solid #fecaca",
            background: "#fef2f2", color: "#991b1b", borderRadius: 4,
            fontSize: 12,
          }}>
            {error}
          </div>
        )}
        {loading && <div style={mutedStyle}>加载中</div>}
        {!loading && items.length === 0 && (
          <div style={mutedStyle}>暂无 released 标准</div>
        )}
        {items.map(item => (
          <button
            key={item.version_id}
            onClick={() => setSelected(item)}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: 10, marginBottom: 6, borderRadius: 4,
              border: selected?.version_id === item.version_id
                ? "1px solid #0a7" : "1px solid #e5e7eb",
              background: selected?.version_id === item.version_id
                ? "#ecfdf5" : "#fff",
              cursor: "pointer",
            }}>
            <div style={{fontSize: 13, fontWeight: 650, color: "#111827"}}>
              {item.doc_code} · {item.version_label}
            </div>
            <div style={{
              marginTop: 3, fontSize: 12, color: "#374151",
              overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {item.title}
            </div>
            <div style={{display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6}}>
              <Chip label="条款" value={item.asset_counts.clauses}/>
              <Chip label="要素" value={item.asset_counts.data_elements}/>
              <Chip label="术语" value={item.asset_counts.terms}/>
              <Chip label="值域" value={item.asset_counts.value_domains}/>
            </div>
          </button>
        ))}
      </div>

      <div style={{padding: 12, overflow: "auto"}}>
        {selected ? (
          <>
            <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "flex-start", gap: 12, marginBottom: 12,
            }}>
              <div>
                <div style={{fontSize: 16, fontWeight: 700, color: "#111827"}}>
                  {selected.title}
                </div>
                <div style={{fontSize: 12, color: "#6b7280", marginTop: 4}}>
                  {selected.doc_code} · {selected.version_label} · {selected.source_type}
                </div>
              </div>
              <button
                onClick={() => onSelectVersion(selected.version_id)}
                style={outlineButtonStyle}>
                设为当前版本
              </button>
            </div>

            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr auto",
              gap: 8, alignItems: "end", marginBottom: 12,
            }}>
              <Field
                label="Source version"
                value={sourceVersionId}
                onChange={setSourceVersionId}
              />
              <Field
                label="Target version"
                value={targetVersionId}
                onChange={setTargetVersionId}
              />
              <button
                onClick={runDiff}
                disabled={diffBusy || !sourceVersionId || !targetVersionId}
                style={buttonStyle}>
                Diff
              </button>
            </div>

            {diff && (
              <>
                <div style={{
                  display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10,
                }}>
                  <Chip label="新增" value={diff.summary.added}/>
                  <Chip label="删除" value={diff.summary.removed}/>
                  <Chip label="变化" value={diff.summary.changed}/>
                  <Chip label="不变" value={diff.summary.unchanged}/>
                </div>
                <div style={{
                  border: "1px solid #e5e7eb", borderRadius: 4,
                  overflow: "hidden",
                }}>
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "120px 90px 1fr 1fr",
                    gap: 0, background: "#f9fafb", fontSize: 12,
                    fontWeight: 650, color: "#374151",
                  }}>
                    <Cell>资产</Cell>
                    <Cell>类型</Cell>
                    <Cell>Source</Cell>
                    <Cell>Target</Cell>
                  </div>
                  {diff.changes.length === 0 && (
                    <div style={{padding: 10, fontSize: 12, color: "#6b7280"}}>
                      无差异
                    </div>
                  )}
                  {diff.changes.map((change, idx) => (
                    <div
                      key={`${change.asset_type}-${change.key}-${idx}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "120px 90px 1fr 1fr",
                        borderTop: "1px solid #e5e7eb",
                        fontSize: 12,
                      }}>
                      <Cell>{change.asset_type}<br/>{change.key}</Cell>
                      <Cell>{change.change_type}</Cell>
                      <Cell>{change.source_label || "-"}</Cell>
                      <Cell>{change.target_label || "-"}</Cell>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <div style={mutedStyle}>请选择一个 released 标准</div>
        )}
      </div>
    </div>
  );
}

function Chip({label, value}: {label: string; value: React.ReactNode}) {
  return (
    <span style={{
      display: "inline-flex", gap: 4, alignItems: "center",
      padding: "2px 6px", border: "1px solid #e5e7eb",
      borderRadius: 4, background: "#fff", color: "#374151",
      fontSize: 11, lineHeight: "18px",
    }}>
      <span style={{color: "#6b7280"}}>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function Field({label, value, onChange}: {
  label: string; value: string; onChange: (value: string) => void;
}) {
  return (
    <label style={{display: "block"}}>
      <div style={{fontSize: 11, color: "#6b7280", marginBottom: 3}}>
        {label}
      </div>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: "100%", boxSizing: "border-box", padding: "6px 8px",
          border: "1px solid #d1d5db", borderRadius: 4, fontSize: 12,
        }}
      />
    </label>
  );
}

function Cell({children}: {children: React.ReactNode}) {
  return (
    <div style={{
      padding: "8px 10px", minWidth: 0, overflowWrap: "anywhere",
      borderRight: "1px solid #e5e7eb",
    }}>
      {children}
    </div>
  );
}

const mutedStyle: React.CSSProperties = {
  padding: 12,
  color: "#6b7280",
  fontSize: 12,
};

const buttonStyle: React.CSSProperties = {
  padding: "6px 10px",
  background: "#0a7",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 12,
};

const outlineButtonStyle: React.CSSProperties = {
  padding: "6px 10px",
  background: "#fff",
  color: "#047857",
  border: "1px solid #0a7",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 12,
  whiteSpace: "nowrap",
};

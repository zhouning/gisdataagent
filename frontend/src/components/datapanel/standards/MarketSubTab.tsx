import React, { useEffect, useState } from "react";
import {
  MarketDiffResponse,
  MarketListing,
  MarketStandardItem,
  MarketSubscription,
  getMarketDiff,
  listMarketListings,
  listMarketSubscriptions,
  listMarketStandards,
  markMarketSubscriptionSeen,
  reviewMarketListing,
  submitMarketListing,
  subscribeMarketStandard,
  unsubscribeMarketSubscription,
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
  const [subscriptions, setSubscriptions] = useState<MarketSubscription[]>([]);
  const [reviewItems, setReviewItems] = useState<MarketListing[]>([]);
  const [loading, setLoading] = useState(false);
  const [diffBusy, setDiffBusy] = useState(false);
  const [subsBusy, setSubsBusy] = useState(false);
  const [auditBusy, setAuditBusy] = useState(false);
  const [auditMessage, setAuditMessage] = useState<string | null>(null);
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

  const loadSubscriptions = () => {
    listMarketSubscriptions()
      .then(r => setSubscriptions(r.subscriptions))
      .catch(() => setSubscriptions([]));
  };

  useEffect(() => {
    loadCatalog();
    loadSubscriptions();
  }, []);

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

  const selectedSubscription = selected
    ? subscriptions.find(s => s.document_id === selected.document_id) || null
    : null;

  const subscribeSelected = async () => {
    if (!selected) return;
    setSubsBusy(true);
    setError(null);
    try {
      await subscribeMarketStandard(selected.version_id);
      loadSubscriptions();
    } catch (e: any) {
      setError(e?.message || "订阅失败");
    } finally {
      setSubsBusy(false);
    }
  };

  const cancelSubscription = async (subscriptionId: string) => {
    setSubsBusy(true);
    setError(null);
    try {
      await unsubscribeMarketSubscription(subscriptionId);
      loadSubscriptions();
    } catch (e: any) {
      setError(e?.message || "取消订阅失败");
    } finally {
      setSubsBusy(false);
    }
  };

  const markSeen = async (subscriptionId: string) => {
    setSubsBusy(true);
    setError(null);
    try {
      await markMarketSubscriptionSeen(subscriptionId);
      loadSubscriptions();
    } catch (e: any) {
      setError(e?.message || "标记已读失败");
    } finally {
      setSubsBusy(false);
    }
  };

  const submitSelectedListing = async () => {
    if (!selected) return;
    setAuditBusy(true);
    setError(null);
    setAuditMessage(null);
    try {
      await submitMarketListing(selected.version_id);
      setAuditMessage("已提交");
      loadCatalog();
    } catch (e: any) {
      setError(e?.message || "提交审核失败");
    } finally {
      setAuditBusy(false);
    }
  };

  const loadAuditQueue = async () => {
    setAuditBusy(true);
    setAuditMessage(null);
    try {
      const result = await listMarketListings({status: "submitted", limit: 20});
      setReviewItems(result.items);
    } catch (e: any) {
      setAuditMessage(e?.message || "加载审核队列失败");
    } finally {
      setAuditBusy(false);
    }
  };

  const reviewListing = async (
    listingId: string,
    decision: "approved" | "rejected",
  ) => {
    setAuditBusy(true);
    setError(null);
    try {
      await reviewMarketListing(listingId, decision);
      await loadAuditQueue();
      loadCatalog();
    } catch (e: any) {
      setError(e?.message || "审核失败");
    } finally {
      setAuditBusy(false);
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
              <Chip label="上架" value={marketStatusLabel(item.market_status)}/>
            </div>
          </button>
        ))}
        <div style={{
          marginTop: 14, paddingTop: 10, borderTop: "1px solid #e5e7eb",
        }}>
          <div style={{
            fontSize: 13, fontWeight: 650, color: "#111827",
            marginBottom: 8,
          }}>
            我的订阅
          </div>
          {subscriptions.length === 0 && (
            <div style={mutedStyle}>暂无订阅</div>
          )}
          {subscriptions.map(sub => (
            <div key={sub.id}
                 style={{
                   padding: 8, marginBottom: 6, borderRadius: 4,
                   border: "1px solid #e5e7eb", background: "#fff",
                 }}>
              <div style={{
                display: "flex", justifyContent: "space-between", gap: 8,
              }}>
                <div style={{minWidth: 0}}>
                  <div style={{
                    fontSize: 12, fontWeight: 650, color: "#111827",
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {sub.doc_code} · {sub.latest_version_label || "-"}
                  </div>
                  <div style={{
                    fontSize: 11, color: "#6b7280", marginTop: 2,
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {sub.title}
                  </div>
                </div>
                {sub.has_update && <Chip label="更新" value="new"/>}
              </div>
              <div style={{display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6}}>
                {sub.latest_version_id && (
                  <button
                    onClick={() => onSelectVersion(sub.latest_version_id!)}
                    style={smallButtonStyle}>
                    设为当前
                  </button>
                )}
                <button
                  onClick={() => markSeen(sub.id)}
                  disabled={subsBusy}
                  style={smallButtonStyle}>
                  标记已读
                </button>
                <button
                  onClick={() => cancelSubscription(sub.id)}
                  disabled={subsBusy}
                  style={smallDangerButtonStyle}>
                  取消订阅
                </button>
              </div>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 14, paddingTop: 10, borderTop: "1px solid #e5e7eb",
        }}>
          <div style={{
            display: "flex", justifyContent: "space-between",
            alignItems: "center", gap: 8, marginBottom: 8,
          }}>
            <div style={{fontSize: 13, fontWeight: 650, color: "#111827"}}>
              市场审核
            </div>
            <button
              onClick={loadAuditQueue}
              disabled={auditBusy}
              style={smallButtonStyle}>
              刷新
            </button>
          </div>
          {auditMessage && (
            <div style={{
              marginBottom: 8, padding: 6, border: "1px solid #e5e7eb",
              background: "#f9fafb", color: "#374151", borderRadius: 4,
              fontSize: 11,
            }}>
              {auditMessage}
            </div>
          )}
          {reviewItems.length === 0 && (
            <div style={mutedStyle}>暂无待审</div>
          )}
          {reviewItems.map(item => (
            <div key={item.id}
                 style={{
                   padding: 8, marginBottom: 6, borderRadius: 4,
                   border: "1px solid #e5e7eb", background: "#fff",
                 }}>
              <div style={{
                fontSize: 12, fontWeight: 650, color: "#111827",
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {item.doc_code} · {item.version_label}
              </div>
              <div style={{
                fontSize: 11, color: "#6b7280", marginTop: 2,
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {item.title}
              </div>
              <div style={{display: "flex", gap: 4, marginTop: 6}}>
                <button
                  onClick={() => reviewListing(item.id, "approved")}
                  disabled={auditBusy}
                  style={smallButtonStyle}>
                  通过
                </button>
                <button
                  onClick={() => reviewListing(item.id, "rejected")}
                  disabled={auditBusy}
                  style={smallDangerButtonStyle}>
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
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
              <div style={{
                display: "flex", gap: 6, flexWrap: "wrap",
                justifyContent: "flex-end",
              }}>
                <button
                  onClick={() => onSelectVersion(selected.version_id)}
                  style={outlineButtonStyle}>
                  设为当前版本
                </button>
                <button
                  onClick={submitSelectedListing}
                  disabled={auditBusy || selected.market_status === "approved"}
                  style={outlineButtonStyle}>
                  {selected.market_status === "approved" ? "已通过审核" : "提交审核"}
                </button>
                {selectedSubscription ? (
                  <button
                    onClick={() => cancelSubscription(selectedSubscription.id)}
                    disabled={subsBusy}
                    style={outlineButtonStyle}>
                    取消订阅
                  </button>
                ) : (
                  <button
                    onClick={subscribeSelected}
                    disabled={subsBusy}
                    style={buttonStyle}>
                    订阅
                  </button>
                )}
              </div>
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

function marketStatusLabel(status: string | null | undefined) {
  switch (status) {
    case "approved":
      return "已通过";
    case "submitted":
      return "待审";
    case "rejected":
      return "已拒绝";
    case "withdrawn":
      return "已撤回";
    default:
      return "已上架";
  }
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

const smallButtonStyle: React.CSSProperties = {
  padding: "3px 6px",
  background: "#fff",
  color: "#047857",
  border: "1px solid #a7f3d0",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 11,
};

const smallDangerButtonStyle: React.CSSProperties = {
  ...smallButtonStyle,
  color: "#b91c1c",
  border: "1px solid #fecaca",
};

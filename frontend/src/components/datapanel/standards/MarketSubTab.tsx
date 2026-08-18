import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../i18n";
import {
  MarketDiffResponse,
  MarketListing,
  MarketStandardItem,
  MarketSubscription,
  MarketVisibilityScope,
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
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<MarketStandardItem[]>([]);
  const [selected, setSelected] = useState<MarketStandardItem | null>(null);
  const [sourceVersionId, setSourceVersionId] = useState(selectedVersionId || "");
  const [targetVersionId, setTargetVersionId] = useState("");
  const [diff, setDiff] = useState<MarketDiffResponse | null>(null);
  const [subscriptions, setSubscriptions] = useState<MarketSubscription[]>([]);
  const [reviewItems, setReviewItems] = useState<MarketListing[]>([]);
  const [visibilityScope, setVisibilityScope] =
    useState<MarketVisibilityScope>("public");
  const [ownerOrgId, setOwnerOrgId] = useState("");
  const [allowedOrgInput, setAllowedOrgInput] = useState("");
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
      .catch((e: any) => setError(t("standards.market.errors.load", {
        message: e?.message || t("errors.unknown"),
      })))
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
      setError(t("standards.market.errors.diff", {message: e?.message || t("errors.unknown")}));
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
      setError(t("standards.market.errors.subscribe", {message: e?.message || t("errors.unknown")}));
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
      setError(t("standards.market.errors.unsubscribe", {message: e?.message || t("errors.unknown")}));
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
      setError(t("standards.market.errors.markSeen", {message: e?.message || t("errors.unknown")}));
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
      await submitMarketListing(selected.version_id, {
        visibility_scope: visibilityScope,
        owner_org_id: ownerOrgId.trim() || null,
        allowed_org_ids: parseOrgList(allowedOrgInput),
      });
      setAuditMessage(t("standards.market.audit.submitted"));
      loadCatalog();
    } catch (e: any) {
      setError(t("standards.market.errors.submit", {message: e?.message || t("errors.unknown")}));
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
      setAuditMessage(t("standards.market.errors.auditQueue", {message: e?.message || t("errors.unknown")}));
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
      setError(t("standards.market.errors.review", {message: e?.message || t("errors.unknown")}));
    } finally {
      setAuditBusy(false);
    }
  };

  const marketStatusLabel = (status: string | null | undefined) =>
    t(`standards.market.status.${status || "listed"}`, {
      defaultValue: t("standards.market.status.listed"),
    });

  const visibilityLabel = (scope: string | null | undefined) =>
    t(`standards.market.visibility.${scope || "public"}`, {
      defaultValue: t("standards.market.visibility.public"),
    });

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "36% 64%",
      height: "100%", minHeight: 0,
    }}>
      <div style={{
        padding: 10, borderInlineEnd: "1px solid #e5e7eb",
        overflow: "auto",
      }}>
        <div style={{display: "flex", gap: 6, marginBottom: 8}}>
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") loadCatalog(); }}
            placeholder={t("standards.market.searchPlaceholder")}
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
            {t("standards.market.search")}
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
        {loading && <div style={mutedStyle}>{t("standards.market.loading")}</div>}
        {!loading && items.length === 0 && (
          <div style={mutedStyle}>{t("standards.market.emptyReleased")}</div>
        )}
        {items.map(item => (
          <button
            key={item.version_id}
            onClick={() => setSelected(item)}
            style={{
              display: "block", width: "100%", textAlign: "start",
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
              <Chip label={t("standards.market.assets.clauses")} value={formatNumber(item.asset_counts.clauses)}/>
              <Chip label={t("standards.market.assets.dataElements")} value={formatNumber(item.asset_counts.data_elements)}/>
              <Chip label={t("standards.market.assets.terms")} value={formatNumber(item.asset_counts.terms)}/>
              <Chip label={t("standards.market.assets.valueDomains")} value={formatNumber(item.asset_counts.value_domains)}/>
              <Chip label={t("standards.market.listingStatus")} value={marketStatusLabel(item.market_status)}/>
              <Chip label={t("standards.market.scope")} value={visibilityLabel(item.visibility_scope)}/>
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
            {t("standards.market.subscriptions.title")}
          </div>
          {subscriptions.length === 0 && (
            <div style={mutedStyle}>{t("standards.market.subscriptions.empty")}</div>
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
                {sub.has_update && <Chip label={t("standards.market.subscriptions.update")} value={t("standards.market.subscriptions.new")}/>}
              </div>
              <div style={{display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6}}>
                {sub.latest_version_id && (
                  <button
                    onClick={() => onSelectVersion(sub.latest_version_id!)}
                    style={smallButtonStyle}>
                    {t("standards.market.actions.setCurrent")}
                  </button>
                )}
                <button
                  onClick={() => markSeen(sub.id)}
                  disabled={subsBusy}
                  style={smallButtonStyle}>
                  {t("standards.market.actions.markSeen")}
                </button>
                <button
                  onClick={() => cancelSubscription(sub.id)}
                  disabled={subsBusy}
                  style={smallDangerButtonStyle}>
                  {t("standards.market.actions.unsubscribe")}
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
              {t("standards.market.audit.title")}
            </div>
            <button
              onClick={loadAuditQueue}
              disabled={auditBusy}
              style={smallButtonStyle}>
              {t("standards.market.actions.refresh")}
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
            <div style={mutedStyle}>{t("standards.market.audit.empty")}</div>
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
                <Chip label={t("standards.market.scope")} value={visibilityLabel(item.visibility_scope)}/>
                <button
                  onClick={() => reviewListing(item.id, "approved")}
                  disabled={auditBusy}
                  style={smallButtonStyle}>
                  {t("standards.market.actions.approve")}
                </button>
                <button
                  onClick={() => reviewListing(item.id, "rejected")}
                  disabled={auditBusy}
                  style={smallDangerButtonStyle}>
                  {t("standards.market.actions.reject")}
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
                  {selected.doc_code} · {selected.version_label} · {t(`standards.ingest.sourceTypes.${selected.source_type}`, {defaultValue: selected.source_type})}
                </div>
              </div>
              <div style={{
                display: "flex", gap: 6, flexWrap: "wrap",
                justifyContent: "flex-end",
              }}>
                <button
                  onClick={() => onSelectVersion(selected.version_id)}
                  style={outlineButtonStyle}>
                  {t("standards.market.actions.setCurrentVersion")}
                </button>
                <button
                  onClick={submitSelectedListing}
                  disabled={auditBusy || selected.market_status === "approved"}
                  style={outlineButtonStyle}>
                  {selected.market_status === "approved"
                    ? t("standards.market.actions.reviewApproved")
                    : t("standards.market.actions.submitReview")}
                </button>
                {selectedSubscription ? (
                  <button
                    onClick={() => cancelSubscription(selectedSubscription.id)}
                    disabled={subsBusy}
                    style={outlineButtonStyle}>
                    {t("standards.market.actions.unsubscribe")}
                  </button>
                ) : (
                  <button
                    onClick={subscribeSelected}
                    disabled={subsBusy}
                    style={buttonStyle}>
                    {t("standards.market.actions.subscribe")}
                  </button>
                )}
              </div>
            </div>

            <div style={{
              display: "grid",
              gridTemplateColumns: "140px 1fr 1fr",
              gap: 8,
              alignItems: "end",
              marginBottom: 12,
            }}>
              <label style={{display: "block"}}>
                <div style={{fontSize: 11, color: "#6b7280", marginBottom: 3}}>
                  {t("standards.market.visibilityLabel")}
                </div>
                <select
                  value={visibilityScope}
                  onChange={e => setVisibilityScope(e.target.value as MarketVisibilityScope)}
                  style={{
                    width: "100%", boxSizing: "border-box",
                    padding: "6px 8px", border: "1px solid #d1d5db",
                    borderRadius: 4, fontSize: 12, background: "#fff",
                  }}>
                  <option value="public">{t("standards.market.visibility.public")}</option>
                  <option value="organization">{t("standards.market.visibility.organization")}</option>
                  <option value="private">{t("standards.market.visibility.private")}</option>
                </select>
              </label>
              <Field
                label={t("standards.market.ownerOrg")}
                value={ownerOrgId}
                onChange={setOwnerOrgId}
              />
              <Field
                label={t("standards.market.allowedOrgs")}
                value={allowedOrgInput}
                onChange={setAllowedOrgInput}
              />
            </div>

            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr auto",
              gap: 8, alignItems: "end", marginBottom: 12,
            }}>
              <Field
                label={t("standards.market.sourceVersion")}
                value={sourceVersionId}
                onChange={setSourceVersionId}
              />
              <Field
                label={t("standards.market.targetVersion")}
                value={targetVersionId}
                onChange={setTargetVersionId}
              />
              <button
                onClick={runDiff}
                disabled={diffBusy || !sourceVersionId || !targetVersionId}
                style={buttonStyle}>
                {diffBusy ? t("standards.market.diff.running") : t("standards.market.diff.action")}
              </button>
            </div>

            {diff && (
              <>
                <div style={{
                  display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10,
                }}>
                  <Chip label={t("standards.market.diff.added")} value={formatNumber(diff.summary.added)}/>
                  <Chip label={t("standards.market.diff.removed")} value={formatNumber(diff.summary.removed)}/>
                  <Chip label={t("standards.market.diff.changed")} value={formatNumber(diff.summary.changed)}/>
                  <Chip label={t("standards.market.diff.unchanged")} value={formatNumber(diff.summary.unchanged)}/>
                  <Chip label={t("standards.market.diff.fieldChanges")} value={formatNumber(diff.summary.field_changes || 0)}/>
                </div>
                {(diff.summary.review_hints || []).length > 0 && (
                  <div style={{
                    display: "grid", gap: 6, marginBottom: 10,
                    fontSize: 12,
                  }}>
                    {(diff.summary.review_hints || []).map(hint => (
                      <div
                        key={hint.code}
                        style={{
                          border: "1px solid #fde68a",
                          background: hint.level === "high" ? "#fef2f2" : "#fffbeb",
                          borderRadius: 4,
                          padding: "6px 8px",
                          color: "#7c2d12",
                        }}>
                        {hint.message} ({formatNumber(hint.count)})
                      </div>
                    ))}
                  </div>
                )}
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
                    <Cell>{t("standards.market.diff.asset")}</Cell>
                    <Cell>{t("standards.market.diff.type")}</Cell>
                    <Cell>{t("standards.market.diff.source")}</Cell>
                    <Cell>{t("standards.market.diff.target")}</Cell>
                  </div>
                  {diff.changes.length === 0 && (
                    <div style={{padding: 10, fontSize: 12, color: "#6b7280"}}>
                      {t("standards.market.diff.empty")}
                    </div>
                  )}
                  {diff.changes.map((change, idx) => (
                    <React.Fragment key={`${change.asset_type}-${change.key}-${idx}`}>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "120px 90px 1fr 1fr",
                          borderTop: "1px solid #e5e7eb",
                          fontSize: 12,
                        }}>
                        <Cell>{t(`standards.market.assetTypes.${change.asset_type}`, {defaultValue: change.asset_type})}<br/>{change.key}</Cell>
                        <Cell>
                          {t(`standards.market.changeTypes.${change.change_type}`, {defaultValue: change.change_type})}
                          {!!change.field_change_count && (
                            <div style={{color: "#6b7280", marginTop: 4}}>
                              {t("standards.market.diff.fieldCount", {count: formatNumber(change.field_change_count)})}
                            </div>
                          )}
                        </Cell>
                        <Cell>{change.source_label || "-"}</Cell>
                        <Cell>{change.target_label || "-"}</Cell>
                      </div>
                      {(change.field_changes || []).map(field => (
                        <div
                          key={`${change.asset_type}-${change.key}-${field.field}`}
                          style={{
                            display: "grid",
                            gridTemplateColumns: "120px 90px 1fr 1fr",
                            borderTop: "1px solid #f3f4f6",
                            background: "#fcfcfd",
                            fontSize: 12,
                          }}>
                          <Cell></Cell>
                          <Cell>{field.label}</Cell>
                          <Cell>{formatDiffValue(field.source_value)}</Cell>
                          <Cell>{formatDiffValue(field.target_value)}</Cell>
                        </div>
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <div style={mutedStyle}>{t("standards.market.selectReleased")}</div>
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

function parseOrgList(raw: string) {
  return raw
    .split(/[,\s]+/)
    .map(v => v.trim())
    .filter((v, idx, arr) => v.length > 0 && arr.indexOf(v) === idx);
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

function Cell({children}: {children?: React.ReactNode}) {
  return (
    <div style={{
      padding: "8px 10px", minWidth: 0, overflowWrap: "anywhere",
      borderInlineEnd: "1px solid #e5e7eb",
    }}>
      {children}
    </div>
  );
}

function formatDiffValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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

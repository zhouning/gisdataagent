import React, { useEffect, useMemo, useState } from "react";
import {
  listOutboxEvents,
  retryOutboxEvent,
  retryOutboxEvents,
} from "../standardsApi";
import type { OutboxCounts, OutboxEvent, OutboxStatus } from "../standardsApi";

interface Props {
  refreshTick: number;
  onRetryComplete: () => void;
}

const STATUSES: OutboxStatus[] = ["failed", "pending", "in_flight", "done"];
const EMPTY_COUNTS: OutboxCounts = {
  pending: 0,
  in_flight: 0,
  done: 0,
  failed: 0,
};
const STATUS_COLORS: Record<OutboxStatus, string> = {
  pending: "#888",
  in_flight: "#b36b00",
  done: "#0a7",
  failed: "#c33",
};
const RETRYABLE = new Set<OutboxStatus>(["failed", "in_flight"]);

const normalizeCounts = (counts?: Partial<OutboxCounts>): OutboxCounts => ({
  ...EMPTY_COUNTS,
  ...(counts ?? {}),
});

const messageOf = (value: unknown) =>
  value instanceof Error ? value.message : String(value);

const shortText = (value: string | null, max = 96) => {
  if (!value) return "无错误";
  return value.length > max ? `${value.slice(0, max)}...` : value;
};

const formatDate = (value: string | null) => {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
};

const formatPayload = (payload: Record<string, any>) => {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
};

const summarizeSkipped = (
  skipped: {id: string; reason?: string}[],
  max = 3,
) => {
  if (skipped.length === 0) return "";
  const reasons = skipped.slice(0, max)
    .map(s => `${s.id.slice(0, 8)}: ${s.reason ?? "skipped"}`);
  const suffix = skipped.length > max ? `; +${skipped.length - max}` : "";
  return ` (${reasons.join("; ")}${suffix})`;
};

const shortId = (id: string) => id.length > 8 ? id.slice(0, 8) : id;

export default function OutboxDeadLetterPanel({
  refreshTick,
  onRetryComplete,
}: Props) {
  const [status, setStatus] = useState<OutboxStatus>("failed");
  const [loadedStatus, setLoadedStatus] = useState<OutboxStatus | null>(null);
  const [events, setEvents] = useState<OutboxEvent[]>([]);
  const [counts, setCounts] = useState<OutboxCounts>(EMPTY_COUNTS);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [localRefreshTick, setLocalRefreshTick] = useState(0);

  useEffect(() => {
    setSelectedIds(new Set());
    setExpandedEventId(null);
  }, [status]);

  useEffect(() => {
    let cancelled = false;

    setBusy(true);
    setError(null);
    listOutboxEvents({status, limit: 50})
      .then(r => {
        if (cancelled) return;
        setEvents(r.events);
        setLoadedStatus(status);
        setCounts(normalizeCounts(r.counts));
        setSelectedIds(prev => {
          const visibleRetryableIds = new Set(
            r.events.filter(e => RETRYABLE.has(e.status)).map(e => e.id),
          );
          return new Set(Array.from(prev).filter(id => visibleRetryableIds.has(id)));
        });
        setExpandedEventId(current =>
          current && !r.events.some(e => e.id === current) ? null : current,
        );
      })
      .catch(e => {
        if (!cancelled) setError(`加载失败: ${messageOf(e)}`);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [status, refreshTick, localRefreshTick]);

  const visibleEvents = useMemo(
    () => loadedStatus === status ? events : [],
    [events, loadedStatus, status],
  );

  const selectedRetryableIds = useMemo(
    () => visibleEvents
      .filter(e => selectedIds.has(e.id) && RETRYABLE.has(e.status))
      .map(e => e.id),
    [visibleEvents, selectedIds],
  );

  const changeStatus = (nextStatus: OutboxStatus) => {
    if (nextStatus === status) return;
    setStatus(nextStatus);
    setError(null);
    setRetryMessage(null);
    setSelectedIds(new Set());
    setExpandedEventId(null);
  };

  const toggleSelected = (event: OutboxEvent, checked: boolean) => {
    if (!RETRYABLE.has(event.status)) return;
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (checked) next.add(event.id);
      else next.delete(event.id);
      return next;
    });
  };

  const retryOne = async (event: OutboxEvent) => {
    if (!RETRYABLE.has(event.status)) return;
    setBusy(true);
    setError(null);
    setRetryMessage(null);
    try {
      const r = await retryOutboxEvent(event.id);
      if (r.result.status === "retried") {
        setRetryMessage("已重试 1 条事件");
      } else {
        setRetryMessage(`未重试: ${r.result.reason ?? "skipped"}`);
      }
      setSelectedIds(prev => {
        const next = new Set(prev);
        next.delete(event.id);
        return next;
      });
      onRetryComplete();
    } catch (e) {
      setError(`重试失败: ${messageOf(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const retrySelected = async () => {
    if (selectedRetryableIds.length === 0) return;
    const ids = selectedRetryableIds;
    setBusy(true);
    setError(null);
    setRetryMessage(null);
    try {
      const r = await retryOutboxEvents(ids);
      const skippedNote = summarizeSkipped(r.skipped);
      setRetryMessage(
        `重试完成: retried ${r.retried.length}, skipped ${r.skipped.length}${skippedNote}`,
      );
      setSelectedIds(prev => {
        const next = new Set(prev);
        ids.forEach(id => next.delete(id));
        return next;
      });
      onRetryComplete();
    } catch (e) {
      setError(`批量重试失败: ${messageOf(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{
      marginTop: 12, padding: 8, border: "1px solid #ddd",
      borderRadius: 4, background: "#fafafa", fontSize: 11,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 8, marginBottom: 6,
      }}>
        <div style={{fontSize: 12, fontWeight: 500}}>Outbox 死信</div>
        <button
          type="button"
          onClick={() => setLocalRefreshTick(t => t + 1)}
          disabled={busy}
          style={{
            padding: "3px 7px", fontSize: 11, border: "1px solid #ccc",
            borderRadius: 3, background: "#fff",
            cursor: busy ? "not-allowed" : "pointer",
          }}>
          刷新
        </button>
      </div>

      <div style={{
        display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: 4, marginBottom: 8,
      }}>
        {STATUSES.map(s => {
          const active = status === s;
          return (
            <button
              key={s}
              type="button"
              onClick={() => changeStatus(s)}
              disabled={busy}
              style={{
                padding: "4px 5px", fontSize: 10, borderRadius: 3,
                border: active ? `1px solid ${STATUS_COLORS[s]}` : "1px solid #ddd",
                background: active ? "#fff" : "#f7f7f7",
                color: active ? STATUS_COLORS[s] : "#555",
                cursor: busy ? "not-allowed" : "pointer",
                overflow: "hidden", textOverflow: "ellipsis",
              }}>
              {s} {counts[s] ?? 0}
            </button>
          );
        })}
      </div>

      {error && (
        <div
          role="alert"
          style={{
            marginBottom: 8, color: "#c33", lineHeight: 1.35,
            overflowWrap: "anywhere",
          }}>
          {error}
        </div>
      )}

      {retryMessage && (
        <div
          role="status"
          style={{
            marginBottom: 8, color: "#075", lineHeight: 1.35,
            overflowWrap: "anywhere",
          }}>
          {retryMessage}
        </div>
      )}

      <button
        type="button"
        onClick={retrySelected}
        disabled={busy || selectedRetryableIds.length === 0}
        style={{
          width: "100%", padding: "5px 8px", marginBottom: 8, fontSize: 11,
          border: "none", borderRadius: 4,
          background: selectedRetryableIds.length > 0 ? "#06c" : "#ddd",
          color: "#fff",
          cursor: busy || selectedRetryableIds.length === 0 ? "not-allowed" : "pointer",
        }}>
        批量重试 ({selectedRetryableIds.length})
      </button>

      {busy && visibleEvents.length === 0 && (
        <div style={{color: "#888", marginBottom: 6}}>加载中...</div>
      )}
      {!busy && visibleEvents.length === 0 && !error && (
        <div style={{color: "#888", marginBottom: 6}}>无 {status} 事件</div>
      )}

      <div style={{
        maxHeight: "42vh", overflow: "auto", borderTop: "1px solid #e6e6e6",
      }}>
        {visibleEvents.map(event => {
          const retryable = RETRYABLE.has(event.status);
          const expanded = expandedEventId === event.id;
          const eventContext = `${event.event_type} ${shortId(event.id)}`;
          return (
            <div
              key={event.id}
              style={{padding: "7px 0", borderBottom: "1px solid #e6e6e6"}}>
              <div style={{
                display: "grid", gridTemplateColumns: "18px minmax(0, 1fr) 46px",
                gap: 4, alignItems: "start",
              }}>
                <input
                  type="checkbox"
                  checked={selectedIds.has(event.id)}
                  disabled={!retryable || busy}
                  onChange={e => toggleSelected(event, e.currentTarget.checked)}
                  aria-label={`选择 outbox 事件 ${eventContext}`}
                  style={{margin: "2px 0 0"}}
                />
                <button
                  type="button"
                  onClick={() => setExpandedEventId(expanded ? null : event.id)}
                  aria-expanded={expanded}
                  style={{
                    minWidth: 0, padding: 0, border: "none", background: "transparent",
                    textAlign: "left", cursor: "pointer", color: "#222",
                  }}>
                  <div style={{display: "flex", alignItems: "center", gap: 4}}>
                    <span
                      title={event.event_type}
                      style={{
                        flex: 1, minWidth: 0, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                        fontWeight: 500,
                      }}>
                      {event.event_type}
                    </span>
                    <span style={{
                      flex: "0 0 auto", padding: "1px 4px", borderRadius: 3,
                      color: "#fff", background: STATUS_COLORS[event.status],
                      fontSize: 10, maxWidth: 58, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {event.status}
                    </span>
                  </div>
                  <div style={{marginTop: 2, color: "#666"}}>
                    attempts {event.attempts}
                  </div>
                  <div
                    title={event.last_error ?? ""}
                    style={{
                      marginTop: 2, color: event.last_error ? "#a33" : "#888",
                      lineHeight: 1.3, overflowWrap: "anywhere",
                    }}>
                    {shortText(event.last_error)}
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => retryOne(event)}
                  aria-label={`Retry outbox event ${eventContext}`}
                  disabled={!retryable || busy}
                  style={{
                    padding: "3px 5px", fontSize: 10, borderRadius: 3,
                    border: "1px solid #ccc",
                    background: retryable ? "#fff" : "#eee",
                    color: retryable ? "#06c" : "#888",
                    cursor: retryable && !busy ? "pointer" : "not-allowed",
                  }}>
                  Retry
                </button>
              </div>

              {expanded && (
                <div style={{
                  marginTop: 6, padding: 6, background: "#fff",
                  border: "1px solid #e0e0e0", borderRadius: 3,
                }}>
                  <div style={{
                    marginBottom: 4, fontFamily: "monospace",
                    overflowWrap: "anywhere",
                  }}>
                    id: {event.id}
                  </div>
                  <div style={{marginBottom: 6}}>
                    next_attempt_at: {formatDate(event.next_attempt_at)}
                  </div>
                  <div style={{fontWeight: 500, marginBottom: 3}}>payload</div>
                  <pre style={{
                    maxHeight: 130, overflow: "auto", margin: "0 0 6px",
                    padding: 6, background: "#f7f7f7", border: "1px solid #eee",
                    borderRadius: 3, fontSize: 10, whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                  }}>{formatPayload(event.payload)}</pre>
                  <div style={{fontWeight: 500, marginBottom: 3}}>last_error</div>
                  <pre style={{
                    maxHeight: 120, overflow: "auto", margin: 0,
                    padding: 6, background: "#fff7f7", border: "1px solid #f0dddd",
                    borderRadius: 3, color: "#7a2222", fontSize: 10,
                    whiteSpace: "pre-wrap", overflowWrap: "anywhere",
                  }}>{event.last_error || "-"}</pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

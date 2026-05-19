import React, { useEffect, useState } from "react";
import { PublishEvent, getPublishTimeline } from "../standardsApi";

interface Props {
  versionId: string | null;
  refreshTick: number;
}

export default function PublishTimeline({versionId, refreshTick}: Props) {
  const [events, setEvents] = useState<PublishEvent[]>([]);

  useEffect(() => {
    if (!versionId) { setEvents([]); return; }
    getPublishTimeline(versionId).then(r => setEvents(r.events))
      .catch(() => setEvents([]));
  }, [versionId, refreshTick]);

  return (
    <div style={{padding: 8, borderLeft: "1px solid #eee", overflow: "auto"}}>
      <h4>发布历史</h4>
      {!versionId && <div style={{color: "#888", fontSize: 12}}>未选版本</div>}
      {versionId && events.length === 0 && (
        <div style={{color: "#888", fontSize: 12}}>无发布记录</div>
      )}
      {events.map(e => (
        <div key={e.id} style={{padding: 6, marginBottom: 4,
                                 border: "1px solid #ddd", borderRadius: 4,
                                 background: "#fff"}}>
          <div style={{fontSize: 12,
                       color: e.event_type === "published" ? "#0a7" : "#06c"}}>
            {e.event_type === "published" ? "✓ 发布" : "⎇ Fork"}
          </div>
          <div style={{fontSize: 11, color: "#666"}}>
            by {e.actor_user_id} · {e.occurred_at && new Date(e.occurred_at).toLocaleString()}
          </div>
          {e.notes && (
            <div style={{fontSize: 11, color: "#666", marginTop: 2}}>{e.notes}</div>
          )}
        </div>
      ))}
    </div>
  );
}

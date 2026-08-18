import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../../../../i18n";
import { PublishEvent, getPublishTimeline } from "../standardsApi";

interface Props {
  versionId: string | null;
  refreshTick: number;
}

export default function PublishTimeline({versionId, refreshTick}: Props) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<PublishEvent[]>([]);

  useEffect(() => {
    if (!versionId) { setEvents([]); return; }
    getPublishTimeline(versionId).then(r => setEvents(r.events))
      .catch(() => setEvents([]));
  }, [versionId, refreshTick]);

  return (
    <div style={{padding: 8, borderInlineStart: "1px solid #eee", overflow: "auto"}}>
      <h4>{t("standards.publish.history")}</h4>
      {!versionId && <div style={{color: "#888", fontSize: 12}}>{t("standards.publish.noVersion")}</div>}
      {versionId && events.length === 0 && (
        <div style={{color: "#888", fontSize: 12}}>{t("standards.publish.noEvents")}</div>
      )}
      {events.map(e => (
        <div key={e.id} style={{padding: 6, marginBottom: 4,
                                 border: "1px solid #ddd", borderRadius: 4,
                                 background: "#fff"}}>
          <div style={{fontSize: 12,
                       color: e.event_type === "published" ? "#0a7" : "#06c"}}>
            {e.event_type === "published" ? t("standards.publish.publishedEvent") : t("standards.publish.forkEvent")}
          </div>
          <div style={{fontSize: 11, color: "#666"}}>
            {t("standards.publish.byActor", {actor: e.actor_user_id})} · {e.occurred_at && formatDate(e.occurred_at, {dateStyle: "medium", timeStyle: "medium"})}
          </div>
          {e.notes && (
            <div style={{fontSize: 11, color: "#666", marginTop: 2}}>{e.notes}</div>
          )}
        </div>
      ))}
    </div>
  );
}

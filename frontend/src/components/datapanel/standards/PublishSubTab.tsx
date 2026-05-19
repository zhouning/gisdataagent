import React, { useEffect, useState } from "react";
import VersionPickerPane from "./publish/VersionPickerPane";
import PublishActionPane from "./publish/PublishActionPane";
import PublishTimeline from "./publish/PublishTimeline";
import ForkDialog from "./publish/ForkDialog";

interface Props {
  selectedVersionId: string | null;
  onSelectVersion: (vid: string) => void;
  userRole: string;
  username: string;
}

export default function PublishSubTab({
  selectedVersionId, onSelectVersion, userRole, username,
}: Props) {
  const isAdmin = userRole === "admin";
  const [versionStatus, setVersionStatus] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [forkOpen, setForkOpen] = useState(false);

  useEffect(() => {
    if (!selectedVersionId) { setVersionStatus(null); return; }
    fetch(`/api/std/documents`).then(() => {});  // warm cache (noop)
    // Use the publish/versions endpoint to check status — but it only lists
    // released versions. For a full status check we use the document_id-less
    // fetch fallback to query the version directly.
    fetch(`/api/std/publish/versions`)
      .then(r => r.ok ? r.json() : {versions: []})
      .then(j => {
        const found = (j.versions || []).find((v: any) => v.id === selectedVersionId);
        if (found) {
          setVersionStatus("released");
        } else {
          // Otherwise we don't know yet — try fetching version metadata via
          // the documents/versions endpoint chain. For Wave 5 simplicity we
          // just leave it null and let user select 'approved' manually via
          // analyze/draft. A future endpoint GET /api/std/versions/{id} would
          // make this cleaner.
          setVersionStatus(null);
        }
      })
      .catch(() => setVersionStatus(null));
  }, [selectedVersionId, refreshTick]);

  const refresh = () => setRefreshTick(t => t + 1);

  return (
    <div style={{display: "grid", gridTemplateColumns: "20% 50% 30%",
                 height: "100%"}}>
      <VersionPickerPane
        selectedVersionId={selectedVersionId}
        onSelect={onSelectVersion}
      />
      <PublishActionPane
        versionId={selectedVersionId}
        versionStatus={versionStatus}
        isAdmin={isAdmin}
        onPublished={refresh}
        onForkClick={() => setForkOpen(true)}
      />
      <PublishTimeline
        versionId={selectedVersionId}
        refreshTick={refreshTick}
      />
      {selectedVersionId && (
        <ForkDialog
          sourceVersionId={selectedVersionId}
          open={forkOpen}
          onClose={() => setForkOpen(false)}
          onForked={(newVid) => {
            onSelectVersion(newVid);
            refresh();
          }}
        />
      )}
    </div>
  );
}

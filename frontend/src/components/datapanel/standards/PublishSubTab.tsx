import React, { useEffect, useState } from "react";
import VersionPickerPane from "./publish/VersionPickerPane";
import PublishActionPane from "./publish/PublishActionPane";
import PublishTimeline from "./publish/PublishTimeline";
import ForkDialog from "./publish/ForkDialog";
import { getVersion } from "./standardsApi";

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
    getVersion(selectedVersionId)
      .then(v => setVersionStatus(v.status))
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

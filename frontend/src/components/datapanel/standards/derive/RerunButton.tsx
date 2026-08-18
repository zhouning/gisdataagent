import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../../../i18n";
import { rerunDerivation } from "../standardsApi";

interface Props {
  versionId: string | null;
  isAdmin: boolean;
  onCompleted: () => void;
}

export default function RerunButton({versionId, isAdmin, onCompleted}: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const rerun = async () => {
    if (!versionId) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await rerunDerivation(versionId);
      const summary = Object.entries(r.results)
        .map(([k, v]: [string, any]) => v.ok
          ? t("standards.derive.rerun.strategySuccess", {
              strategy: k,
              created: formatNumber(v.new ?? 0),
              stale: formatNumber(v.staled ?? 0),
            })
          : t("standards.derive.rerun.strategyFailed", {strategy: k, message: v.error}))
        .join("; ");
      setMsg(summary || t("standards.derive.rerun.noActiveStrategy"));
      onCompleted();
    } catch (e: any) {
      setMsg(t("standards.derive.rerun.failed", {message: e.message}));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button onClick={rerun}
              disabled={!versionId || !isAdmin || busy}
              title={!isAdmin ? t("standards.derive.rerun.adminOnly") :
                     !versionId ? t("standards.derive.rerun.selectVersion") : ""}
              style={{padding: "6px 16px", width: "100%",
                      background: (versionId && isAdmin) ? "#06c" : "#ddd",
                      color: "#fff", border: "none", borderRadius: 4,
                      cursor: (versionId && isAdmin) ? "pointer" : "not-allowed"}}>
        {busy ? t("standards.derive.rerun.running") : t("standards.derive.rerun.action")}
      </button>
      {msg && (
        <div style={{marginTop: 8, padding: 6, fontSize: 11,
                     background: "#f5f5f5", border: "1px solid #ddd",
                     borderRadius: 3}}>
          {msg}
        </div>
      )}
    </div>
  );
}

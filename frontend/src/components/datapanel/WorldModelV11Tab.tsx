import { RefreshCw } from 'lucide-react';

export default function WorldModelV11Tab() {
  return (
    <div className="datapanel-section">
      <div className="datapanel-section-header">
        <div>
          <h3>世界模型 v1.1</h3>
          <p>Paper58 is external benchmark support only.</p>
        </div>
        <button
          className="secondary-button"
          type="button"
          disabled
          title="Task 3 wires the local evidence refresh endpoint"
        >
          <RefreshCw size={14} />
          刷新证据
        </button>
      </div>
      <div className="datapanel-card">
        <p>runtime_dependency=none</p>
        <p>geofm_runtime_allowed=false</p>
        <p>not_a_runtime_generator</p>
        <p>/api/twm/paper58-benchmark</p>
        <p>/api/twm/paper58-benchmark/refresh</p>
      </div>
    </div>
  );
}

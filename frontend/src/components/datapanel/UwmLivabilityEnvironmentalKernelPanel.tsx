import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CloudSun, Map, RefreshCw, Shield, Clock3 } from 'lucide-react';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
const asArray = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const number = (value: unknown, digits = 3) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? formatNumber(parsed, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '-';
};
const date = (value: unknown, includeTime = false) => {
  if (!value) return '-';
  return formatDate(String(value), includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium', timeZone: 'UTC' });
};

export default function UwmLivabilityEnvironmentalKernelPanel() {
  const { t, i18n } = useTranslation('common');
  const isChinese = (i18n.resolvedLanguage || i18n.language).startsWith('zh');
  const [scene, setScene] = useState<Row | null>(null);
  const [gate, setGate] = useState<Row | null>(null);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [catalog, setCatalog] = useState<Row[]>([]);
  const [nodeId, setNodeId] = useState('');
  const [replay, setReplay] = useState<Row | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const translatedValue = (scope: string, value: unknown) => {
    const key = String(value || 'unavailable');
    return t(`uwmEnvironmentalKernel.${scope}.${key}`, { defaultValue: key });
  };
  const unitLabel = (value: unknown) => {
    const raw = String(value || '-');
    if (isChinese) return raw.replace(/\|/g, ' · ');
    const parts = raw.split('|');
    const id = parts[parts.length - 1] || raw;
    return t('uwmEnvironmentalKernel.unitId', { id });
  };
  const localizedMapPayload = (payload: Row | null) => payload ? {
    ...payload,
    summary: { ...payload.summary, title: t('uwmEnvironmentalKernel.map.title') },
    layers: asArray<Row>(payload.layers).map((layer, index) => ({
      ...layer,
      name: index === 0 ? t('uwmEnvironmentalKernel.map.observationLayer') : layer.name,
    })),
  } : payload;

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const request = { credentials: 'include' as const, headers: getLocaleHeaders() };
      const [sceneResponse, gateResponse, mapResponse, nodesResponse] = await Promise.all([
        fetch('/api/uwm/livability/environmental-kernel/scene', request),
        fetch('/api/uwm/livability/environmental-kernel/evidence-gate', request),
        fetch('/api/uwm/livability/environmental-kernel/map', request),
        fetch('/api/uwm/livability/environmental-kernel/nodes', request),
      ]);
      const [sceneData, gateData, mapData, nodesData] = await Promise.all([
        sceneResponse.json(), gateResponse.json(), mapResponse.json(), nodesResponse.json(),
      ]);
      if (!sceneResponse.ok || !gateResponse.ok || !mapResponse.ok || !nodesResponse.ok) {
        throw new Error(t('uwmEnvironmentalKernel.errors.unavailable'));
      }
      setScene(sceneData);
      setGate(gateData);
      setMapPayload(mapData);
      const nextCatalog = asArray<Row>(nodesData.nodes);
      setCatalog(nextCatalog);
      setNodeId(previous => previous || nextCatalog[0]?.node_id || '');
      setReplay(null);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('uwmEnvironmentalKernel.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  const loadReplay = async () => {
    if (!nodeId) return;
    setLoading(true);
    setMessage('');
    try {
      const response = await fetch(`/api/uwm/livability/environmental-kernel/temporal-replay/${encodeURIComponent(nodeId)}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(t('uwmEnvironmentalKernel.errors.replay'));
      setReplay(payload);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('uwmEnvironmentalKernel.errors.replay'));
    } finally {
      setLoading(false);
    }
  };

  const run = async () => {
    if (!scene || !acknowledged) return;
    setLoading(true);
    setMessage('');
    try {
      const firstNode = asArray<Row>(scene.state?.spatial_nodes)[0];
      const response = await fetch('/api/uwm/livability/environmental-kernel/rollout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({
          action_type: 'increase_tree_canopy_proxy',
          target_node_ids: firstNode ? [firstNode.node_id] : [],
          state_snapshot_digest: scene.state?.snapshot_digest,
        }),
      });
      const payload = await response.json();
      setMessage(response.ok
        ? t('uwmEnvironmentalKernel.runResult', {
          value: translatedValue('boolean', payload.not_a_causal_effect_estimate),
        })
        : t('uwmEnvironmentalKernel.errors.gateBlocked', {
          reason: translatedValue('errors.codes', payload.error),
        }));
    } catch {
      setMessage(t('uwmEnvironmentalKernel.errors.rollout'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [i18n.resolvedLanguage]);
  const blockers = asArray<string>(gate?.production_blockers);
  const nodes = asArray<Row>(scene?.state?.spatial_nodes);
  const temporal = gate?.temporal_calibration || {};
  const direct = gate?.direct_action_response || {};
  const spatial = gate?.spatial_propagation || {};
  const replayNode = replay?.node || {};
  const replayQuality = replay?.source_quality || {};

  return <div className="uwm-livability-panel" data-testid="uwm-environmental-kernel-panel">
    <div className="uwm-livability-panel-title">
      <CloudSun size={15} /><strong>{t('uwmEnvironmentalKernel.title')}</strong>
      <button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14} />{t('uwmEnvironmentalKernel.refresh')}</button>
    </div>
    <p>{t('uwmEnvironmentalKernel.description', {
      start: date(scene?.scene_time_range?.start_date),
      end: date(scene?.scene_time_range?.end_date),
    })}</p>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="uwm-evidence-grid">
      <div><span>{t('uwmEnvironmentalKernel.kpis.stateNodes')}</span><strong>{number(nodes.length, 0)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.maxClaim')}</span><strong>{translatedValue('claimLevels', gate?.max_claim_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.pm25Temporal')}</span><strong>{translatedValue('supportLevels', temporal.pm25?.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.temperatureTemporal')}</span><strong>{translatedValue('supportLevels', temporal.temperature?.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.pm25Direct')}</span><strong>{translatedValue('supportLevels', direct.pm25?.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.temperatureDirect')}</span><strong>{translatedValue('supportLevels', direct.temperature?.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.vegetationSpatial')}</span><strong>{translatedValue('supportLevels', spatial.vegetation?.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.kpis.pm25Spatial')}</span><strong>{translatedValue('supportLevels', spatial.pm25?.support_level)}</strong></div>
    </div>
    <div className="traditional-message error"><Shield size={15} />{t('uwmEnvironmentalKernel.blockers', {
      blockers: blockers.map(item => translatedValue('blockerCodes', item)).join(t('uwmEnvironmentalKernel.listSeparator')) || '-',
    })}</div>
    <div className="traditional-form-grid">
      <label>{t('uwmEnvironmentalKernel.adminUnit')}
        <select value={nodeId} onChange={event => { setNodeId(event.target.value); setReplay(null); }}>
          {catalog.map(node => <option key={node.node_id} value={node.node_id}>{t('uwmEnvironmentalKernel.nodeOption', { unit: unitLabel(node.node_id), value: number(node.pm25_ugm3) })}</option>)}
        </select>
      </label>
    </div>
    <button className="secondary-button" disabled={!nodeId || loading} onClick={loadReplay}><Clock3 size={14} />{t('uwmEnvironmentalKernel.replay.load')}</button>
    {replay && <div className="uwm-evidence-grid" data-testid="environmental-temporal-replay">
      <div><span>{t('uwmEnvironmentalKernel.replay.records')}</span><strong>{number(replayNode.record_count, 0)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.replay.change')}</span><strong>{Number(replayNode.pm25_last_minus_first_ugm3 || 0) >= 0 ? '+' : ''}{number(replayNode.pm25_last_minus_first_ugm3)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.replay.minimum')}</span><strong>{number(replayNode.pm25_min_ugm3)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.replay.maximum')}</span><strong>{number(replayNode.pm25_max_ugm3)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.replay.supportLevel')}</span><strong>{translatedValue('supportLevels', replayQuality.support_level)}</strong></div>
      <div><span>{t('uwmEnvironmentalKernel.replay.dataNature')}</span><strong>{translatedValue('dataNature', replayQuality.synthetic_status)}</strong></div>
    </div>}
    {replay && <p>{t('uwmEnvironmentalKernel.replay.boundary', {
      start: date(replayNode.start_timestamp, true),
      end: date(replayNode.end_timestamp, true),
    })}</p>}
    <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />{t('uwmEnvironmentalKernel.acknowledgement')}</label>
    <div className="uwm-environmental-actions">
      <button className="secondary-button" disabled={!acknowledged || !scene || loading} onClick={run}>{t('uwmEnvironmentalKernel.tryAction')}</button>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(localizedMapPayload(mapPayload))}><Map size={14} />{t('uwmEnvironmentalKernel.sendToMap')}</button>
    </div>
    <p>{t('uwmEnvironmentalKernel.boundary')}</p>
  </div>;
}

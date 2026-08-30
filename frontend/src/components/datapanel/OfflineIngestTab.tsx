import { useCallback, useEffect, useMemo, useState } from 'react';
import { Download, FileArchive, FileUp, Info, MessageCircle, RefreshCw, Search, ShieldAlert, Upload } from 'lucide-react';

type Row = Record<string, any>;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: 'include', ...init });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('json') ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`);
  return payload as T;
}

function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  return crypto.subtle.digest('SHA-256', buffer).then((digest) => (
    Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
  ));
}

async function uploadStorageKey(file: File): Promise<string> {
  const sampleSize = Math.min(1024 * 1024, file.size);
  const first = new Uint8Array(await file.slice(0, sampleSize).arrayBuffer());
  const lastStart = Math.max(sampleSize, file.size - sampleSize);
  const last = new Uint8Array(await file.slice(lastStart, file.size).arrayBuffer());
  const metadata = new TextEncoder().encode(`${file.name}\0${file.size}\0${file.lastModified}\0`);
  const fingerprintInput = new Uint8Array(metadata.length + first.length + last.length);
  fingerprintInput.set(metadata, 0);
  fingerprintInput.set(first, metadata.length);
  fingerprintInput.set(last, metadata.length + first.length);
  return `gda.offline-ingest.upload:${await sha256Hex(fingerprintInput.buffer)}`;
}

function readRememberedSession(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function rememberSession(key: string, sessionId: string | null): void {
  try {
    if (sessionId) window.localStorage.setItem(key, sessionId);
    else window.localStorage.removeItem(key);
  } catch {
    // Upload remains usable when browser storage is unavailable; only reload resume is disabled.
  }
}

function statusTone(status: string): string {
  if (status === 'succeeded' || status === 'pass' || status === 'accepted') return '#15803d';
  if (status === 'review' || status === 'manual_review' || status === 'planned') return '#a16207';
  if (status === 'blocked' || status === 'fail' || status === 'unmatched') return '#b91c1c';
  return '#475569';
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span style={{ color: statusTone(value), background: `${statusTone(value)}15`, borderRadius: 4, padding: '2px 6px', fontSize: 11 }}>
      {value || 'unknown'}
    </span>
  );
}

export default function OfflineIngestTab() {
  const [overview, setOverview] = useState<Row | null>(null);
  const [runs, setRuns] = useState<Row[]>([]);
  const [contracts, setContracts] = useState<Row | null>(null);
  const [selectedRun, setSelectedRun] = useState<Row | null>(null);
  const [standardizationPlan, setStandardizationPlan] = useState<Row | null>(null);
  const [materialization, setMaterialization] = useState<Row | null>(null);
  const [binding, setBinding] = useState<Row | null>(null);
  const [semanticProjection, setSemanticProjection] = useState<Row | null>(null);
  const [semanticQuestion, setSemanticQuestion] = useState('各地类图斑数量和面积是多少？');
  const [semanticAnswer, setSemanticAnswer] = useState<Row | null>(null);
  const [semanticEngine, setSemanticEngine] = useState<'postgis' | 'lake' | 'geopandas'>('postgis');
  const [localPath, setLocalPath] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadStage, setUploadStage] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    const [summary, recentRuns, contractCatalog] = await Promise.all([
      api<Row>('/api/offline-ingest/overview?limit=30'),
      api<{ runs: Row[] }>('/api/offline-ingest/runs?limit=30'),
      api<Row>('/api/offline-ingest/contracts'),
    ]);
    setOverview(summary);
    setRuns(recentRuns.runs || []);
    setContracts(contractCatalog);
  }, []);

  useEffect(() => {
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : '离线入湖状态加载失败'));
  }, [refresh]);

  const inspectRun = async (runId: string) => {
    try {
      setSelectedRun(await api<Row>(`/api/offline-ingest/runs/${encodeURIComponent(runId)}`));
      setStandardizationPlan(null);
      setMaterialization(null);
      setBinding(null);
      setSemanticProjection(null);
      setSemanticAnswer(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '运行详情加载失败');
    }
  };

  const scanPath = async () => {
    if (!localPath.trim()) return;
    setBusy(true);
    setMessage('正在扫描 GIS Data Agent 服务器上的受控目录...');
    try {
      const result = await api<Row>('/api/offline-ingest/local-scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: localPath.trim() }),
      });
      setMessage(`服务器受控目录扫描完成：${result.asset_count || 0} 个资产，状态 ${result.status}`);
      await refresh();
      await inspectRun(result.run_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '服务器受控目录扫描失败');
    } finally {
      setBusy(false);
    }
  };

  const uploadFile = async () => {
    if (!selectedFile) return;
    setBusy(true);
    const chunkSize = 64 * 1024 * 1024;
    try {
      const storageKey = await uploadStorageKey(selectedFile);
      const suffix = selectedFile.name.toLowerCase().split('.').pop() || '';
      let status: Row | null = null;
      const rememberedSessionId = readRememberedSession(storageKey);
      if (rememberedSessionId) {
        try {
          const remembered = await api<Row>(`/api/offline-ingest/sessions/${rememberedSessionId}`);
          if (
            remembered.filename === selectedFile.name
            && Number(remembered.expected_size) === selectedFile.size
            && Number(remembered.chunk_size) === chunkSize
          ) {
            status = remembered;
            setUploadStage('已恢复上次上传会话，正在核对已接收分片');
          } else {
            rememberSession(storageKey, null);
          }
        } catch {
          rememberSession(storageKey, null);
        }
      }
      if (!status) {
        status = await api<Row>('/api/offline-ingest/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: selectedFile.name,
            size: selectedFile.size,
            chunk_size: chunkSize,
            asset_kind: suffix === 'zip' ? 'filegdb_bundle' : suffix === 'tif' || suffix === 'tiff' ? 'raster' : undefined,
            source_system: 'browser-upload',
          }),
        });
        rememberSession(storageKey, String(status.session_id));
      }
      const total = Number(status.total_chunks || 1);
      if (status.status !== 'committed') {
        for (let index = 0; index < total; index += 1) {
          if (status.chunks?.[String(index)]) continue;
          const start = index * chunkSize;
          const buffer = await selectedFile.slice(start, Math.min(selectedFile.size, start + chunkSize)).arrayBuffer();
          const digest = await sha256Hex(buffer);
          await api(`/api/offline-ingest/sessions/${status.session_id}/chunks/${index}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-Sha256': digest },
            body: buffer,
          });
          status = await api<Row>(`/api/offline-ingest/sessions/${status.session_id}`);
          setUploadStage(`分片上传与校验：${Object.keys(status.chunks || {}).length}/${total}`);
        }
        setUploadStage('服务端正在合并分片并校验完整文件 SHA-256');
        await api<Row>(`/api/offline-ingest/sessions/${status.session_id}/finalize`, { method: 'POST' });
      }
      setUploadStage(suffix === 'zip' ? '正在安全解压、发现 FileGDB 并解析图层字段' : '正在解析数据并执行深度质量检查');
      const ingested = await api<Row>(`/api/offline-ingest/sessions/${status.session_id}/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_quality: true }),
      });
      rememberSession(storageKey, null);
      setUploadStage('');
      setMessage(`数据集接入完成：发现 ${ingested.run?.asset_count || 0} 个资产，质量状态 ${ingested.deep_quality?.status || ingested.status}`);
      setSelectedFile(null);
      await refresh();
      if (ingested.ingest_run_id) await inspectRun(ingested.ingest_run_id);
    } catch (error) {
      setUploadStage('接入中断；重新选择同一文件可继续已有上传会话');
      setMessage(error instanceof Error ? error.message : '数据集接入失败，可重新选择同一文件继续');
    } finally {
      setBusy(false);
    }
  };

  const runDeepQuality = async () => {
    if (!selectedRun?.run_id) return;
    setBusy(true);
    setMessage('正在读取真实要素并执行深度质量检查...');
    try {
      const result = await api<Row>(`/api/offline-ingest/runs/${selectedRun.run_id}/quality`, { method: 'POST' });
      await inspectRun(selectedRun.run_id);
      await refresh();
      setMessage(`深度质量检查完成：${result.status}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '深度质量检查失败');
    } finally {
      setBusy(false);
    }
  };

  const createPlan = async (allowReview: boolean) => {
    if (!selectedRun?.run_id) return;
    setBusy(true);
    try {
      const result = await api<Row>(`/api/offline-ingest/runs/${selectedRun.run_id}/standardize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allow_review: allowReview }),
      });
      setStandardizationPlan(result.standardization_plan || null);
      setMessage(allowReview ? '已按人工复核结果生成标准化计划' : '标准化计划已生成');
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '标准化计划被质量门禁拦截');
    } finally {
      setBusy(false);
    }
  };

  const executePlan = async () => {
    if (!standardizationPlan?.plan_id) return;
    setBusy(true);
    try {
      const result = await api<Row>(`/api/offline-ingest/standardization/${standardizationPlan.plan_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      setMaterialization(result);
      setMessage(`标准化执行状态：${result.status}`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '标准化执行失败');
    } finally {
      setBusy(false);
    }
  };

  const bindOntology = async (bindingMode: 'rehearsal' | 'production' = 'rehearsal') => {
    if (!standardizationPlan?.plan_id) return;
    setBusy(true);
    try {
      const result = await api<Row>(`/api/offline-ingest/standardization/${standardizationPlan.plan_id}/ontology-bind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ontology_version: '2.3.0', binding_mode: bindingMode }),
      });
      setBinding(result);
      const bindingStatus = result.ontology_binding?.status || result.status;
      setMessage(bindingStatus === 'accepted' || result.status === 'succeeded' ? `${bindingMode === 'rehearsal' ? '演示' : '生产'}本体引用绑定已接受` : `本体绑定状态：${bindingStatus}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '本体绑定被门禁拒绝');
    } finally {
      setBusy(false);
    }
  };

  const buildSemanticProjection = async () => {
    if (!standardizationPlan?.plan_id) return;
    setBusy(true);
    try {
      const result = await api<Row>(`/api/offline-ingest/standardization/${standardizationPlan.plan_id}/semantic-project`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'rehearsal', preview_limit: 500, publish_postgis: true }),
      });
      setSemanticProjection(result.projection || null);
      setSemanticAnswer(null);
      setSemanticEngine('postgis');
      setMessage('DLTB 语义投影已生成，治理 GeoParquet 已同步发布到 PostGIS；默认使用 PostGIS 问数');
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '语义投影生成失败');
    } finally {
      setBusy(false);
    }
  };

  const askSemantic = async () => {
    if (!semanticProjection?.projection_id || !semanticQuestion.trim()) return;
    setBusy(true);
    try {
      const result = await api<Row>('/api/offline-ingest/semantic-query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projection_id: semanticProjection.projection_id,
          question: semanticQuestion.trim(),
          execution_engine: semanticEngine,
          limit: 100,
        }),
      });
      setSemanticAnswer(result);
      setMessage(`Qwen 问数完成：${semanticEngine} · ${result.llm?.latency_ms ?? '—'} ms · 未使用固定规则回退`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '离线语义问数失败');
    } finally {
      setBusy(false);
    }
  };

  const contractEntries = useMemo(() => Object.values(contracts?.contracts || {}) as Row[], [contracts]);
  const qualityCounts = overview?.quality_counts || {};

  return (
    <div style={{ padding: 14, color: '#0f172a', fontSize: 13, overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 16 }}>离线入湖管理</h3>
          <div style={{ color: '#64748b', marginTop: 4 }}>Raw 原始证据 → 质量门禁 → 标准化 → 本体引用绑定</div>
        </div>
        <button onClick={() => refresh().catch((error) => setMessage(error.message))} disabled={busy} title="刷新状态" aria-label="刷新状态" style={{ border: '1px solid #cbd5e1', background: '#fff', padding: 7, borderRadius: 5, cursor: 'pointer' }}><RefreshCw size={15} /></button>
      </div>

      {message && <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '8px 10px', borderRadius: 5, marginBottom: 12 }}>{message}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginBottom: 14 }}>
        {[
          ['运行批次', overview?.run_count ?? 0],
          ['最近资产', overview?.asset_count_in_recent_runs ?? 0],
          ['通过检查', qualityCounts.pass ?? 0],
          ['待复核', qualityCounts.review ?? 0],
        ].map(([label, value]) => <div key={String(label)} style={{ border: '1px solid #e2e8f0', borderRadius: 6, padding: '10px 12px', background: '#fff' }}><div style={{ color: '#64748b', fontSize: 11 }}>{label}</div><strong style={{ fontSize: 20 }}>{Number(value).toLocaleString()}</strong></div>)}
      </div>

      <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>数据接入</div>
        <div style={{ background: '#f8fafc', borderLeft: '3px solid #0f766e', padding: '10px 12px', marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, marginBottom: 4 }}><FileArchive size={15} />浏览器上传</div>
          <div style={{ color: '#64748b', fontSize: 12, marginBottom: 8 }}>远程浏览器可直接选择本机文件。FileGDB 文件夹须整体打包为 ZIP，服务端保留原包并自动安全解压、发现 .gdb、解析图层字段；TIFF 可直接上传。</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <FileUp size={15} color="#64748b" />
          <input type="file" accept=".zip,.tif,.tiff" onChange={(event) => { setSelectedFile(event.target.files?.[0] || null); setUploadStage(''); }} />
          {selectedFile && <span style={{ color: '#475569' }}>{selectedFile.name}（{(selectedFile.size / 1024 / 1024).toFixed(1)} MB）</span>}
          <button onClick={uploadFile} disabled={busy || !selectedFile} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, border: 0, background: '#0f766e', color: '#fff', borderRadius: 4, padding: '7px 10px', cursor: 'pointer' }}><Upload size={14} />上传并接入</button>
          </div>
          {uploadStage && <div style={{ marginTop: 8, color: uploadStage.includes('中断') ? '#b91c1c' : '#0f766e', fontSize: 12 }}>{uploadStage}</div>}
          <div style={{ color: '#64748b', fontSize: 11, marginTop: 6 }}>采用 64 MB 分片和逐片 SHA-256；页面刷新后重新选择同一文件，将继续缺失分片，不会从头上传。</div>
        </div>
        <div style={{ padding: '8px 0 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, marginBottom: 4 }}><Search size={15} />扫描服务器受控目录</div>
          <div style={{ color: '#64748b', fontSize: 12, marginBottom: 8 }}>仅供部署主机或 Windows 采集器使用。这里填写的是 GIS Data Agent 服务器路径，不是当前浏览器所在电脑的路径。</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input value={localPath} onChange={(event) => setLocalPath(event.target.value)} placeholder="服务器受控目录，例如 D:\\NX_INCOMING\\批次01" style={{ minWidth: 340, flex: 1, border: '1px solid #cbd5e1', borderRadius: 4, padding: '7px 8px' }} />
            <button onClick={scanPath} disabled={busy || !localPath.trim()} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, border: '1px solid #0f766e', background: '#fff', color: '#0f766e', borderRadius: 4, padding: '7px 10px', cursor: 'pointer' }}><Search size={14} />扫描服务器目录</button>
          </div>
        </div>
      </section>

      <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>最近运行</div>
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 620 }}><thead><tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}><th style={{ padding: 6 }}>时间</th><th style={{ padding: 6 }}>类型</th><th style={{ padding: 6 }}>状态</th><th style={{ padding: 6 }}>资产</th><th style={{ padding: 6 }}>查看</th></tr></thead><tbody>{runs.map((run) => <tr key={run.run_id} style={{ borderBottom: '1px solid #f1f5f9' }}><td style={{ padding: 6, whiteSpace: 'nowrap' }}>{String(run.started_at || run.created_at || '').replace('T', ' ').slice(0, 19)}</td><td style={{ padding: 6 }}>{run.kind}</td><td style={{ padding: 6 }}><StatusBadge value={run.status} /></td><td style={{ padding: 6 }}>{(run.assets || []).length}</td><td style={{ padding: 6 }}><button onClick={() => inspectRun(run.run_id)} style={{ border: '1px solid #cbd5e1', background: '#fff', borderRadius: 4, padding: '4px 8px', cursor: 'pointer' }}>详情</button></td></tr>)}{runs.length === 0 && <tr><td colSpan={5} style={{ padding: 18, textAlign: 'center', color: '#94a3b8' }}>暂无入湖运行</td></tr>}</tbody></table></div>
      </section>

      {selectedRun && <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}><div style={{ fontWeight: 600 }}>运行详情 <code style={{ fontSize: 11, color: '#64748b' }}>{selectedRun.run_id}</code></div><a href={`/api/offline-ingest/runs/${selectedRun.run_id}/diagnostics`} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#0f766e' }}><Download size={14} />诊断包</a></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginBottom: 8 }}><div>运行类型：{selectedRun.kind}</div><div>状态：<StatusBadge value={selectedRun.status} /></div><div>资产数：{(selectedRun.assets || []).length}</div></div>
        <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 680 }}><thead><tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}><th style={{ padding: 6 }}>资产</th><th style={{ padding: 6 }}>格式</th><th style={{ padding: 6 }}>质量</th><th style={{ padding: 6 }}>映射</th><th style={{ padding: 6 }}>SHA-256</th></tr></thead><tbody>{(selectedRun.assets || []).map((asset: Row) => <tr key={asset.asset_id} style={{ borderBottom: '1px solid #f1f5f9' }}><td style={{ padding: 6 }}>{asset.name || asset.filename || asset.asset_id}</td><td style={{ padding: 6 }}>{asset.kind}</td><td style={{ padding: 6 }}><StatusBadge value={(selectedRun.quality || []).find((item: Row) => item.asset_id === asset.asset_id)?.status || 'unknown'} /></td><td style={{ padding: 6 }}>{(asset.layers || []).map((layer: Row) => layer.mapping?.status).filter(Boolean).join(', ') || '—'}</td><td style={{ padding: 6 }}><code style={{ fontSize: 10 }}>{String(asset.sha256 || '').slice(0, 12)}</code></td></tr>)}</tbody></table></div>
        {selectedRun.deep_quality && <div style={{ marginTop: 8, color: '#475569' }}>深度质检：<StatusBadge value={selectedRun.deep_quality.status} /> · {Object.entries(selectedRun.deep_quality.counts || {}).map(([key, value]) => `${key} ${value}`).join('，')}</div>}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <button onClick={runDeepQuality} disabled={busy || !(selectedRun.assets || []).length} style={{ padding: '6px 9px', border: '1px solid #334155', color: '#334155', background: '#fff', borderRadius: 4, cursor: 'pointer' }}>执行深度质检</button>
          <button onClick={() => createPlan(false)} disabled={busy || selectedRun.status === 'blocked' || !selectedRun.deep_quality} style={{ padding: '6px 9px', border: '1px solid #0f766e', color: '#0f766e', background: '#fff', borderRadius: 4, cursor: 'pointer' }}>生成标准化计划</button>
          <button onClick={() => createPlan(true)} disabled={busy || selectedRun.status === 'blocked' || !selectedRun.deep_quality} style={{ padding: '6px 9px', border: '1px solid #a16207', color: '#a16207', background: '#fff', borderRadius: 4, cursor: 'pointer' }}>人工复核后生成</button>
        </div>
      </section>}

      {standardizationPlan && <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}><div style={{ fontWeight: 600, marginBottom: 8 }}>标准化计划 <StatusBadge value={standardizationPlan.status} /></div><div style={{ color: '#475569', marginBottom: 8 }}>目标数：{(standardizationPlan.outputs || []).length}，版本：{standardizationPlan.standard_version}</div><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button onClick={executePlan} disabled={busy} style={{ padding: '6px 9px', border: 0, color: '#fff', background: '#0f766e', borderRadius: 4, cursor: 'pointer' }}>执行标准化</button><button onClick={() => bindOntology('rehearsal')} disabled={busy || !materialization} style={{ padding: '6px 9px', border: '1px solid #334155', color: '#334155', background: '#fff', borderRadius: 4, cursor: 'pointer' }}>演示本体绑定</button><button onClick={() => bindOntology('production')} disabled={busy || !materialization} style={{ padding: '6px 9px', border: '1px solid #b91c1c', color: '#b91c1c', background: '#fff', borderRadius: 4, cursor: 'pointer' }}>申请生产绑定</button><button onClick={buildSemanticProjection} disabled={busy || !materialization} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '6px 9px', border: '1px solid #0f766e', color: '#0f766e', background: '#fff', borderRadius: 4, cursor: 'pointer' }}><MessageCircle size={14} />生成 DLTB 语义投影</button></div></section>}

      {materialization && <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}><div style={{ fontWeight: 600 }}>标准化结果 <StatusBadge value={materialization.status} /></div><div style={{ marginTop: 6, color: '#475569' }}>输出：{materialization.output_count ?? materialization.materialization?.outputs?.length ?? 0}，阻断：{materialization.materialization?.failures?.length ?? materialization.failures?.length ?? 0}</div></section>}
      {binding && <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}><div style={{ fontWeight: 600 }}>本体绑定门禁 <StatusBadge value={binding.ontology_binding?.status || binding.status} /></div><div style={{ marginTop: 6, color: '#475569' }}>{binding.reason || binding.message || '仅保存治理数据引用，不复制原始记录'}</div></section>}

      {semanticProjection && <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12, marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}><div style={{ fontWeight: 600 }}>DLTB 语义层与 Qwen 智能问数</div><StatusBadge value={semanticProjection.production_eligible ? 'production_eligible' : 'rehearsal_only'} /></div>
        <div style={{ color: '#475569', marginBottom: 6 }}>语义源：<code>land_parcel_current</code> · 本体：{semanticProjection.ontology_version} · 质量：<StatusBadge value={semanticProjection.quality_status || 'review'} /></div>
        <div style={{ color: '#64748b', fontSize: 11, marginBottom: 8 }}>数据湖：{semanticProjection.execution_bindings?.lake?.row_count?.toLocaleString?.() ?? '—'} 条 · PostGIS：<code>{semanticProjection.execution_bindings?.postgis?.table_name || '未发布'}</code> · 发布状态：{semanticProjection.publication_status}</div>
        <div role="group" aria-label="智能问数执行引擎" style={{ display: 'inline-grid', gridTemplateColumns: 'repeat(3, minmax(92px, 1fr))', border: '1px solid #cbd5e1', borderRadius: 5, overflow: 'hidden', marginBottom: 8 }}>
          {([
            ['postgis', 'PostGIS', '生产默认：NL2Semantic2SQL 在 PostGIS 执行'],
            ['lake', '数据湖 SQL', 'NL2Semantic2SQL 在治理 GeoParquet 上通过 DuckDB 执行'],
            ['geopandas', '诊断', 'Qwen 生成受控语义 AST，GeoPandas 仅用于结果核验'],
          ] as const).map(([value, label, title]) => {
            const unavailable = value !== 'geopandas' && !semanticProjection.execution_bindings?.[value];
            return <button key={value} type="button" title={title} disabled={unavailable} onClick={() => { setSemanticEngine(value); setSemanticAnswer(null); }} style={{ minHeight: 32, border: 0, borderRight: value !== 'geopandas' ? '1px solid #cbd5e1' : 0, background: semanticEngine === value ? '#0f766e' : '#fff', color: semanticEngine === value ? '#fff' : unavailable ? '#94a3b8' : '#334155', cursor: unavailable ? 'not-allowed' : 'pointer', padding: '5px 8px' }}>{label}</button>;
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><MessageCircle size={15} color="#64748b" /><input value={semanticQuestion} onChange={(event) => setSemanticQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') askSemantic(); }} placeholder="例如：每个行政区的耕地面积和数量是多少？" style={{ minWidth: 340, flex: 1, border: '1px solid #cbd5e1', borderRadius: 4, padding: '7px 8px' }} /><button onClick={askSemantic} disabled={busy || !semanticQuestion.trim()} style={{ padding: '7px 10px', border: 0, background: '#0f766e', color: '#fff', borderRadius: 4, cursor: 'pointer' }}>智能问数</button></div>
        {semanticAnswer && <div style={{ marginTop: 10, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 5, padding: 10 }}><div style={{ marginBottom: 6 }}>{semanticAnswer.answer}</div><div style={{ color: '#64748b', fontSize: 11, marginBottom: 8 }}>LLM：{semanticAnswer.llm?.provider} / {semanticAnswer.llm?.model} · 请求 {semanticAnswer.llm?.request_id || '—'} · {semanticAnswer.llm?.latency_ms} ms · 执行器：{semanticAnswer.executor?.engine} / {semanticAnswer.executor?.source_kind} · 回退：{semanticAnswer.fallback_used ? '是' : '否'}{semanticAnswer.diagnostic_only ? ' · 仅诊断' : ''}</div><details style={{ marginBottom: 8 }}><summary style={{ cursor: 'pointer', color: '#475569' }}>查看生成 SQL、语义约束与执行证据</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 11, margin: '6px 0 0' }}>{JSON.stringify({ generated_sql: semanticAnswer.sql, raw_sql: semanticAnswer.raw_sql, semantic_ast: semanticAnswer.semantic_ast, semantic_context: semanticAnswer.semantic, llm: semanticAnswer.llm, executor: semanticAnswer.executor, fallback_used: semanticAnswer.fallback_used }, null, 2)}</pre></details><div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}><thead><tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>{Object.keys((semanticAnswer.rows || [])[0] || {}).map((key) => <th key={key} style={{ padding: 5 }}>{key}</th>)}</tr></thead><tbody>{(semanticAnswer.rows || []).slice(0, 20).map((row: Row, index: number) => <tr key={index} style={{ borderBottom: '1px solid #f1f5f9' }}>{Object.keys((semanticAnswer.rows || [])[0] || {}).map((key) => <td key={key} style={{ padding: 5 }}>{String(row[key] ?? '—')}</td>)}</tr>)}</tbody></table></div></div>}
      </section>}

      <section style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}><div style={{ fontWeight: 600 }}>宁夏数据模型基线</div><span style={{ color: '#64748b', fontSize: 11 }}>{contracts?.authority || 'not_configured'} · {contractEntries.length} 个对象</span></div>{contracts?.status === 'not_configured' ? <div style={{ display: 'flex', gap: 6, alignItems: 'center', color: '#b91c1c', background: '#fff1f2', padding: 8, borderRadius: 4, marginBottom: 8 }}><ShieldAlert size={15} />尚未配置宁夏清单字段基线，不能进行标准匹配。</div> : <div style={{ display: 'flex', gap: 6, alignItems: 'center', color: '#166534', background: '#f0fdf4', padding: 8, borderRadius: 4, marginBottom: 8 }}><Info size={15} />两份宁夏 Excel 已作为匹配基线；真实数据按图层逐项执行字段、CRS、几何和值域质量校验。</div>}<div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{contractEntries.slice(0, 18).map((contract) => <span key={contract.code} style={{ border: '1px solid #e2e8f0', borderRadius: 4, padding: '4px 7px', background: '#fff' }}>{contract.code} <span style={{ color: '#64748b' }}>{contract.fields?.length || 0} 字段</span></span>)}</div></section>
    </div>
  );
}

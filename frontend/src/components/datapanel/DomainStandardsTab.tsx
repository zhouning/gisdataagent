import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import ModuleList from './domain-standards/ModuleList';
import ClassGraph from './domain-standards/ClassGraph';
import ClassDetailDrawer, { type ClassDetail } from './domain-standards/ClassDetailDrawer';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

interface XmiStatus {
  compiled: boolean;
  module_count: number;
  class_count: number;
  last_compiled?: string;
}

export default function DomainStandardsTab() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<XmiStatus | null>(null);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);
  const [classDetail, setClassDetail] = useState<ClassDetail | null>(null);
  const [compiling, setCompiling] = useState(false);

  useEffect(() => {
    fetchStatus();
  }, [i18n.resolvedLanguage]);

  useEffect(() => {
    if (selectedClassId) {
      fetchClassDetail(selectedClassId);
    } else {
      setClassDetail(null);
    }
  }, [selectedClassId, i18n.resolvedLanguage]);

  const fetchStatus = async () => {
    try {
      const resp = await fetch('/api/xmi/status', { credentials: 'include', headers: getLocaleHeaders() });
      if (resp.ok) {
        const data = await resp.json();
        setStatus(data);
      }
    } catch { /* ignore */ }
  };

  const fetchClassDetail = async (classId: string) => {
    try {
      const resp = await fetch(`/api/xmi/classes/${encodeURIComponent(classId)}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      if (resp.ok) {
        const data = await resp.json();
        setClassDetail(data);
      }
    } catch { /* ignore */ }
  };

  const handleCompile = async () => {
    const sourceDir = window.prompt(t('domainStandards.prompt.sourceDirectory'));
    if (!sourceDir) return;
    setCompiling(true);
    try {
      const resp = await fetch('/api/xmi/compile', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_dir: sourceDir }),
      });
      if (resp.ok) {
        await fetchStatus();
      }
    } catch { /* ignore */ }
    finally { setCompiling(false); }
  };

  const handleClassNavigate = (classId: string) => {
    setSelectedClassId(classId);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Top bar */}
      <div style={{
        padding: '8px 12px',
        borderBottom: '1px solid #e5e7eb',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: '#f8fafc',
        flexShrink: 0,
      }}>
        {/* Status indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: status?.compiled ? '#22c55e' : '#9ca3af',
          }} />
          <span style={{ fontSize: 12, color: '#374151' }}>
            {status
              ? status.compiled
                ? t('domainStandards.status.compiled', {
                    modules: formatNumber(status.module_count),
                    classes: formatNumber(status.class_count),
                  })
                : t('domainStandards.status.notCompiled')
              : t('domainStandards.status.loading')}
          </span>
          {status?.last_compiled && (
            <span style={{ fontSize: 11, color: '#9ca3af' }}>
              ({formatDate(status.last_compiled, { dateStyle: 'medium' })})
            </span>
          )}
        </div>

        <div style={{ flex: 1 }} />

        {/* Compile button */}
        <button
          onClick={handleCompile}
          disabled={compiling}
          style={{
            background: compiling ? '#93c5fd' : '#3b82f6',
            color: '#fff',
            border: 'none',
            borderRadius: 5,
            padding: '5px 12px',
            fontSize: 12,
            cursor: compiling ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          {compiling && (
            <span style={{
              display: 'inline-block', width: 10, height: 10,
              border: '2px solid rgba(255,255,255,0.4)',
              borderTopColor: '#fff',
              borderRadius: '50%',
              animation: 'spin 0.7s linear infinite',
            }} />
          )}
          {compiling ? t('domainStandards.actions.compiling') : t('domainStandards.actions.compile')}
        </button>
      </div>

      {/* Main split layout */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Left: Module list */}
        <div style={{
          width: 280,
          borderInlineEnd: '1px solid #e5e7eb',
          flexShrink: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{
            padding: '6px 12px',
            fontSize: 11, fontWeight: 700, color: '#6b7280',
            textTransform: 'uppercase', letterSpacing: 0,
            borderBottom: '1px solid #f3f4f6',
            background: '#f9fafb',
          }}>
            {t('domainStandards.sections.modules')}
          </div>
          <ModuleList
            onModuleSelect={setSelectedModuleId}
            onClassSelect={setSelectedClassId}
            selectedModuleId={selectedModuleId}
          />
        </div>

        {/* Right: Class graph */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
          <ClassGraph
            moduleId={selectedModuleId}
            onClassClick={setSelectedClassId}
          />

          {/* Class detail drawer overlays on right */}
          <ClassDetailDrawer
            classDetail={classDetail}
            onClose={() => { setClassDetail(null); setSelectedClassId(null); }}
            onClassNavigate={handleClassNavigate}
          />
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

import { useState, useEffect } from 'react';
import Papa from 'papaparse';

import CatalogTab from './datapanel/CatalogTab';
import HistoryTab from './datapanel/HistoryTab';
import UsageTab from './datapanel/UsageTab';
import ToolsTab from './datapanel/ToolsTab';
import CapabilitiesTab from './datapanel/CapabilitiesTab';
import KnowledgeBaseTab from './datapanel/KnowledgeBaseTab';
import WorkflowsTab from './datapanel/WorkflowsTab';
import { FileManager, DataTable } from './datapanel/FileListTab';
import SuggestionsTab from './datapanel/SuggestionsTab';
import TasksTab from './datapanel/TasksTab';
import TemplatesTab from './datapanel/TemplatesTab';
import AnalyticsTab from './datapanel/AnalyticsTab';
import ChartsTab from './datapanel/ChartsTab';
import GovernanceTab from './datapanel/GovernanceTab';
import MemorySearchTab from './datapanel/MemorySearchTab';
import ObservabilityTab from './datapanel/ObservabilityTab';
import VirtualSourcesTab from './datapanel/VirtualSourcesTab';
import MarketplaceTab from './datapanel/MarketplaceTab';
import GeoJsonEditorTab from './datapanel/GeoJsonEditorTab';
import WorldModelTab from './datapanel/WorldModelTab';
import CausalReasoningTab from './datapanel/CausalReasoningTab';
import OptimizationTab from './datapanel/OptimizationTab';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
}

type TabKey = 'files' | 'table' | 'catalog' | 'history' | 'usage' | 'tools' | 'workflows' | 'suggestions' | 'tasks' | 'templates' | 'analytics' | 'capabilities' | 'kb' | 'vsources' | 'market' | 'geojson' | 'charts' | 'governance' | 'memory' | 'observability' | 'worldmodel' | 'causal' | 'optimization';

type GroupKey = 'data' | 'intelligence' | 'ops' | 'orchestration';

interface TabDef {
  key: TabKey;
  label: string;
  icon: string;
}

const TAB_GROUPS: { key: GroupKey; label: string; icon: string; tabs: TabDef[] }[] = [
  {
    key: 'data', label: '数据', icon: '📊',
    tabs: [
      { key: 'files', label: '文件', icon: '📁' },
      { key: 'table', label: '表格', icon: '📋' },
      { key: 'catalog', label: '资产', icon: '🗃️' },
      { key: 'vsources', label: '数据源', icon: '🔗' },
      { key: 'geojson', label: 'GeoJSON', icon: '✏️' },
      { key: 'charts', label: '图表', icon: '📈' },
    ],
  },
  {
    key: 'intelligence', label: '智能', icon: '🤖',
    tabs: [
      { key: 'capabilities', label: '能力', icon: '⚡' },
      { key: 'tools', label: '工具', icon: '🔧' },
      { key: 'kb', label: '知识库', icon: '📚' },
      { key: 'suggestions', label: '建议', icon: '💡' },
      { key: 'memory', label: '记忆', icon: '🧠' },
      { key: 'market', label: '市场', icon: '🏪' },
      { key: 'worldmodel', label: '世界模型', icon: '🌍' },
      { key: 'causal', label: '因果推理', icon: '⚗️' },
    ],
  },
  {
    key: 'ops', label: '运维', icon: '📈',
    tabs: [
      { key: 'history', label: '历史', icon: '🕐' },
      { key: 'usage', label: '用量', icon: '📉' },
      { key: 'analytics', label: '分析', icon: '📊' },
      { key: 'governance', label: '治理', icon: '🛡️' },
      { key: 'observability', label: '追踪', icon: '🔍' },
      { key: 'tasks', label: '任务', icon: '✅' },
    ],
  },
  {
    key: 'orchestration', label: '编排', icon: '🔀',
    tabs: [
      { key: 'workflows', label: '工作流', icon: '⚙️' },
      { key: 'templates', label: '模板', icon: '📄' },
      { key: 'optimization', label: '优化', icon: '🎯' },
    ],
  },
];

// Build a lookup: tabKey → groupKey
const TAB_TO_GROUP: Record<TabKey, GroupKey> = {} as any;
TAB_GROUPS.forEach(g => g.tabs.forEach(t => { TAB_TO_GROUP[t.key] = g.key; }));

export default function DataPanel({ dataFile, userRole }: DataPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('files');
  const [activeGroup, setActiveGroup] = useState<GroupKey>('data');
  const [tableData, setTableData] = useState<any[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!dataFile) return;
    loadCsvData(dataFile);
    setActiveTab('table');
    setActiveGroup('data');
  }, [dataFile]);

  const loadCsvData = async (filename: string) => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/user/files/${encodeURIComponent(filename)}`, { credentials: 'include' });
      if (!resp.ok) return;
      const text = await resp.text();
      const result = Papa.parse(text, { header: true, skipEmptyLines: true });
      if (result.data.length > 0) {
        setTableColumns(result.meta.fields || []);
        setTableData(result.data.slice(0, 500));
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  const handleTabClick = (tab: TabKey) => {
    setActiveTab(tab);
    setActiveGroup(TAB_TO_GROUP[tab]);
  };

  const handleGroupClick = (groupKey: GroupKey) => {
    setActiveGroup(groupKey);
    // Switch to first tab in group if current tab is not in this group
    const group = TAB_GROUPS.find(g => g.key === groupKey);
    if (group && !group.tabs.some(t => t.key === activeTab)) {
      setActiveTab(group.tabs[0].key);
    }
  };

  const currentGroup = TAB_GROUPS.find(g => g.key === activeGroup) || TAB_GROUPS[0];

  return (
    <div className="data-panel">
      <div className="data-panel-header">
        <svg className="data-panel-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
        </svg>
        <span>工作台</span>
      </div>

      {/* Group selector */}
      <div className="data-panel-groups">
        {TAB_GROUPS.map(g => (
          <button
            key={g.key}
            className={`data-panel-group ${activeGroup === g.key ? 'active' : ''}`}
            onClick={() => handleGroupClick(g.key)}
            title={g.label}
          >
            <span className="group-icon">{g.icon}</span>
            <span className="group-label">{g.label}</span>
          </button>
        ))}
      </div>

      {/* Tabs within active group */}
      <div className="data-panel-tabs">
        {currentGroup.tabs.map(t => (
          <button
            key={t.key}
            className={`data-panel-tab ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => handleTabClick(t.key)}
          >
            <span className="tab-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileManager onFileClick={(name) => { loadCsvData(name); setActiveTab('table'); }} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
        {activeTab === 'catalog' && <CatalogTab />}
        {activeTab === 'history' && <HistoryTab />}
        {activeTab === 'usage' && <UsageTab />}
        {activeTab === 'tools' && <ToolsTab userRole={userRole} />}
        {activeTab === 'workflows' && <WorkflowsTab />}
        {activeTab === 'suggestions' && <SuggestionsTab />}
        {activeTab === 'tasks' && <TasksTab />}
        {activeTab === 'templates' && <TemplatesTab />}
        {activeTab === 'analytics' && <AnalyticsTab />}
        {activeTab === 'governance' && <GovernanceTab />}
        {activeTab === 'memory' && <MemorySearchTab />}
        {activeTab === 'observability' && <ObservabilityTab />}
        {activeTab === 'capabilities' && <CapabilitiesTab userRole={userRole} />}
        {activeTab === 'kb' && <KnowledgeBaseTab />}
        {activeTab === 'vsources' && <VirtualSourcesTab />}
        {activeTab === 'market' && <MarketplaceTab />}
        {activeTab === 'geojson' && <GeoJsonEditorTab />}
        {activeTab === 'charts' && <ChartsTab />}
        {activeTab === 'worldmodel' && <WorldModelTab />}
        {activeTab === 'causal' && <CausalReasoningTab />}
        {activeTab === 'optimization' && <OptimizationTab />}
      </div>
    </div>
  );
}

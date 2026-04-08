import { useState, useEffect, type ReactNode } from 'react';
import Papa from 'papaparse';
import {
  FolderOpen, Table2, Database, Tag, Link, MapPin, BarChart3,
  Zap, Wrench, BookOpen, Lightbulb, Brain, Store, Globe, FlaskConical, Network,
  History, Gauge, PieChart, Shield, ClipboardCheck, Bell, Activity, Radio, ListTodo,
  GitBranch, FileText, Target, ThumbsUp,
  LayoutGrid,
} from 'lucide-react';

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
import QcMonitorTab from './datapanel/QcMonitorTab';
import AlertsTab from './datapanel/AlertsTab';
import TopologyTab from './datapanel/TopologyTab';
import MessageBusTab from './datapanel/MessageBusTab';
import MetadataPanel from './datapanel/MetadataPanel';
import FeedbackTab from './datapanel/FeedbackTab';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
}

type TabKey = 'files' | 'table' | 'catalog' | 'metadata' | 'history' | 'usage' | 'tools' | 'workflows' | 'suggestions' | 'tasks' | 'templates' | 'analytics' | 'capabilities' | 'kb' | 'vsources' | 'market' | 'geojson' | 'charts' | 'governance' | 'memory' | 'observability' | 'worldmodel' | 'causal' | 'optimization' | 'qcmonitor' | 'alerts' | 'topology' | 'messagebus' | 'feedback';

type GroupKey = 'data' | 'intelligence' | 'ops';

interface TabDef {
  key: TabKey;
  label: string;
  icon: ReactNode;
}

const ICON_SIZE = 14;

const TAB_GROUPS: { key: GroupKey; label: string; icon: ReactNode; tabs: TabDef[] }[] = [
  {
    key: 'data', label: '数据资源', icon: <Database size={16} />,
    tabs: [
      { key: 'files', label: '文件', icon: <FolderOpen size={ICON_SIZE} /> },
      { key: 'table', label: '表格', icon: <Table2 size={ICON_SIZE} /> },
      { key: 'catalog', label: '资产', icon: <Database size={ICON_SIZE} /> },
      { key: 'vsources', label: '数据源', icon: <Link size={ICON_SIZE} /> },
      { key: 'metadata', label: '元数据', icon: <Tag size={ICON_SIZE} /> },
      { key: 'geojson', label: 'GeoJSON', icon: <MapPin size={ICON_SIZE} /> },
      { key: 'charts', label: '图表', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'topology', label: '拓扑', icon: <Network size={ICON_SIZE} /> },
    ],
  },
  {
    key: 'intelligence', label: '智能分析', icon: <Brain size={16} />,
    tabs: [
      { key: 'capabilities', label: '能力', icon: <Zap size={ICON_SIZE} /> },
      { key: 'tools', label: '工具', icon: <Wrench size={ICON_SIZE} /> },
      { key: 'kb', label: '知识库', icon: <BookOpen size={ICON_SIZE} /> },
      { key: 'suggestions', label: '建议', icon: <Lightbulb size={ICON_SIZE} /> },
      { key: 'memory', label: '记忆', icon: <Brain size={ICON_SIZE} /> },
      { key: 'market', label: '市场', icon: <Store size={ICON_SIZE} /> },
      { key: 'worldmodel', label: '世界模型', icon: <Globe size={ICON_SIZE} /> },
      { key: 'causal', label: '因果推理', icon: <FlaskConical size={ICON_SIZE} /> },
      { key: 'optimization', label: '优化', icon: <Target size={ICON_SIZE} /> },
    ],
  },
  {
    key: 'ops', label: '平台运营', icon: <Activity size={16} />,
    tabs: [
      { key: 'history', label: '历史', icon: <History size={ICON_SIZE} /> },
      { key: 'feedback', label: '反馈', icon: <ThumbsUp size={ICON_SIZE} /> },
      { key: 'usage', label: '用量', icon: <Gauge size={ICON_SIZE} /> },
      { key: 'analytics', label: '分析', icon: <PieChart size={ICON_SIZE} /> },
      { key: 'governance', label: '治理', icon: <Shield size={ICON_SIZE} /> },
      { key: 'qcmonitor', label: '质检', icon: <ClipboardCheck size={ICON_SIZE} /> },
      { key: 'alerts', label: '告警', icon: <Bell size={ICON_SIZE} /> },
      { key: 'observability', label: '追踪', icon: <Activity size={ICON_SIZE} /> },
      { key: 'messagebus', label: '消息总线', icon: <Radio size={ICON_SIZE} /> },
      { key: 'tasks', label: '任务', icon: <ListTodo size={ICON_SIZE} /> },
      { key: 'workflows', label: '工作流', icon: <GitBranch size={ICON_SIZE} /> },
      { key: 'templates', label: '模板', icon: <FileText size={ICON_SIZE} /> },
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
    const group = TAB_GROUPS.find(g => g.key === groupKey);
    if (group && !group.tabs.some(t => t.key === activeTab)) {
      setActiveTab(group.tabs[0].key);
    }
  };

  const currentGroup = TAB_GROUPS.find(g => g.key === activeGroup) || TAB_GROUPS[0];

  return (
    <div className="data-panel">
      <div className="data-panel-header">
        <LayoutGrid size={18} className="data-panel-header-icon" />
        <span>工作台</span>
      </div>

      {/* Group selector — 3 segments */}
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
        {activeTab === 'metadata' && <MetadataPanel />}
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
        {activeTab === 'qcmonitor' && <QcMonitorTab />}
        {activeTab === 'alerts' && <AlertsTab />}
        {activeTab === 'messagebus' && <MessageBusTab />}
        {activeTab === 'feedback' && <FeedbackTab />}
        {activeTab === 'topology' && <TopologyTab />}
      </div>
    </div>
  );
}

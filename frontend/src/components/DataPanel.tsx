import { useState, useCallback, type ReactNode } from 'react';
import {
  Upload, Table2, AlertTriangle, Wrench, Play, FileText,
  BookOpen, Settings, Users, Activity, BarChart3,
} from 'lucide-react';
import DataUploadTab, { type DatasetInfo } from './datapanel/DataUploadTab';
import FieldMatchTab from './datapanel/FieldMatchTab';
import GapReportTab from './datapanel/GapReportTab';
import AdjustmentTab from './datapanel/AdjustmentTab';
import ReportTab from './datapanel/ReportTab';
import KnowledgeTab from './datapanel/KnowledgeTab';
import KnowledgeManageTab from './datapanel/KnowledgeManageTab';
import ProjectOverviewTab from './datapanel/ProjectOverviewTab';
import UserManageTab from './datapanel/UserManageTab';
import OpsMonitorTab from './datapanel/OpsMonitorTab';
import SystemConfigTab from './datapanel/SystemConfigTab';

/* ---------- 治理场景 Tab 组件（剩余占位符）---------- */

function GovernanceProgressTab() {
  return (
    <div className="tab-content-placeholder">
      <Play size={40} strokeWidth={1} />
      <h3>治理进度</h3>
      <p>治理执行时展示实时进度（待底座环境就绪）</p>
    </div>
  );
}

/* ---------- Tab 定义 ---------- */

const ICON_SIZE = 14;

type TabKey = 'upload' | 'match' | 'gap' | 'adjust' | 'progress' | 'report' | 'knowledge'
  | 'km' | 'config' | 'users' | 'ops' | 'overview';

type GroupKey = 'operate' | 'manage';

interface TabDef {
  key: TabKey;
  label: string;
  icon: ReactNode;
}

const TAB_GROUPS: { key: GroupKey; label: string; tabs: TabDef[] }[] = [
  {
    key: 'operate', label: '治理操作',
    tabs: [
      { key: 'upload', label: '数据', icon: <Upload size={ICON_SIZE} /> },
      { key: 'match', label: '匹配', icon: <Table2 size={ICON_SIZE} /> },
      { key: 'gap', label: '差距', icon: <AlertTriangle size={ICON_SIZE} /> },
      { key: 'adjust', label: '建议', icon: <Wrench size={ICON_SIZE} /> },
      { key: 'progress', label: '进度', icon: <Play size={ICON_SIZE} /> },
      { key: 'report', label: '报告', icon: <FileText size={ICON_SIZE} /> },
      { key: 'knowledge', label: '知识库', icon: <BookOpen size={ICON_SIZE} /> },
    ],
  },
  {
    key: 'manage', label: '系统管理',
    tabs: [
      { key: 'km', label: '知识管理', icon: <BookOpen size={ICON_SIZE} /> },
      { key: 'config', label: '配置', icon: <Settings size={ICON_SIZE} /> },
      { key: 'overview', label: '总览', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'users', label: '用户', icon: <Users size={ICON_SIZE} /> },
      { key: 'ops', label: '运维', icon: <Activity size={ICON_SIZE} /> },
    ],
  },
];

/* ---------- DataPanel 主组件 ---------- */

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
  onMapUpdate?: (config: any) => void;
}

export default function DataPanel({ dataFile, userRole, onMapUpdate }: DataPanelProps) {
  const [activeGroup, setActiveGroup] = useState<GroupKey>('operate');
  const [activeTab, setActiveTab] = useState<TabKey>('upload');
  const isAdmin = userRole === 'admin';

  // 当前活跃的 dataset（上传后设置）
  const [currentDatasetId, setCurrentDatasetId] = useState<string | null>(null);
  // 标准对照结果（match 后设置，供 gap/report Tab 使用）
  const [matchResult, setMatchResult] = useState<any>(null);

  const handleDatasetLoaded = useCallback((ds: DatasetInfo, geojson: any) => {
    setCurrentDatasetId(ds.dataset_id);
    if (onMapUpdate && geojson) {
      onMapUpdate({
        layers: [{
          type: 'geojson',
          data: geojson,
          name: ds.filename,
          style: { color: '#22c55e', weight: 1, fillOpacity: 0.3 },
        }],
        bounds: ds.bounds,
      });
    }
  }, [onMapUpdate]);

  const handleAnalyzeRequest = useCallback((ds: DatasetInfo) => {
    setCurrentDatasetId(ds.dataset_id);
    setActiveTab('match');
  }, []);

  const handleMatchComplete = useCallback((result: any) => {
    setMatchResult(result);
  }, []);

  // 从 matchResult 中提取差距列表和统计
  const gaps = matchResult?.差距清单 ?? [];
  const matchRate = matchResult?.匹配率 ?? undefined;
  const gapCount = matchResult ? {
    high: gaps.filter((g: any) => g.严重程度 === 'high').length,
    medium: gaps.filter((g: any) => g.严重程度 === 'medium').length,
    low: gaps.filter((g: any) => g.严重程度 === 'low').length,
  } : undefined;

  const tabContent: Record<TabKey, () => ReactNode> = {
    upload: () => <DataUploadTab onDatasetLoaded={handleDatasetLoaded} onAnalyzeRequest={handleAnalyzeRequest} />,
    match: () => <FieldMatchTab datasetId={currentDatasetId} onMatchComplete={handleMatchComplete} />,
    gap: () => <GapReportTab gaps={gaps} matchRate={matchRate} />,
    adjust: () => <AdjustmentTab datasetId={currentDatasetId} />,
    progress: () => <GovernanceProgressTab />,
    report: () => <ReportTab datasetId={currentDatasetId} matchRate={matchRate} gapCount={gapCount} />,
    knowledge: () => <KnowledgeTab />,
    km: () => <KnowledgeManageTab />,    config: () => <SystemConfigTab />,
    users: () => <UserManageTab />,
    ops: () => <OpsMonitorTab />,
    overview: () => <ProjectOverviewTab />,  };

  const currentGroup = TAB_GROUPS.find(g => g.key === activeGroup);
  const visibleGroups = isAdmin ? TAB_GROUPS : TAB_GROUPS.filter(g => g.key !== 'manage');

  return (
    <div className="data-panel">
      {/* Group selector */}
      <div className="dp-group-bar">
        {visibleGroups.map(g => (
          <button
            key={g.key}
            className={`dp-group-btn ${activeGroup === g.key ? 'active' : ''}`}
            onClick={() => {
              setActiveGroup(g.key);
              setActiveTab(TAB_GROUPS.find(grp => grp.key === g.key)!.tabs[0].key);
            }}
          >
            {g.label}
          </button>
        ))}
      </div>

      {/* Tab bar */}
      <div className="dp-tab-bar">
        {currentGroup?.tabs.map(tab => (
          <button
            key={tab.key}
            className={`dp-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
            title={tab.label}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="dp-content">
        {tabContent[activeTab]?.() ?? <div>未知 Tab</div>}
      </div>
    </div>
  );
}

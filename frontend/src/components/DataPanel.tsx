import { useState, useCallback, type ReactNode } from 'react';
import {
  Upload, Table2, AlertTriangle, Wrench, Play, FileText,
  BookOpen, Settings, Users, Activity, BarChart3,
} from 'lucide-react';
import DataUploadTab, { type DatasetInfo } from './datapanel/DataUploadTab';

/* ---------- 治理场景 Tab 组件（除 DataUploadTab 外均为占位符）---------- */

function FieldMatchTab() {
  return (
    <div className="tab-content-placeholder">
      <Table2 size={40} strokeWidth={1} />
      <h3>字段匹配</h3>
      <p>上传数据后自动进行语义匹配分析</p>
    </div>
  );
}

function GapReportTab() {
  return (
    <div className="tab-content-placeholder">
      <AlertTriangle size={40} strokeWidth={1} />
      <h3>差距分析</h3>
      <p>标准对照完成后展示差距报告</p>
    </div>
  );
}

function AdjustmentTab() {
  return (
    <div className="tab-content-placeholder">
      <Wrench size={40} strokeWidth={1} />
      <h3>调整建议</h3>
      <p>模型推荐完成后展示调整方案</p>
    </div>
  );
}

function GovernanceProgressTab() {
  return (
    <div className="tab-content-placeholder">
      <Play size={40} strokeWidth={1} />
      <h3>治理进度</h3>
      <p>治理执行时展示实时进度</p>
    </div>
  );
}

function ReportTab() {
  return (
    <div className="tab-content-placeholder">
      <FileText size={40} strokeWidth={1} />
      <h3>治理报告</h3>
      <p>治理完成后预览和下载报告</p>
    </div>
  );
}

function KnowledgeTab() {
  return (
    <div className="tab-content-placeholder">
      <BookOpen size={40} strokeWidth={1} />
      <h3>知识库</h3>
      <p>查看和管理语义等价库、标准规则库、数据模型库</p>
    </div>
  );
}

/* ---------- 管理端 Tab 组件 ---------- */

function KnowledgeManageTab() {
  return (
    <div className="tab-content-placeholder">
      <BookOpen size={40} strokeWidth={1} />
      <h3>知识管理</h3>
      <p>语义等价库 CRUD / 标准文档上传解析 / 数据模型导入</p>
    </div>
  );
}

function SystemConfigTab() {
  return (
    <div className="tab-content-placeholder">
      <Settings size={40} strokeWidth={1} />
      <h3>系统配置</h3>
      <p>底座连接 / LLM 配置 / 存储配置</p>
    </div>
  );
}

function UserManageTab() {
  return (
    <div className="tab-content-placeholder">
      <Users size={40} strokeWidth={1} />
      <h3>用户管理</h3>
      <p>账号、角色、权限管理</p>
    </div>
  );
}

function OpsMonitorTab() {
  return (
    <div className="tab-content-placeholder">
      <Activity size={40} strokeWidth={1} />
      <h3>运维监控</h3>
      <p>Token 消耗 / 推荐采纳率 / 知识库命中率 / 操作日志</p>
    </div>
  );
}

function ProjectOverviewTab() {
  return (
    <div className="tab-content-placeholder">
      <BarChart3 size={40} strokeWidth={1} />
      <h3>项目总览</h3>
      <p>所有数据集治理进度汇总</p>
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

  const handleDatasetLoaded = useCallback((ds: DatasetInfo, geojson: any) => {
    // 通知地图面板渲染 GeoJSON
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
    // 切换到匹配 Tab 并触发分析
    setActiveTab('match');
    // TODO: 触发 AI 对话分析
  }, []);

  const tabContent: Record<TabKey, () => ReactNode> = {
    upload: () => <DataUploadTab onDatasetLoaded={handleDatasetLoaded} onAnalyzeRequest={handleAnalyzeRequest} />,
    match: () => <FieldMatchTab />,
    gap: () => <GapReportTab />,
    adjust: () => <AdjustmentTab />,
    progress: () => <GovernanceProgressTab />,
    report: () => <ReportTab />,
    knowledge: () => <KnowledgeTab />,
    km: () => <KnowledgeManageTab />,
    config: () => <SystemConfigTab />,
    users: () => <UserManageTab />,
    ops: () => <OpsMonitorTab />,
    overview: () => <ProjectOverviewTab />,
  };

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

import { useState, useEffect, type ReactNode } from 'react';
import Papa from 'papaparse';
import { useTranslation } from 'react-i18next';
import {
  FolderOpen, Table2, Database, Tag, Link, MapPin, BarChart3,
  Zap, Wrench, BookOpen, Lightbulb, Brain, Store, Globe, FlaskConical, Network,
  History, Gauge, PieChart, Shield, ClipboardCheck, Bell, Activity, Radio, ListTodo,
  GitBranch, FileText, Target, ThumbsUp, Tags, Sparkles,
  LayoutGrid, Home, Inbox, Upload, Droplets,
} from 'lucide-react';

import CatalogTab, { type MapPublicationLayer } from './datapanel/CatalogTab';
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
import WorldModelV11Tab from './datapanel/WorldModelV11Tab';
import WorldModelV2Tab from './datapanel/WorldModelV2Tab';
import WorldModelV21Tab from './datapanel/WorldModelV21Tab';
import IrrigationWorldModelDemoTab from './datapanel/IrrigationWorldModelDemoTab';
import TerritoryWorldModelTab from './datapanel/TerritoryWorldModelTab';
import AbuDhabiLandUseComparisonTab from './datapanel/AbuDhabiLandUseComparisonTab';
import AbuDhabiLandUseModelTab from './datapanel/AbuDhabiLandUseModelTab';
import TraditionalLivabilityTab from './datapanel/TraditionalLivabilityTab';
import TraditionalCulturalHeritageTab from './datapanel/TraditionalCulturalHeritageTab';
import CrossDomainImpactTab from './datapanel/CrossDomainImpactTab';
import ImplementationRoadmapTab from './datapanel/ImplementationRoadmapTab';
import ResilienceWorldModelTab from './datapanel/ResilienceWorldModelTab';
import DigitalReadinessTab from './datapanel/DigitalReadinessTab';
import OperationsQualityTab from './datapanel/OperationsQualityTab';
import BusinessLicenceTab from './datapanel/BusinessLicenceTab';
import DevelopmentControlTab from './datapanel/DevelopmentControlTab';
import FinancialReadinessTab from './datapanel/FinancialReadinessTab';
import PublicFeedbackReadinessTab from './datapanel/PublicFeedbackReadinessTab';
import SpatialScopeRegistryTab from './datapanel/SpatialScopeRegistryTab';
import PlanningVersionRegistryTab from './datapanel/PlanningVersionRegistryTab';
import ParcelStateReadinessTab from './datapanel/ParcelStateReadinessTab';
import InfrastructureNetworkReadinessTab from './datapanel/InfrastructureNetworkReadinessTab';
import AssetLifecycleReadinessTab from './datapanel/AssetLifecycleReadinessTab';
import PopulationDemographicReadinessTab from './datapanel/PopulationDemographicReadinessTab';
import PopulationHousingOptimizationTab from './datapanel/PopulationHousingOptimizationTab';
import LivabilityWorldModelTab from './datapanel/LivabilityWorldModelTab';
import UwmMultistageInterventionTab from './datapanel/UwmMultistageInterventionTab';
import AiDemandReadinessTab from './datapanel/AiDemandReadinessTab';
import CausalReasoningTab from './datapanel/CausalReasoningTab';
import OptimizationTab from './datapanel/OptimizationTab';
import QcMonitorTab from './datapanel/QcMonitorTab';
import AlertsTab from './datapanel/AlertsTab';
import TopologyTab from './datapanel/TopologyTab';
import AgentsTab from './datapanel/AgentsTab';
import MessageBusTab from './datapanel/MessageBusTab';
import AgentRunLogsTab from './datapanel/AgentRunLogsTab';
import MetadataPanel from './datapanel/MetadataPanel';
import FeedbackTab from './datapanel/FeedbackTab';
import DomainStandardsTab from './datapanel/DomainStandardsTab';
import StandardsTab from './datapanel/StandardsTab';
import IntakeTab from './datapanel/IntakeTab';
import OfflineIngestTab from './datapanel/OfflineIngestTab';
import SemanticLayerTab from './datapanel/SemanticLayerTab';
import ClassificationTab from './datapanel/ClassificationTab';
import FusionQualityTab from './datapanel/FusionQualityTab';
import DataModelWorkbenchTab from './datapanel/DataModelWorkbenchTab';
import OntologyTab from './datapanel/OntologyTab';
import NaturalResourceOntologyDemoTab from './datapanel/NaturalResourceOntologyDemoTab';
import ApprovalInboxTab from './datapanel/ApprovalInboxTab';
import { getLocaleHeaders } from '../i18n';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
  username?: string;
  onRequestWidth?: (width: number) => void;
  onAddMapLayer?: (layer: MapPublicationLayer) => void;
}

type TabKey = 'files' | 'table' | 'catalog' | 'models' | 'metadata' | 'history' | 'agent_logs' | 'usage' | 'tools' | 'workflows' | 'suggestions' | 'tasks' | 'templates' | 'analytics' | 'capabilities' | 'kb' | 'vsources' | 'market' | 'geojson' | 'charts' | 'governance' | 'approvals' | 'memory' | 'observability' | 'traditional_livability' | 'cultural_heritage' | 'cross_domain_impact' | 'implementation_roadmap' | 'resilience_kernel' | 'digital_readiness' | 'operations_quality' | 'business_licence' | 'development_control' | 'financial_readiness' | 'public_feedback_readiness' | 'spatial_scope_registry' | 'planning_version_registry' | 'parcel_state_readiness' | 'infrastructure_network_readiness' | 'asset_lifecycle_readiness' | 'population_demographic_readiness' | 'population_housing_optimization' | 'uwm_livability' | 'uwm_multistage' | 'ai_demand_readiness' | 'abu_land_use_compare' | 'abu_flus' | 'abu_kernel' | 'worldmodel' | 'worldmodel_v11' | 'worldmodel_v2' | 'worldmodel_v21' | 'irrigation_demo' | 'twm' | 'causal' | 'optimization' | 'qcmonitor' | 'fusion_quality' | 'alerts' | 'topology' | 'messagebus' | 'feedback' | 'standards' | 'std_platform' | 'semantic' | 'ontology' | 'ontology_demo' | 'agents' | 'intake' | 'offline_ingest' | 'classification';

type GroupKey = 'data' | 'intelligence' | 'ops';
type NavigationGroupKey = 'data' | 'semantic' | 'analysis' | 'ops' | 'extensions';

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
      { key: 'models', label: '数据模型', icon: <LayoutGrid size={ICON_SIZE} /> },
      { key: 'vsources', label: '数据源', icon: <Link size={ICON_SIZE} /> },
      { key: 'metadata', label: '元数据', icon: <Tag size={ICON_SIZE} /> },
      { key: 'geojson', label: 'GeoJSON', icon: <MapPin size={ICON_SIZE} /> },
      { key: 'charts', label: '图表', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'topology', label: '拓扑', icon: <Network size={ICON_SIZE} /> },
      { key: 'intake', label: '接入', icon: <LayoutGrid size={ICON_SIZE} /> },
      { key: 'offline_ingest', label: '离线入湖', icon: <Upload size={ICON_SIZE} /> },
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
      { key: 'traditional_livability', label: '城市宜居性分析（传统方法）', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'cultural_heritage', label: '文化遗产与场所', icon: <MapPin size={ICON_SIZE} /> },
      { key: 'cross_domain_impact', label: '跨领域影响与优先级', icon: <GitBranch size={ICON_SIZE} /> },
      { key: 'implementation_roadmap', label: '建议与实施路线图', icon: <ListTodo size={ICON_SIZE} /> },
      { key: 'resilience_kernel', label: '韧性世界模型', icon: <Shield size={ICON_SIZE} /> },
      { key: 'digital_readiness', label: '数字资产与智慧片区', icon: <Database size={ICON_SIZE} /> },
      { key: 'operations_quality', label: '运维与服务质量', icon: <Activity size={ICON_SIZE} /> },
      { key: 'business_licence', label: '企业执照与经济活动', icon: <Store size={ICON_SIZE} /> },
      { key: 'development_control', label: '开发控制规则', icon: <Shield size={ICON_SIZE} /> },
      { key: 'financial_readiness', label: '财务与投资证据', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'public_feedback_readiness', label: '公众反馈证据', icon: <ThumbsUp size={ICON_SIZE} /> },
      { key: 'spatial_scope_registry', label: '空间范围注册', icon: <MapPin size={ICON_SIZE} /> },
      { key: 'planning_version_registry', label: '规划与地块版本', icon: <FileText size={ICON_SIZE} /> },
      { key: 'parcel_state_readiness', label: '用地与地块状态', icon: <MapPin size={ICON_SIZE} /> },
      { key: 'infrastructure_network_readiness', label: '基础设施与市政管网', icon: <Network size={ICON_SIZE} /> },
      { key: 'asset_lifecycle_readiness', label: '资产生命周期', icon: <Wrench size={ICON_SIZE} /> },
      { key: 'population_demographic_readiness', label: '人口与人口结构', icon: <PieChart size={ICON_SIZE} /> },
      { key: 'population_housing_optimization', label: '人口住房配置', icon: <Home size={ICON_SIZE} /> },
      { key: 'uwm_livability', label: '城市宜居性分析（UWM）', icon: <Brain size={ICON_SIZE} /> },
      { key: 'uwm_multistage', label: 'UWM多阶段城市干预规划', icon: <GitBranch size={ICON_SIZE} /> },
      { key: 'ai_demand_readiness', label: 'AI应用需求矩阵', icon: <ClipboardCheck size={ICON_SIZE} /> },
      { key: 'abu_land_use_compare', label: '阿布扎比 · 三模型对比', icon: <BarChart3 size={ICON_SIZE} /> },
      { key: 'abu_flus', label: '阿布扎比 · GeoSOS-FLUS', icon: <LayoutGrid size={ICON_SIZE} /> },
      { key: 'abu_kernel', label: '阿布扎比 · Geospatial Kernel', icon: <Network size={ICON_SIZE} /> },
      { key: 'worldmodel', label: '世界模型', icon: <Globe size={ICON_SIZE} /> },
      { key: 'worldmodel_v11', label: '世界模型v1.1 · Paper58（阿布扎比）', icon: <Globe size={ICON_SIZE} /> },
      { key: 'worldmodel_v2', label: '世界模型v2', icon: <Globe size={ICON_SIZE} /> },
      { key: 'worldmodel_v21', label: '世界模型v2.1', icon: <Globe size={ICON_SIZE} /> },
      { key: 'irrigation_demo', label: '灌区世界模型', icon: <Droplets size={ICON_SIZE} /> },
      { key: 'twm', label: 'TWM', icon: <Shield size={ICON_SIZE} /> },
      { key: 'causal', label: '因果推理', icon: <FlaskConical size={ICON_SIZE} /> },
      { key: 'optimization', label: '优化', icon: <Target size={ICON_SIZE} /> },
      { key: 'standards', label: '领域标准', icon: <Database size={ICON_SIZE} /> },
      { key: 'std_platform', label: '数据标准', icon: <FileText size={ICON_SIZE} /> },
      { key: 'agents', label: '智能体', icon: <Network size={ICON_SIZE} /> },
      { key: 'semantic', label: '语义层', icon: <Tags size={ICON_SIZE} /> },
      { key: 'ontology', label: '本体模型', icon: <Network size={ICON_SIZE} /> },
      { key: 'ontology_demo', label: '本体应用', icon: <Sparkles size={ICON_SIZE} /> },
    ],
  },
  {
    key: 'ops', label: '平台运营', icon: <Activity size={16} />,
    tabs: [
      { key: 'history', label: '历史', icon: <History size={ICON_SIZE} /> },
      { key: 'agent_logs', label: '运行日志', icon: <FileText size={ICON_SIZE} /> },
      { key: 'feedback', label: '反馈', icon: <ThumbsUp size={ICON_SIZE} /> },
      { key: 'usage', label: '用量', icon: <Gauge size={ICON_SIZE} /> },
      { key: 'analytics', label: '分析', icon: <PieChart size={ICON_SIZE} /> },
      { key: 'governance', label: '治理', icon: <Shield size={ICON_SIZE} /> },
      { key: 'approvals', label: '审批中心', icon: <Inbox size={ICON_SIZE} /> },
      { key: 'classification', label: '分级', icon: <Shield size={ICON_SIZE} /> },
      { key: 'qcmonitor', label: '质检', icon: <ClipboardCheck size={ICON_SIZE} /> },
      { key: 'fusion_quality', label: '融合质量', icon: <GitBranch size={ICON_SIZE} /> },
      { key: 'alerts', label: '告警', icon: <Bell size={ICON_SIZE} /> },
      { key: 'observability', label: '追踪', icon: <Activity size={ICON_SIZE} /> },
      { key: 'messagebus', label: '消息总线', icon: <Radio size={ICON_SIZE} /> },
      { key: 'tasks', label: '任务', icon: <ListTodo size={ICON_SIZE} /> },
      { key: 'workflows', label: '工作流', icon: <GitBranch size={ICON_SIZE} /> },
      { key: 'templates', label: '模板', icon: <FileText size={ICON_SIZE} /> },
    ],
  },
];

interface NavigationItem {
  tab_key: TabKey;
  label: string;
  icon: ReactNode;
  group_key: NavigationGroupKey;
  section_key: string;
  sort_order: number;
  group_sort_order?: number;
  section_sort_order?: number;
}

interface NavigationSection {
  key: string;
  label: string;
  sort_order: number;
  items: NavigationItem[];
}

interface NavigationGroup {
  key: NavigationGroupKey;
  label: string;
  icon: ReactNode;
  sort_order: number;
  sections: NavigationSection[];
}

interface NavigationConfig {
  groups: NavigationGroup[];
}

const NAVIGATION_GROUPS: Array<{
  key: NavigationGroupKey;
  label: string;
  icon: ReactNode;
  sort_order: number;
  sections: Array<{ key: string; label: string; sort_order: number }>;
}> = [
  {
    key: 'data', label: '数据资源', icon: <Database size={16} />, sort_order: 10,
    sections: [
      { key: 'browse', label: '文件与数据浏览', sort_order: 10 },
      { key: 'assets', label: '数据资产', sort_order: 20 },
      { key: 'ingest', label: '数据接入', sort_order: 30 },
    ],
  },
  {
    key: 'semantic', label: '标准与语义', icon: <Tags size={16} />, sort_order: 20,
    sections: [
      { key: 'standards', label: '标准体系', sort_order: 10 },
      { key: 'models', label: '语义模型', sort_order: 20 },
      { key: 'governance', label: '治理与审批', sort_order: 30 },
    ],
  },
  {
    key: 'analysis', label: '分析与模型', icon: <Brain size={16} />, sort_order: 30,
    sections: [
      { key: 'general', label: '通用分析', sort_order: 10 },
      { key: 'domain', label: '领域专题', sort_order: 20 },
      { key: 'world_models', label: '世界模型', sort_order: 30 },
      { key: 'regional', label: '区域与实验模型', sort_order: 40 },
    ],
  },
  {
    key: 'ops', label: '运营与质量', icon: <Activity size={16} />, sort_order: 40,
    sections: [
      { key: 'tasks', label: '任务与流程', sort_order: 10 },
      { key: 'monitoring', label: '运行监控', sort_order: 20 },
      { key: 'quality', label: '质量与评估', sort_order: 30 },
    ],
  },
  {
    key: 'extensions', label: '扩展能力', icon: <LayoutGrid size={16} />, sort_order: 50,
    sections: [
      { key: 'agent', label: '智能体与知识', sort_order: 10 },
      { key: 'market', label: '市场与扩展', sort_order: 20 },
    ],
  },
];

const DATA_TABS = new Set<TabKey>([
  'files', 'table', 'geojson', 'topology', 'catalog', 'models', 'metadata', 'vsources', 'intake', 'offline_ingest',
]);
const SEMANTIC_TABS = new Set<TabKey>([
  'standards', 'std_platform', 'semantic', 'ontology', 'ontology_demo', 'classification', 'governance', 'approvals',
]);
const OPS_TABS = new Set<TabKey>([
  'history', 'agent_logs', 'usage', 'analytics', 'feedback', 'qcmonitor', 'alerts',
  'observability', 'messagebus', 'tasks', 'workflows', 'templates',
]);
const EXTENSION_TABS = new Set<TabKey>([
  'kb', 'suggestions', 'memory', 'market', 'agents',
]);
const WORLD_MODEL_TABS = new Set<TabKey>([
  'worldmodel', 'worldmodel_v11', 'worldmodel_v2', 'worldmodel_v21', 'irrigation_demo', 'twm', 'uwm_livability', 'uwm_multistage',
]);
const REGIONAL_TABS = new Set<TabKey>(['abu_land_use_compare', 'abu_flus', 'abu_kernel']);
const DOMAIN_TABS = new Set<TabKey>([
  'traditional_livability', 'cultural_heritage', 'cross_domain_impact', 'implementation_roadmap', 'resilience_kernel',
  'digital_readiness', 'operations_quality', 'business_licence', 'development_control', 'financial_readiness',
  'public_feedback_readiness', 'spatial_scope_registry', 'planning_version_registry', 'parcel_state_readiness',
  'infrastructure_network_readiness', 'asset_lifecycle_readiness', 'population_demographic_readiness',
  'population_housing_optimization', 'ai_demand_readiness',
]);

function fallbackNavigation(): NavigationConfig {
  const flat = TAB_GROUPS.flatMap(group => group.tabs);
  const groups = NAVIGATION_GROUPS.map(group => ({
    ...group,
    sections: group.sections.map(section => ({ ...section, items: [] as NavigationItem[] })),
  }));
  const groupFor = (tab: TabKey): NavigationGroupKey => {
    if (DATA_TABS.has(tab)) return 'data';
    if (SEMANTIC_TABS.has(tab)) return 'semantic';
    if (OPS_TABS.has(tab)) return 'ops';
    if (EXTENSION_TABS.has(tab)) return 'extensions';
    return 'analysis';
  };
  const sectionFor = (tab: TabKey, group: NavigationGroupKey): string => {
    if (group === 'data') {
      if (['catalog', 'models', 'metadata'].includes(tab)) return 'assets';
      if (['vsources', 'intake', 'offline_ingest'].includes(tab)) return 'ingest';
      return 'browse';
    }
    if (group === 'semantic') {
      if (['standards', 'std_platform'].includes(tab)) return 'standards';
      if (['semantic', 'ontology', 'ontology_demo'].includes(tab)) return 'models';
      return 'governance';
    }
    if (group === 'ops') {
      if (['tasks', 'workflows', 'templates'].includes(tab)) return 'tasks';
      if (['history', 'agent_logs', 'alerts', 'observability', 'messagebus'].includes(tab)) return 'monitoring';
      return 'quality';
    }
    if (group === 'extensions') return tab === 'market' ? 'market' : 'agent';
    if (WORLD_MODEL_TABS.has(tab)) return 'world_models';
    if (REGIONAL_TABS.has(tab)) return 'regional';
    if (DOMAIN_TABS.has(tab)) return 'domain';
    return 'general';
  };
  flat.forEach((tab) => {
    const groupKey = groupFor(tab.key);
    const sectionKey = sectionFor(tab.key, groupKey);
    const group = groups.find(candidate => candidate.key === groupKey);
    const section = group?.sections.find(candidate => candidate.key === sectionKey);
    if (!section) return;
    section.items.push({
      tab_key: tab.key,
      label: tab.label,
      icon: tab.icon,
      group_key: groupKey,
      section_key: sectionKey,
      sort_order: section.items.length,
    });
  });
  return { groups };
}

const ICONS: Record<string, ReactNode> = {
  database: <Database size={14} />, tags: <Tags size={14} />, brain: <Brain size={14} />, activity: <Activity size={14} />,
  puzzle: <LayoutGrid size={14} />, folder: <FolderOpen size={14} />, table: <Table2 size={14} />, 'map-pin': <MapPin size={14} />,
  network: <Network size={14} />, layout: <LayoutGrid size={14} />, tag: <Tag size={14} />, link: <Link size={14} />, inbox: <Inbox size={14} />,
  'file-text': <FileText size={14} />, sparkles: <Sparkles size={14} />, shield: <Shield size={14} />, zap: <Zap size={14} />, wrench: <Wrench size={14} />,
  'book-open': <BookOpen size={14} />, 'bar-chart': <BarChart3 size={14} />, flask: <FlaskConical size={14} />, target: <Target size={14} />, 'git-branch': <GitBranch size={14} />,
  globe: <Globe size={14} />, droplets: <Droplets size={14} />, 'list-todo': <ListTodo size={14} />, store: <Store size={14} />, 'thumbs-up': <ThumbsUp size={14} />, 'pie-chart': <PieChart size={14} />,
  home: <Home size={14} />, history: <History size={14} />, bell: <Bell size={14} />, gauge: <Gauge size={14} />, radio: <Radio size={14} />,
  'layout-grid': <LayoutGrid size={14} />, 'clipboard-check': <ClipboardCheck size={14} />, lightbulb: <Lightbulb size={14} />, upload: <Upload size={14} />,
};

function normalizeNavigation(payload: any): NavigationConfig | null {
  if (!payload || !Array.isArray(payload.groups)) return null;
  const groups: NavigationGroup[] = payload.groups.map((group: any) => ({
    key: group.key as NavigationGroupKey,
    label: String(group.label || group.key),
    icon: ICONS[group.icon] || <LayoutGrid size={16} />,
    sort_order: Number(group.sort_order || 0),
    sections: Array.isArray(group.sections) ? group.sections.map((section: any) => ({
      key: String(section.key),
      label: String(section.label || section.key),
      sort_order: Number(section.sort_order || 0),
      items: Array.isArray(section.items) ? section.items.map((item: any) => ({
        tab_key: item.tab_key as TabKey,
        label: String(item.label || item.tab_key),
        icon: ICONS[item.icon] || <LayoutGrid size={14} />,
        group_key: group.key as NavigationGroupKey,
        section_key: String(section.key),
        sort_order: Number(item.sort_order || 0),
        group_sort_order: Number(item.group_sort_order || group.sort_order || 0),
        section_sort_order: Number(item.section_sort_order || section.sort_order || 0),
      })) : [],
    })) : [],
  })).filter((group: NavigationGroup) => group.sections.some(section => section.items.length));
  return { groups };
}

export default function DataPanel({
  dataFile,
  userRole,
  username,
  onRequestWidth,
  onAddMapLayer,
}: DataPanelProps) {
  const { t } = useTranslation('common');
  const [activeTab, setActiveTab] = useState<TabKey>('files');
  const [navigation, setNavigation] = useState<NavigationConfig>(() => fallbackNavigation());
  const [activeGroup, setActiveGroup] = useState<NavigationGroupKey>('data');
  const [activeSection, setActiveSection] = useState('browse');
  const [tableData, setTableData] = useState<any[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/workspace/navigation', {
      credentials: 'include',
      headers: getLocaleHeaders(),
    })
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (!cancelled) {
          const resolved = normalizeNavigation(payload);
          if (resolved) setNavigation(resolved);
        }
      })
      .catch(() => { /* fallback registry remains active */ });
    return () => { cancelled = true; };
  }, [userRole, username, t]);

  const allNavigationItems = navigation.groups.flatMap(group => group.sections.flatMap(section => section.items));
  const findNavigationItem = (tab: TabKey) => allNavigationItems.find(item => item.tab_key === tab);
  const firstNavigationItem = navigation.groups[0]?.sections[0]?.items[0];

  const selectFirstAvailableTab = (preferred: TabKey) => {
    const item = findNavigationItem(preferred) || firstNavigationItem;
    if (!item) return;
    setActiveTab(item.tab_key);
    setActiveGroup(item.group_key);
    setActiveSection(item.section_key);
  };

  useEffect(() => {
    const selected = findNavigationItem(activeTab);
    if (selected) {
      setActiveGroup(selected.group_key);
      setActiveSection(selected.section_key);
      return;
    }
    if (firstNavigationItem) {
      setActiveGroup(firstNavigationItem.group_key);
      setActiveSection(firstNavigationItem.section_key);
      setActiveTab(firstNavigationItem.tab_key);
    }
  }, [navigation]);

  useEffect(() => {
    if (!dataFile) return;
    loadCsvData(dataFile);
    selectFirstAvailableTab('table');
  }, [dataFile]);

  useEffect(() => {
    const handleWorkspaceUpdate = (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent).detail || {};
      const tab = detail.tab as TabKey;
      if (tab !== 'ontology' && tab !== 'ontology_demo') return;
      const item = findNavigationItem(tab);
      if (!item) return;
      setActiveTab(tab);
      setActiveGroup(item.group_key);
      setActiveSection(item.section_key);
      onRequestWidth?.(tab === 'ontology' ? 980 : 760);
    };
    window.addEventListener('gda-workspace-update', handleWorkspaceUpdate);
    return () => window.removeEventListener('gda-workspace-update', handleWorkspaceUpdate);
  }, [navigation, onRequestWidth]);

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
    const item = findNavigationItem(tab);
    if (!item) return;
    setActiveTab(tab);
    setActiveGroup(item.group_key);
    setActiveSection(item.section_key);
    if (tab === 'models') onRequestWidth?.(680);
    else if (tab === 'capabilities') onRequestWidth?.(720);
    else if (tab === 'ontology') onRequestWidth?.(980);
    else if (tab === 'ontology_demo') onRequestWidth?.(760);
    else if (tab === 'approvals') onRequestWidth?.(740);
    else if (tab === 'population_housing_optimization') onRequestWidth?.(720);
    else if (tab === 'uwm_livability' || tab === 'uwm_multistage') onRequestWidth?.(680);
    else if (tab === 'abu_land_use_compare' || tab === 'abu_flus' || tab === 'abu_kernel' || tab === 'worldmodel_v11') onRequestWidth?.(700);
    else if (tab === 'irrigation_demo') onRequestWidth?.(1180);
  };

  const handleGroupClick = (groupKey: NavigationGroupKey) => {
    setActiveGroup(groupKey);
    const group = navigation.groups.find(g => g.key === groupKey);
    const section = group?.sections[0];
    if (section) {
      setActiveSection(section.key);
      if (section.items[0]) setActiveTab(section.items[0].tab_key);
    }
  };

  const currentGroup = navigation.groups.find(g => g.key === activeGroup) || navigation.groups[0];
  const currentSection = currentGroup?.sections.find(section => section.key === activeSection) || currentGroup?.sections[0];
  const hasVisibleNavigation = navigation.groups.length > 0;
  const navigationLabel = (
    kind: 'groups' | 'sections' | 'tabs',
    key: string,
    fallback: string,
  ) => t(`dataPanel.${kind}.${key}`, { defaultValue: fallback });

  return (
    <div className="data-panel">
      <div className="data-panel-header">
        <LayoutGrid size={18} className="data-panel-header-icon" />
        <span>{t('dataPanel.title')}</span>
      </div>

      {/* Primary group selector */}
      <div className="data-panel-groups">
        {navigation.groups.map(g => (
          <button
            key={g.key}
            className={`data-panel-group ${activeGroup === g.key ? 'active' : ''}`}
            onClick={() => handleGroupClick(g.key)}
            title={navigationLabel('groups', g.key, g.label)}
          >
            <span className="group-icon">{g.icon}</span>
            <span className="group-label">{navigationLabel('groups', g.key, g.label)}</span>
            <span className="group-count">{g.sections.reduce((count, section) => count + section.items.length, 0)}</span>
          </button>
        ))}
      </div>

      {/* Second-level section selector */}
      {currentGroup && currentGroup.sections.length > 1 && (
        <div className="data-panel-sections">
          {currentGroup.sections.map(section => (
            <button
              key={section.key}
              className={`data-panel-section ${activeSection === section.key ? 'active' : ''}`}
              onClick={() => {
                setActiveSection(section.key);
                if (section.items[0]) setActiveTab(section.items[0].tab_key);
              }}
            >
              {navigationLabel('sections', section.key, section.label)}<span>{section.items.length}</span>
            </button>
          ))}
        </div>
      )}

      {/* Tabs within active section */}
      <div className="data-panel-tabs">
        {(currentSection?.items || []).map(t => (
          <button
            key={t.tab_key}
            className={`data-panel-tab ${activeTab === t.tab_key ? 'active' : ''}`}
            onClick={() => handleTabClick(t.tab_key)}
            title={navigationLabel('tabs', t.tab_key, t.label)}
          >
            <span className="tab-icon">{t.icon}</span>
            {navigationLabel('tabs', t.tab_key, t.label)}
          </button>
        ))}
      </div>

      <div className="data-panel-content">
        {!hasVisibleNavigation && <div className="data-panel-empty">{t('dataPanel.empty')}</div>}
        {hasVisibleNavigation && <>
        {activeTab === 'files' && <FileManager onFileClick={(name) => { loadCsvData(name); handleTabClick('table'); }} />}
        {activeTab === 'table' && <DataTable columns={tableColumns} data={tableData} loading={loading} />}
        {activeTab === 'catalog' && (
          <CatalogTab
            userRole={userRole}
            username={username}
            onAddMapLayer={onAddMapLayer}
          />
        )}
        {activeTab === 'models' && <DataModelWorkbenchTab userRole={userRole} />}
        {activeTab === 'metadata' && <MetadataPanel />}
        {activeTab === 'history' && <HistoryTab />}
        {activeTab === 'agent_logs' && <AgentRunLogsTab />}
        {activeTab === 'usage' && <UsageTab />}
        {activeTab === 'tools' && <ToolsTab userRole={userRole} />}
        {activeTab === 'workflows' && <WorkflowsTab />}
        {activeTab === 'suggestions' && <SuggestionsTab />}
        {activeTab === 'tasks' && <TasksTab />}
        {activeTab === 'templates' && <TemplatesTab />}
        {activeTab === 'analytics' && <AnalyticsTab />}
        {activeTab === 'governance' && <GovernanceTab />}
        {activeTab === 'approvals' && <ApprovalInboxTab userRole={userRole} username={username} />}
        {activeTab === 'classification' && <ClassificationTab />}
        {activeTab === 'memory' && <MemorySearchTab />}
        {activeTab === 'observability' && <ObservabilityTab />}
        {activeTab === 'capabilities' && <CapabilitiesTab userRole={userRole} />}
        {activeTab === 'kb' && <KnowledgeBaseTab />}
        {activeTab === 'vsources' && <VirtualSourcesTab />}
        {activeTab === 'market' && <MarketplaceTab />}
        {activeTab === 'geojson' && <GeoJsonEditorTab />}
        {activeTab === 'charts' && <ChartsTab />}
        {activeTab === 'traditional_livability' && <TraditionalLivabilityTab />}
        {activeTab === 'cultural_heritage' && <TraditionalCulturalHeritageTab />}
        {activeTab === 'cross_domain_impact' && <CrossDomainImpactTab />}
        {activeTab === 'implementation_roadmap' && <ImplementationRoadmapTab />}
        {activeTab === 'resilience_kernel' && <ResilienceWorldModelTab />}
        {activeTab === 'digital_readiness' && <DigitalReadinessTab />}
        {activeTab === 'operations_quality' && <OperationsQualityTab />}
        {activeTab === 'business_licence' && <BusinessLicenceTab />}
        {activeTab === 'development_control' && <DevelopmentControlTab />}
        {activeTab === 'financial_readiness' && <FinancialReadinessTab />}
        {activeTab === 'public_feedback_readiness' && <PublicFeedbackReadinessTab />}
        {activeTab === 'spatial_scope_registry' && <SpatialScopeRegistryTab />}
        {activeTab === 'planning_version_registry' && <PlanningVersionRegistryTab />}
        {activeTab === 'parcel_state_readiness' && <ParcelStateReadinessTab />}
        {activeTab === 'infrastructure_network_readiness' && <InfrastructureNetworkReadinessTab />}
        {activeTab === 'asset_lifecycle_readiness' && <AssetLifecycleReadinessTab />}
        {activeTab === 'population_demographic_readiness' && <PopulationDemographicReadinessTab />}
        {activeTab === 'population_housing_optimization' && <PopulationHousingOptimizationTab />}
        {activeTab === 'uwm_livability' && <LivabilityWorldModelTab />}
        {activeTab === 'uwm_multistage' && <UwmMultistageInterventionTab />}
        {activeTab === 'ai_demand_readiness' && <AiDemandReadinessTab />}
        {activeTab === 'abu_land_use_compare' && <AbuDhabiLandUseComparisonTab />}
        {activeTab === 'abu_flus' && <AbuDhabiLandUseModelTab modelId="geosos_flus" />}
        {activeTab === 'abu_kernel' && <AbuDhabiLandUseModelTab modelId="geospatial_kernel" />}
        {activeTab === 'worldmodel' && <WorldModelTab />}
        {activeTab === 'worldmodel_v11' && <WorldModelV11Tab />}
        {activeTab === 'worldmodel_v2' && <WorldModelV2Tab />}
        {activeTab === 'worldmodel_v21' && <WorldModelV21Tab />}
        {activeTab === 'irrigation_demo' && <IrrigationWorldModelDemoTab />}
        {activeTab === 'twm' && <TerritoryWorldModelTab />}
        {activeTab === 'causal' && <CausalReasoningTab />}
        {activeTab === 'optimization' && <OptimizationTab />}
        {activeTab === 'qcmonitor' && <QcMonitorTab />}
        {activeTab === 'fusion_quality' && <FusionQualityTab />}
        {activeTab === 'alerts' && <AlertsTab />}
        {activeTab === 'messagebus' && <MessageBusTab />}
        {activeTab === 'feedback' && <FeedbackTab />}
        {activeTab === 'topology' && <TopologyTab />}
        {activeTab === 'agents' && <AgentsTab />}
        {activeTab === 'intake' && <IntakeTab />}
        {activeTab === 'offline_ingest' && <OfflineIngestTab />}
        {activeTab === 'standards' && <DomainStandardsTab />}
        {activeTab === 'std_platform' && <StandardsTab userRole={userRole} username={username} />}
        {activeTab === 'semantic' && <SemanticLayerTab userRole={userRole} />}
        {activeTab === 'ontology' && <OntologyTab userRole={userRole} />}
        {activeTab === 'ontology_demo' && <NaturalResourceOntologyDemoTab />}
        </>}
      </div>
    </div>
  );
}

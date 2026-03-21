import { useState, useEffect } from 'react';
import Papa from 'papaparse';

import CatalogTab from './datapanel/CatalogTab';
import HistoryTab from './datapanel/HistoryTab';
import UsageTab from './datapanel/UsageTab';
import ToolsTab from './datapanel/ToolsTab';
import CapabilitiesTab from './datapanel/CapabilitiesTab';
import KnowledgeBaseTab from './datapanel/KnowledgeBaseTab';
import WorkflowsTab from './datapanel/WorkflowsTab';
import { FileList, DataTable } from './datapanel/FileListTab';
import SuggestionsTab from './datapanel/SuggestionsTab';
import TasksTab from './datapanel/TasksTab';
import TemplatesTab from './datapanel/TemplatesTab';
import AnalyticsTab from './datapanel/AnalyticsTab';
import VirtualSourcesTab from './datapanel/VirtualSourcesTab';
import MarketplaceTab from './datapanel/MarketplaceTab';
import GeoJsonEditorTab from './datapanel/GeoJsonEditorTab';

interface DataPanelProps {
  dataFile: string | null;
  userRole?: string;
}

type TabKey = 'files' | 'table' | 'catalog' | 'history' | 'usage' | 'tools' | 'workflows' | 'suggestions' | 'tasks' | 'templates' | 'analytics' | 'capabilities' | 'kb' | 'vsources' | 'market' | 'geojson';

interface FileInfo {
  name: string;
  size: number;
  modified: string;
  type: string;
}

export default function DataPanel({ dataFile, userRole }: DataPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('files');
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [tableData, setTableData] = useState<any[]>([]);
  const [tableColumns, setTableColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchFiles();
    const interval = setInterval(fetchFiles, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!dataFile) return;
    loadCsvData(dataFile);
    setActiveTab('table');
  }, [dataFile]);

  const fetchFiles = async () => {
    try {
      const resp = await fetch('/api/user/files', { credentials: 'include' });
      if (resp.ok) setFiles(await resp.json());
    } catch { /* ignore */ }
  };

  const loadCsvData = async (filename: string) => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/user/files/${filename}`, { credentials: 'include' });
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

  const handleFileClick = (file: FileInfo) => {
    if (file.type === 'csv') { loadCsvData(file.name); setActiveTab('table'); }
    else {
      window.open(`/api/user/files/${encodeURIComponent(file.name)}`, '_blank');
    }
  };

  return (
    <div className="data-panel">
      <div className="data-panel-header">
        <svg className="data-panel-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
        </svg>
        <span>数据</span>
      </div>

      <div className="data-panel-tabs">
        <button className={`data-panel-tab ${activeTab === 'files' ? 'active' : ''}`}
          onClick={() => setActiveTab('files')}>文件</button>
        <button className={`data-panel-tab ${activeTab === 'table' ? 'active' : ''}`}
          onClick={() => setActiveTab('table')}>表格</button>
        <button className={`data-panel-tab ${activeTab === 'catalog' ? 'active' : ''}`}
          onClick={() => setActiveTab('catalog')}>资产</button>
        <button className={`data-panel-tab ${activeTab === 'history' ? 'active' : ''}`}
          onClick={() => setActiveTab('history')}>历史</button>
        <button className={`data-panel-tab ${activeTab === 'usage' ? 'active' : ''}`}
          onClick={() => setActiveTab('usage')}>用量</button>
        <button className={`data-panel-tab ${activeTab === 'tools' ? 'active' : ''}`}
          onClick={() => setActiveTab('tools')}>工具</button>
        <button className={`data-panel-tab ${activeTab === 'workflows' ? 'active' : ''}`}
          onClick={() => setActiveTab('workflows')}>工作流</button>
        <button className={`data-panel-tab ${activeTab === 'suggestions' ? 'active' : ''}`}
          onClick={() => setActiveTab('suggestions')}>建议</button>
        <button className={`data-panel-tab ${activeTab === 'tasks' ? 'active' : ''}`}
          onClick={() => setActiveTab('tasks')}>任务</button>
        <button className={`data-panel-tab ${activeTab === 'templates' ? 'active' : ''}`}
          onClick={() => setActiveTab('templates')}>模板</button>
        <button className={`data-panel-tab ${activeTab === 'analytics' ? 'active' : ''}`}
          onClick={() => setActiveTab('analytics')}>分析</button>
        <button className={`data-panel-tab ${activeTab === 'capabilities' ? 'active' : ''}`}
          onClick={() => setActiveTab('capabilities')}>能力</button>
        <button className={`data-panel-tab ${activeTab === 'kb' ? 'active' : ''}`}
          onClick={() => setActiveTab('kb')}>知识库</button>
        <button className={`data-panel-tab ${activeTab === 'vsources' ? 'active' : ''}`}
          onClick={() => setActiveTab('vsources')}>数据源</button>
        <button className={`data-panel-tab ${activeTab === 'market' ? 'active' : ''}`}
          onClick={() => setActiveTab('market')}>市场</button>
        <button className={`data-panel-tab ${activeTab === 'geojson' ? 'active' : ''}`}
          onClick={() => setActiveTab('geojson')}>GeoJSON</button>
      </div>

      <div className="data-panel-content">
        {activeTab === 'files' && <FileList files={files} onFileClick={handleFileClick} />}
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
        {activeTab === 'capabilities' && <CapabilitiesTab userRole={userRole} />}
        {activeTab === 'kb' && <KnowledgeBaseTab />}
        {activeTab === 'vsources' && <VirtualSourcesTab />}
        {activeTab === 'market' && <MarketplaceTab />}
        {activeTab === 'geojson' && <GeoJsonEditorTab />}
      </div>
    </div>
  );
}

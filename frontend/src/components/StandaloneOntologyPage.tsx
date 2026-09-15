import { BarChart3, ChevronRight } from 'lucide-react';
import { useAuth } from '@chainlit/react-client';
import OntologyTab from './datapanel/OntologyTab';
import LoginPage from './LoginPage';
import LanguageSwitcher from './LanguageSwitcher';
import './StandaloneOntologyPage.css';

/**
 * A focused ontology workbench route. It reuses the authenticated registry and
 * draft APIs so industry profiles (including DMT) and governed modeling are
 * available outside the wider three-panel GIS workspace.
 */
export default function StandaloneOntologyPage() {
  const { user, isReady, isAuthenticated, setUserFromAPI } = useAuth();
  const initialConceptId = new URLSearchParams(window.location.search).get('concept_id') || '';
  const userRole = String((user?.metadata as any)?.role || '');

  if (!isReady) return <div className="ontology-state">正在加载本体工作台</div>;
  // This route is the editable ontology workbench, so it always requires an
  // authenticated user even when the general chat is running in guest mode.
  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={() => { void setUserFromAPI(); }} />;
  }

  return (
    <div className="standalone-ontology-page">
      <div className="cim-page-body">
        <main className="cim-main-content">
          <div className="cim-breadcrumb">
            <span>本体模型中心</span><ChevronRight size={12} /><strong>行业本体模型</strong>
            <span className="cim-breadcrumb-spacer" />
            <a className="cim-workbench-link" href="/metric-management"><BarChart3 size={13} />指标管理</a>
            <LanguageSwitcher compact />
          </div>
          <h1 className="cim-visually-hidden">行业本体模型</h1>
          <section className="cim-ontology-viewer" aria-label="行业本体模型工作台">
            <OntologyTab
              apiBase="/api/ontology"
              userRole={userRole}
              allowExport
              showTechnicalStatus
              initialConceptId={initialConceptId}
              className="standalone-ontology-workbench"
            />
          </section>
        </main>
      </div>
    </div>
  );
}

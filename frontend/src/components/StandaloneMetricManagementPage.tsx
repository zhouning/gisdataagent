import { Network, ChevronRight } from 'lucide-react';
import { useAuth } from '@chainlit/react-client';
import SemanticLayerTab from './datapanel/SemanticLayerTab';
import LoginPage from './LoginPage';
import LanguageSwitcher from './LanguageSwitcher';
import './StandaloneOntologyPage.css';

/** A direct, authenticated route for governed metric contracts and composition. */
export default function StandaloneMetricManagementPage() {
  const { user, isReady, isAuthenticated, setUserFromAPI } = useAuth();
  const userRole = String((user?.metadata as any)?.role || '');

  if (!isReady) return <div className="ontology-state">正在加载指标管理工作台</div>;
  if (!isAuthenticated) return <LoginPage onLoginSuccess={() => { void setUserFromAPI(); }} />;

  return (
    <div className="standalone-ontology-page">
      <div className="cim-page-body">
        <main className="cim-main-content">
          <div className="cim-breadcrumb">
            <span>语义层中心</span><ChevronRight size={12} /><strong>指标管理</strong>
            <span className="cim-breadcrumb-spacer" />
            <a className="cim-workbench-link" href="/ontology-model"><Network size={13} />本体模型</a>
            <LanguageSwitcher compact />
          </div>
          <h1 className="cim-visually-hidden">指标管理</h1>
          <section className="cim-semantic-viewer" aria-label="指标管理工作台">
            <SemanticLayerTab userRole={userRole} initialView="metrics" />
          </section>
        </main>
      </div>
    </div>
  );
}

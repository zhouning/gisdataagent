import { ChevronRight } from 'lucide-react';
import OntologyTab from './datapanel/OntologyTab';
import LanguageSwitcher from './LanguageSwitcher';
import './StandaloneOntologyPage.css';

/**
 * A CIM-facing, unauthenticated shell around the read-only ontology browser.
 * The ontology workbench itself stays shared with the authenticated GIS view,
 * while this route deliberately points it at the bounded public API.
 */
export default function StandaloneOntologyPage() {
  const initialConceptId = new URLSearchParams(window.location.search).get('concept_id') || '';

  return (
    <div className="standalone-ontology-page">
      <div className="cim-page-body">
        <main className="cim-main-content">
          <div className="cim-breadcrumb">
            <span>本体模型中心</span><ChevronRight size={12} /><strong>自然资源本体模型</strong>
            <span className="cim-breadcrumb-spacer" />
            <LanguageSwitcher compact />
          </div>
          <h1 className="cim-visually-hidden">自然资源本体模型</h1>
          <section className="cim-ontology-viewer" aria-label="自然资源本体模型浏览器">
            <OntologyTab
              apiBase="/api/public/ontology"
              allowExport={false}
              showTechnicalStatus={false}
              initialConceptId={initialConceptId}
              className="standalone-ontology-workbench"
            />
          </section>
        </main>
      </div>
    </div>
  );
}

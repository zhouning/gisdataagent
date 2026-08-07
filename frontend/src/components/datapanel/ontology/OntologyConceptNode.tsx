import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Box, Database, FileText, Layers3, ListTree, Network, Shield, Tags, Workflow } from 'lucide-react';

type NodeData = {
  label?: string;
  code?: string;
  kind?: string;
  sourceSystem?: string;
  propertyCount?: number;
  geometryType?: string;
  classCount?: number;
  isFocus?: boolean;
};

const KIND_ICON: Record<string, typeof Box> = {
  Domain: Layers3,
  DomainClass: Network,
  ProcessClass: Workflow,
  StateClass: ListTree,
  RoleClass: Box,
  InformationClass: FileText,
  ObservationClass: Shield,
  ReferenceScheme: Tags,
  ReferenceConcept: ListTree,
  SchemaArtifact: Database,
  StandardDocument: FileText,
  Package: Box,
  FeatureType: Network,
  DatasetSchema: Database,
  ObjectType: Box,
  ActionType: Workflow,
  QualityRule: Shield,
  ValueDomain: Tags,
  ValueDomainMember: ListTree,
};

export default function OntologyConceptNode({ data, selected }: NodeProps) {
  const value = data as NodeData;
  const Icon = KIND_ICON[value.kind || ''] || Box;
  return (
    <div className={`ontology-node ontology-node-${value.kind || 'concept'}${value.isFocus ? ' focus' : ''}${selected ? ' selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="ontology-node-head">
        <Icon size={13} />
        <span>{value.kind || 'Concept'}</span>
        {value.isFocus && <span className="ontology-node-focus">中心对象</span>}
        {value.geometryType && <span className="ontology-node-geo">GEO</span>}
      </div>
      <strong title={value.label}>{value.label || '未命名概念'}</strong>
      <div className="ontology-node-code" title={value.code}>{value.code || 'no-code'}</div>
      <div className="ontology-node-foot">
        <span>{value.sourceSystem === 'standard' ? '标准' : value.sourceSystem === 'enterprise_architect' ? 'EA' : value.sourceSystem === 'curated_domain' ? '领域模型' : 'Runtime'}</span>
        <span>{value.kind === 'Domain' && value.classCount != null ? `${value.classCount} 类` : value.kind === 'ReferenceConcept' || value.kind === 'ValueDomainMember' ? '代码项' : value.kind?.endsWith('Class') ? '语义类' : `${value.propertyCount || 0} 字段`}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

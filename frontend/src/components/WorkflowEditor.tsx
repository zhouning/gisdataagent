import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  type Node,
  type Edge,
  type Connection,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { getLocaleHeaders } from '../i18n';

/* ------------------------------------------------------------------
   Types
   ------------------------------------------------------------------ */

interface WorkflowStep {
  step_id: string;
  label: string;
  pipeline_type: string;
  prompt: string;
  depends_on: string[];
  skill_id?: number;
  skill_name?: string;
}

interface WorkflowDef {
  id?: number;
  workflow_name: string;
  description: string;
  steps: WorkflowStep[];
  parameters: Record<string, { type: string; default: string; desc: string }>;
  graph_data: { nodes: Node[]; edges: Edge[] };
  cron_schedule: string;
  webhook_url: string;
  pipeline_type: string;
}

interface WorkflowEditorProps {
  workflow?: WorkflowDef | null;
  onSave: (wf: WorkflowDef) => void;
  onCancel: () => void;
}

/* ------------------------------------------------------------------
   Default empty workflow
   ------------------------------------------------------------------ */

const emptyWorkflow: WorkflowDef = {
  workflow_name: '',
  description: '',
  steps: [],
  parameters: {},
  graph_data: { nodes: [], edges: [] },
  cron_schedule: '',
  webhook_url: '',
  pipeline_type: 'general',
};

/* ------------------------------------------------------------------
   Node ID generator
   ------------------------------------------------------------------ */
let _nodeCounter = 0;
function nextNodeId(prefix: string) {
  _nodeCounter += 1;
  return `${prefix}_${_nodeCounter}`;
}

/* ------------------------------------------------------------------
   Custom Nodes
   ------------------------------------------------------------------ */

function DataInputNode({ data }: NodeProps) {
  const { t } = useTranslation('common');
  return (
    <div className="workflow-node workflow-node-input">
      <div className="workflow-node-title">{t('workflowEditor.dataInput')}</div>
      <div className="workflow-node-body">
        <div className="workflow-node-field">{(data as any).paramName || t('workflowEditor.notSet')}</div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

function PipelineNode({ data }: NodeProps) {
  const { t } = useTranslation('common');
  const pipelineLabels: Record<string, string> = {
    general: t('workflowEditor.pipelineTypes.general'),
    governance: t('workflowEditor.pipelineTypes.governance'),
    optimization: t('workflowEditor.pipelineTypes.optimization'),
    planner: t('workflowEditor.pipelineTypes.planner'),
  };
  return (
    <div className="workflow-node workflow-node-pipeline">
      <Handle type="target" position={Position.Top} />
      <div className="workflow-node-title">
        {pipelineLabels[(data as any).pipeline_type] || t('workflowEditor.pipeline')}
      </div>
      <div className="workflow-node-body">
        <div className="workflow-node-label">{(data as any).label || t('workflowEditor.unnamed')}</div>
        <div className="workflow-node-prompt">{((data as any).prompt || '').slice(0, 60)}</div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

function OutputNode({ data }: NodeProps) {
  const { t } = useTranslation('common');
  return (
    <div className="workflow-node workflow-node-output">
      <Handle type="target" position={Position.Top} />
      <div className="workflow-node-title">{t('workflowEditor.output')}</div>
      <div className="workflow-node-body">
        <div className="workflow-node-field">
          {(data as any).webhook_url ? t('workflowEditor.webhook') : t('workflowEditor.resultOutput')}
        </div>
      </div>
    </div>
  );
}

function SkillNode({ data }: NodeProps) {
  const { t } = useTranslation('common');
  return (
    <div className="workflow-node workflow-skill-node">
      <Handle type="target" position={Position.Top} />
      <div className="workflow-node-title">{t('workflowEditor.skillAgent')}</div>
      <div className="workflow-node-body">
        <div className="workflow-node-label">{(data as any).skill_name || t('workflowEditor.selectSkill')}</div>
        <div className="workflow-node-prompt">{((data as any).prompt || '').slice(0, 60)}</div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = {
  dataInput: DataInputNode,
  pipeline: PipelineNode,
  output: OutputNode,
  skill: SkillNode,
};

/* ------------------------------------------------------------------
   Nodes/edges ↔ steps conversion
   ------------------------------------------------------------------ */

function nodesToSteps(nodes: Node[], edges: Edge[]): WorkflowStep[] {
  const agentNodes = nodes.filter((n) => n.type === 'pipeline' || n.type === 'skill');
  return agentNodes.map((n) => {
    const incoming = edges
      .filter((e) => e.target === n.id)
      .map((e) => {
        const src = nodes.find((nn) => nn.id === e.source);
        return (src?.type === 'pipeline' || src?.type === 'skill') ? e.source : null;
      })
      .filter(Boolean) as string[];
    const d = n.data as any;
    const step: WorkflowStep = {
      step_id: n.id,
      label: d.label || d.skill_name || n.id,
      pipeline_type: n.type === 'skill' ? 'custom_skill' : (d.pipeline_type || 'general'),
      prompt: d.prompt || '',
      depends_on: incoming,
    };
    if (n.type === 'skill') {
      step.skill_id = d.skill_id;
      step.skill_name = d.skill_name;
    }
    return step;
  });
}

function stepsToNodesEdges(
  steps: WorkflowStep[],
  graphData?: { nodes: Node[]; edges: Edge[] },
): { nodes: Node[]; edges: Edge[] } {
  // Prefer stored graph_data if present
  if (graphData && graphData.nodes && graphData.nodes.length > 0) {
    return { nodes: graphData.nodes, edges: graphData.edges || [] };
  }
  // Auto-layout from steps
  const nodes: Node[] = steps.map((s, i) => ({
    id: s.step_id,
    type: s.pipeline_type === 'custom_skill' ? 'skill' : 'pipeline',
    position: { x: 200, y: 100 + i * 140 },
    data: s.pipeline_type === 'custom_skill'
      ? { label: s.label, skill_id: s.skill_id, skill_name: s.skill_name || s.label, prompt: s.prompt }
      : { label: s.label, pipeline_type: s.pipeline_type, prompt: s.prompt },
  }));
  const edges: Edge[] = [];
  steps.forEach((s) => {
    (s.depends_on || []).forEach((dep) => {
      edges.push({ id: `e_${dep}_${s.step_id}`, source: dep, target: s.step_id });
    });
  });
  return { nodes, edges };
}

/* ------------------------------------------------------------------
   Property Panel
   ------------------------------------------------------------------ */

function PropPanel({
  node,
  onChange,
  skills,
}: {
  node: Node | null;
  onChange: (id: string, data: Record<string, any>) => void;
  skills: { id: number; skill_name: string }[];
}) {
  const { t } = useTranslation('common');
  if (!node) {
    return (
      <div className="workflow-props-panel">
        <div className="workflow-props-empty">{t('workflowEditor.selectNodeHint')}</div>
      </div>
    );
  }

  const d = node.data as any;

  if (node.type === 'dataInput') {
    return (
      <div className="workflow-props-panel">
        <h4>{t('workflowEditor.dataInputNode')}</h4>
        <label>{t('workflowEditor.parameterName')}</label>
        <input
          value={d.paramName || ''}
          onChange={(e) => onChange(node.id, { ...d, paramName: e.target.value })}
        />
        <label>{t('workflowEditor.defaultPath')}</label>
        <input
          value={d.defaultPath || ''}
          onChange={(e) => onChange(node.id, { ...d, defaultPath: e.target.value })}
        />
      </div>
    );
  }

  if (node.type === 'pipeline') {
    return (
      <div className="workflow-props-panel">
        <h4>{t('workflowEditor.pipelineNode')}</h4>
        <label>{t('workflowEditor.stepName')}</label>
        <input
          value={d.label || ''}
          onChange={(e) => onChange(node.id, { ...d, label: e.target.value })}
        />
        <label>{t('workflowEditor.pipelineType')}</label>
        <select
          value={d.pipeline_type || 'general'}
          onChange={(e) => onChange(node.id, { ...d, pipeline_type: e.target.value })}
        >
          <option value="general">{t('workflowEditor.pipelineTypes.general')}</option>
          <option value="governance">{t('workflowEditor.pipelineTypes.governance')}</option>
          <option value="optimization">{t('workflowEditor.pipelineTypes.optimization')}</option>
          <option value="planner">{t('workflowEditor.pipelineTypes.planner')}</option>
        </select>
        <label>{t('workflowEditor.promptTemplate')}</label>
        <textarea
          rows={4}
          value={d.prompt || ''}
          onChange={(e) => onChange(node.id, { ...d, prompt: e.target.value })}
          placeholder={t('workflowEditor.parameterPromptPlaceholder')}
        />
      </div>
    );
  }

  if (node.type === 'skill') {
    return (
      <div className="workflow-props-panel">
        <h4>{t('workflowEditor.skillAgentNode')}</h4>
        <label>{t('workflowEditor.chooseSkill')}</label>
        <select
          value={d.skill_id || ''}
          onChange={(e) => {
            const sid = Number(e.target.value);
            const sk = skills.find(s => s.id === sid);
            onChange(node.id, { ...d, skill_id: sid, skill_name: sk?.skill_name || '', label: sk?.skill_name || '' });
          }}
        >
          <option value="">{t('workflowEditor.chooseCustomSkill')}</option>
          {skills.map(s => (
            <option key={s.id} value={s.id}>{s.skill_name}</option>
          ))}
        </select>
        <label>{t('workflowEditor.promptTemplate')}</label>
        <textarea
          rows={4}
          value={d.prompt || ''}
          onChange={(e) => onChange(node.id, { ...d, prompt: e.target.value })}
          placeholder={t('workflowEditor.skillPromptPlaceholder')}
        />
      </div>
    );
  }

  if (node.type === 'output') {
    return (
      <div className="workflow-props-panel">
        <h4>{t('workflowEditor.outputNode')}</h4>
        <label>{t('workflowEditor.webhookUrl')}</label>
        <input
          value={d.webhook_url || ''}
          onChange={(e) => onChange(node.id, { ...d, webhook_url: e.target.value })}
          placeholder={t('workflowEditor.urlPlaceholder')}
        />
      </div>
    );
  }

  return null;
}

/* ------------------------------------------------------------------
   Main Editor
   ------------------------------------------------------------------ */

export default function WorkflowEditor({ workflow, onSave, onCancel }: WorkflowEditorProps) {
  const { t } = useTranslation('common');
  const initial = workflow || emptyWorkflow;
  const { nodes: initNodes, edges: initEdges } = stepsToNodesEdges(
    initial.steps,
    initial.graph_data,
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initEdges);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [name, setName] = useState(initial.workflow_name);
  const [description, setDescription] = useState(initial.description);
  const [cronSchedule, setCronSchedule] = useState(initial.cron_schedule);
  const [webhookUrl, setWebhookUrl] = useState(initial.webhook_url);
  const [skills, setSkills] = useState<{ id: number; skill_name: string }[]>([]);
  const reactFlowRef = useRef<HTMLDivElement>(null);

  // Load available custom skills for the skill node dropdown
  useEffect(() => {
    fetch('/api/skills', { credentials: 'include', headers: getLocaleHeaders() })
      .then(r => r.ok ? r.json() : { skills: [] })
      .then(data => setSkills((data.skills || []).map((s: any) => ({ id: s.id, skill_name: s.skill_name }))))
      .catch(() => {});
  }, []);

  const onConnect = useCallback(
    (conn: Connection) => setEdges((eds) => addEdge(conn, eds)),
    [setEdges],
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onNodeDataChange = useCallback(
    (id: string, data: Record<string, any>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data } : n)),
      );
      setSelectedNode((prev) => (prev && prev.id === id ? { ...prev, data } : prev));
    },
    [setNodes],
  );

  const addNode = (type: 'dataInput' | 'pipeline' | 'output' | 'skill') => {
    const id = nextNodeId(type);
    const defaults: Record<string, Record<string, any>> = {
      dataInput: { paramName: '', defaultPath: '' },
      pipeline: { label: t('workflowEditor.newStep'), pipeline_type: 'general', prompt: '' },
      output: { webhook_url: '' },
      skill: { label: t('workflowEditor.selectSkill'), skill_id: null, skill_name: '', prompt: '' },
    };
    const newNode: Node = {
      id,
      type,
      position: { x: 200 + Math.random() * 100, y: 100 + nodes.length * 80 },
      data: defaults[type],
    };
    setNodes((nds) => [...nds, newNode]);
  };

  const handleSave = () => {
    const steps = nodesToSteps(nodes, edges);
    // Collect parameters from DataInput nodes
    const params: Record<string, { type: string; default: string; desc: string }> = {};
    nodes.filter((n) => n.type === 'dataInput').forEach((n) => {
      const d = n.data as any;
      if (d.paramName) {
        params[d.paramName] = { type: 'file', default: d.defaultPath || '', desc: '' };
      }
    });
    // Collect webhook from output nodes
    let wh = webhookUrl;
    const outputNodes = nodes.filter((n) => n.type === 'output');
    if (outputNodes.length > 0 && (outputNodes[0].data as any).webhook_url) {
      wh = (outputNodes[0].data as any).webhook_url;
    }

    const wf: WorkflowDef = {
      ...(workflow?.id ? { id: workflow.id } : {}),
      workflow_name: name,
      description,
      steps,
      parameters: params,
      graph_data: { nodes, edges },
      cron_schedule: cronSchedule,
      webhook_url: wh,
      pipeline_type: steps[0]?.pipeline_type || 'general',
    };
    onSave(wf);
  };

  return (
    <div className="workflow-editor">
      {/* Top bar: name + actions */}
      <div className="workflow-editor-topbar">
        <input
          className="workflow-name-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('workflowEditor.workflowName')}
        />
        <div className="workflow-editor-actions">
          <button className="btn-secondary" onClick={onCancel}>{t('workflowEditor.cancel')}</button>
          <button className="btn-primary" onClick={handleSave} disabled={!name.trim()}>
            {t('workflowEditor.save')}
          </button>
        </div>
      </div>

      {/* Toolbar: add nodes */}
      <div className="workflow-toolbar">
        <button onClick={() => addNode('dataInput')}>+ {t('workflowEditor.dataInput')}</button>
        <button onClick={() => addNode('pipeline')}>+ {t('workflowEditor.pipeline')}</button>
        <button onClick={() => addNode('skill')}>+ {t('workflowEditor.skillAgent')}</button>
        <button onClick={() => addNode('output')}>+ {t('workflowEditor.output')}</button>
        <div className="workflow-toolbar-right">
          <input
            className="workflow-cron-input"
            value={cronSchedule}
            onChange={(e) => setCronSchedule(e.target.value)}
            placeholder={t('workflowEditor.cronPlaceholder')}
            title={t('workflowEditor.cronTitle')}
          />
        </div>
      </div>

      {/* Canvas + props */}
      <div className="workflow-canvas-area">
        <div className="workflow-canvas" ref={reactFlowRef}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
        <PropPanel node={selectedNode} onChange={onNodeDataChange} skills={skills} />
      </div>

      {/* Description */}
      <div className="workflow-editor-footer">
        <textarea
          className="workflow-desc-input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('workflowEditor.descriptionPlaceholder')}
          rows={2}
        />
      </div>
    </div>
  );
}

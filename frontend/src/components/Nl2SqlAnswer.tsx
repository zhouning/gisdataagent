import { useMemo, useState } from 'react';
import {
  BarChart3,
  Bot,
  ChevronRight,
  Clock3,
  Database,
  ShieldCheck,
  Table2,
} from 'lucide-react';
import ChartView from './ChartView';

type Language = 'zh' | 'en' | 'ar';

interface PresentationColumn {
  key: string;
  label: string;
  role: string;
  numeric: boolean;
  aggregate?: string | null;
  format?: { decimals?: number };
}

interface Nl2SqlPresentation {
  schema: string;
  language: Language;
  title: string;
  summary?: string;
  row_count: number;
  displayed_row_count: number;
  truncated: boolean;
  columns: PresentationColumn[];
  rows: Array<Record<string, unknown>>;
  visualization: {
    kind: 'bar' | 'line' | 'kpi' | 'table';
    orientation?: 'horizontal' | 'vertical';
    category_key?: string;
    measure_keys?: string[];
    sort?: 'source' | 'measure_desc';
  };
  timing?: { total_ms?: number | null; database_ms?: number | null };
  model?: {
    invoked?: boolean;
    route?: string | null;
    contract_id?: string | null;
    model?: string | null;
    input_tokens?: number;
    output_tokens?: number;
    reasoning_tokens?: number;
    generation_ms?: number | null;
  };
  evidence?: {
    database_name?: string | null;
    schemas?: string[];
    read_only?: boolean;
    semantic_version?: string | null;
    sql?: string | null;
    fingerprint?: string | null;
    execution_attempt_count?: number | null;
  };
}

const COPY = {
  zh: {
    chart: '图表', table: '表格', rows: '行', shown: '当前展示',
    evidence: '查询依据', total: '总耗时', database: '数据库执行',
    planner: '规划方式', model: '模型调用', notInvoked: '未调用',
    tokens: 'Token', source: '数据源', semantic: '语义版本', sql: '执行 SQL',
    fingerprint: '结果等价指纹', readOnly: '只读', attempts: '执行次数',
  },
  en: {
    chart: 'Chart', table: 'Table', rows: 'rows', shown: 'Showing',
    evidence: 'Query evidence', total: 'Total time', database: 'Database execution',
    planner: 'Planning route', model: 'Model call', notInvoked: 'Not invoked',
    tokens: 'Tokens', source: 'Source', semantic: 'Semantic version', sql: 'Executed SQL',
    fingerprint: 'Result equivalence fingerprint', readOnly: 'read-only', attempts: 'Execution attempts',
  },
  ar: {
    chart: 'الرسم', table: 'الجدول', rows: 'صفوف', shown: 'المعروض',
    evidence: 'أدلة الاستعلام', total: 'الوقت الإجمالي', database: 'تنفيذ قاعدة البيانات',
    planner: 'مسار التخطيط', model: 'استدعاء النموذج', notInvoked: 'لم يتم الاستدعاء',
    tokens: 'الرموز', source: 'المصدر', semantic: 'الإصدار الدلالي', sql: 'SQL المنفذ',
    fingerprint: 'بصمة تكافؤ النتيجة', readOnly: 'للقراءة فقط', attempts: 'محاولات التنفيذ',
  },
};

const ROUTE_LABELS: Record<string, Record<Language, string>> = {
  deterministic_reviewed_metric_contract: {
    zh: '审核指标合同', en: 'Reviewed metric contract', ar: 'عقد مؤشر معتمد',
  },
  governed_free_form_llm: {
    zh: '治理型自由问数', en: 'Governed free-form planning', ar: 'تخطيط حر محكوم',
  },
  semantic_ir_experimental_llm: {
    zh: 'Semantic IR 编译路线', en: 'Semantic IR compiler route', ar: 'مسار مترجم Semantic IR',
  },
};

function formatDuration(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function numberLocale(language: Language) {
  return language === 'zh' ? 'zh-CN' : language === 'ar' ? 'ar-AE' : 'en-US';
}

function formatValue(value: unknown, column: PresentationColumn, language: Language) {
  if (value === null || value === undefined || value === '') return '-';
  if (column.numeric && typeof value === 'number') {
    const decimals = Number(column.format?.decimals ?? 2);
    return new Intl.NumberFormat(numberLocale(language), {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);
  }
  return String(value);
}

function buildChartOption(presentation: Nl2SqlPresentation) {
  const { visualization, columns, language } = presentation;
  const categoryKey = visualization.category_key || '';
  const measureKeys = visualization.measure_keys || [];
  const columnMap = new Map(columns.map(column => [column.key, column]));
  const primaryMeasure = measureKeys[0];
  const rows = [...presentation.rows];
  if (visualization.sort === 'measure_desc' && primaryMeasure) {
    rows.sort((left, right) => Number(right[primaryMeasure] ?? 0) - Number(left[primaryMeasure] ?? 0));
  }
  const categories = rows.map(row => String(row[categoryKey] ?? '-'));
  const formatSeriesValue = (key: string, value: unknown) => {
    const column = columnMap.get(key);
    return column ? formatValue(value, column, language) : String(value ?? '-');
  };
  const series = measureKeys.map((key, index) => {
    const column = columnMap.get(key);
    return {
      name: column?.label || key,
      type: visualization.kind,
      data: rows.map(row => row[key]),
      barMaxWidth: 28,
      smooth: visualization.kind === 'line',
      symbolSize: 7,
      itemStyle: { color: index === 0 ? '#2aa78f' : index === 1 ? '#4d8dca' : '#d39a3b' },
      lineStyle: { width: 2.5 },
      label: visualization.kind === 'bar' ? {
        show: rows.length <= 12,
        position: visualization.orientation === 'horizontal' ? 'right' : 'top',
        color: '#cbd5e1',
        fontSize: 10,
        formatter: ({ value }: { value: unknown }) => formatSeriesValue(key, value),
      } : undefined,
    };
  });
  const valueAxis = {
    type: 'value',
    axisLabel: { color: '#94a3b8', fontSize: 10 },
    splitLine: { lineStyle: { color: '#475569' } },
  };
  const categoryAxis = {
    type: 'category',
    data: categories,
    inverse: visualization.orientation === 'horizontal',
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#64748b' } },
    axisLabel: {
      color: '#aeb9c7',
      fontSize: 10,
      width: visualization.orientation === 'horizontal' ? 112 : 76,
      overflow: 'truncate',
    },
  };
  return {
    animationDuration: 350,
    grid: visualization.orientation === 'horizontal'
      ? { left: 8, right: 54, top: measureKeys.length > 1 ? 30 : 12, bottom: 12, containLabel: true }
      : { left: 8, right: 18, top: measureKeys.length > 1 ? 34 : 26, bottom: 24, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      valueFormatter: (value: unknown) => formatSeriesValue(primaryMeasure, value),
    },
    legend: measureKeys.length > 1 ? { top: 0, textStyle: { color: '#aeb9c7', fontSize: 10 } } : undefined,
    xAxis: visualization.orientation === 'horizontal' ? valueAxis : categoryAxis,
    yAxis: visualization.orientation === 'horizontal' ? categoryAxis : valueAxis,
    series,
  };
}

function ResultTable({ presentation }: { presentation: Nl2SqlPresentation }) {
  const rows = [...presentation.rows];
  const primaryMeasure = presentation.visualization.measure_keys?.[0];
  if (presentation.visualization.sort === 'measure_desc' && primaryMeasure) {
    rows.sort((left, right) => Number(right[primaryMeasure] ?? 0) - Number(left[primaryMeasure] ?? 0));
  }
  return (
    <div className="nl2sql-table-wrap">
      <table className="nl2sql-result-table">
        <thead>
          <tr>
            {presentation.columns.map(column => (
              <th key={column.key} className={column.numeric ? 'numeric' : ''}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {presentation.columns.map(column => (
                <td key={column.key} className={column.numeric ? 'numeric' : ''}>
                  {formatValue(row[column.key], column, presentation.language)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KpiResult({ presentation }: { presentation: Nl2SqlPresentation }) {
  const keys = presentation.visualization.measure_keys || [];
  const row = presentation.rows[0] || {};
  return (
    <div className="nl2sql-kpi-grid">
      {keys.map(key => {
        const column = presentation.columns.find(item => item.key === key);
        if (!column) return null;
        return <div className="nl2sql-kpi" key={key}><span>{column.label}</span><strong>{formatValue(row[key], column, presentation.language)}</strong></div>;
      })}
    </div>
  );
}

export default function Nl2SqlAnswer({ presentation }: { presentation: Nl2SqlPresentation }) {
  const visualKind = presentation.visualization.kind;
  const hasChart = visualKind === 'bar' || visualKind === 'line';
  const [view, setView] = useState<'chart' | 'table'>(hasChart ? 'chart' : 'table');
  const labels = COPY[presentation.language] || COPY.en;
  const chartOption = useMemo(
    () => hasChart ? buildChartOption(presentation) : null,
    [hasChart, presentation],
  );
  const route = presentation.model?.route || '';
  const routeLabel = ROUTE_LABELS[route]?.[presentation.language] || route || '-';
  const totalMs = presentation.timing?.total_ms;
  const chartHeight = `${Math.max(220, Math.min(390, presentation.rows.length * 34 + 62))}px`;

  return (
    <section className="nl2sql-answer" dir={presentation.language === 'ar' ? 'rtl' : 'ltr'}>
      <header className="nl2sql-answer-header">
        <div>
          <h3>{presentation.title}</h3>
          <div className="nl2sql-answer-meta">
            <span><Clock3 size={13} />{labels.total} {formatDuration(totalMs)}</span>
            <span>{presentation.row_count.toLocaleString(numberLocale(presentation.language))} {labels.rows}</span>
          </div>
        </div>
        {hasChart && (
          <div className="nl2sql-view-switch" role="group" aria-label={`${labels.chart} / ${labels.table}`}>
            <button type="button" className={view === 'chart' ? 'active' : ''} onClick={() => setView('chart')}><BarChart3 size={14} />{labels.chart}</button>
            <button type="button" className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}><Table2 size={14} />{labels.table}</button>
          </div>
        )}
      </header>

      {presentation.summary && <p className="nl2sql-answer-summary">{presentation.summary}</p>}

      {visualKind === 'kpi' ? <KpiResult presentation={presentation} /> : null}
      {hasChart && view === 'chart' && chartOption ? (
        <div className="nl2sql-inline-chart"><ChartView option={chartOption} height={chartHeight} compact /></div>
      ) : null}
      {(!hasChart || view === 'table') && visualKind !== 'kpi' ? <ResultTable presentation={presentation} /> : null}
      {presentation.truncated && (
        <p className="nl2sql-truncation">{labels.shown} {presentation.displayed_row_count.toLocaleString(numberLocale(presentation.language))} / {presentation.row_count.toLocaleString(numberLocale(presentation.language))} {labels.rows}</p>
      )}

      <details className="nl2sql-evidence">
        <summary><ShieldCheck size={14} /><span>{labels.evidence}</span><ChevronRight className="nl2sql-evidence-chevron" size={14} /></summary>
        <dl>
          <div><dt>{labels.total}</dt><dd>{formatDuration(totalMs)}</dd></div>
          <div><dt>{labels.database}</dt><dd>{formatDuration(presentation.timing?.database_ms)}</dd></div>
          <div><dt>{labels.planner}</dt><dd>{routeLabel}{presentation.model?.contract_id ? ` · ${presentation.model.contract_id}` : ''}</dd></div>
          <div><dt><Bot size={12} />{labels.model}</dt><dd>{presentation.model?.invoked ? `${presentation.model.model || '-'} · ${formatDuration(presentation.model.generation_ms)}` : labels.notInvoked}</dd></div>
          {presentation.model?.invoked && <div><dt>{labels.tokens}</dt><dd>{presentation.model.input_tokens || 0} in / {presentation.model.output_tokens || 0} out{presentation.model.reasoning_tokens ? ` / ${presentation.model.reasoning_tokens} reasoning` : ''}</dd></div>}
          <div><dt><Database size={12} />{labels.source}</dt><dd><code>{presentation.evidence?.database_name || '-'}/{(presentation.evidence?.schemas || []).join(', ') || '-'}</code>{presentation.evidence?.read_only ? ` · ${labels.readOnly}` : ''}</dd></div>
          <div><dt>{labels.semantic}</dt><dd><code>{presentation.evidence?.semantic_version || '-'}</code></dd></div>
          {presentation.evidence?.execution_attempt_count ? <div><dt>{labels.attempts}</dt><dd>{presentation.evidence.execution_attempt_count}</dd></div> : null}
        </dl>
        {presentation.evidence?.sql && <div className="nl2sql-evidence-block"><strong>{labels.sql}</strong><pre><code>{presentation.evidence.sql}</code></pre></div>}
        {presentation.evidence?.fingerprint && <div className="nl2sql-fingerprint"><strong>{labels.fingerprint}</strong><code>{presentation.evidence.fingerprint}</code></div>}
      </details>
    </section>
  );
}

export type { Nl2SqlPresentation };

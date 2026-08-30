import { Database, ArrowRight } from 'lucide-react';

type Language = 'zh' | 'en' | 'ar';

interface ClarificationOption {
  physical_table: string;
  semantic_asset_id?: string | null;
  matched_terms?: string[];
}

export interface Nl2SqlClarificationPayload {
  required?: boolean;
  reason?: string;
  message?: string;
  question?: string;
  scope?: 'liveability' | 'makani' | string;
  options?: ClarificationOption[];
  answer_not_executed?: boolean;
}

const COPY: Record<Language, { title: string; hint: string; continue: string }> = {
  zh: { title: '需要选择数据表', hint: '系统检测到多个同名语义对象，未执行查询。请选择准确的数据表后继续。', continue: '使用此表继续' },
  en: { title: 'Choose a data table', hint: 'Multiple equally matched semantic objects were found. No query was executed. Choose a table to continue.', continue: 'Continue with this table' },
  ar: { title: 'اختر جدول البيانات', hint: 'تم العثور على عدة كائنات دلالية متساوية. لم يتم تنفيذ الاستعلام. اختر جدولاً للمتابعة.', continue: 'المتابعة بهذا الجدول' },
};

export function detectClarificationLanguage(value: unknown): Language {
  const text = String(value || '');
  if (/[؀-ۿ]/.test(text)) return 'ar';
  if (/[一-鿿]/.test(text)) return 'zh';
  return 'en';
}

function scopePrefix(scope: string | undefined, language: Language) {
  if (scope === 'liveability') return '@Liveability';
  if (scope === 'makani') return '@Makani';
  return language === 'zh' ? '' : '';
}

export function buildClarificationFollowup(
  clarification: Nl2SqlClarificationPayload,
  option: ClarificationOption,
): string {
  const language = detectClarificationLanguage(clarification.question || clarification.message);
  const table = String(option.physical_table || '').trim();
  const question = String(clarification.question || '').trim();
  if (!table || !question) return '';
  const prefix = scopePrefix(clarification.scope, language);
  const qualifier = language === 'zh'
    ? `请使用数据表 ${table} 查询：${question}`
    : language === 'ar'
      ? `استخدم جدول البيانات ${table} للإجابة عن: ${question}`
      : `Use data table ${table} to answer: ${question}`;
  return prefix ? `${prefix} ${qualifier}` : qualifier;
}

export function isActionableClarification(
  clarification: Nl2SqlClarificationPayload | undefined,
): boolean {
  return Boolean(
    clarification?.required
      && clarification.answer_not_executed === true
      && (clarification.options || []).some(option => String(option.physical_table || '').trim()),
  );
}

export default function Nl2SqlClarification({
  clarification,
  onSelect,
}: {
  clarification: Nl2SqlClarificationPayload;
  onSelect: (text: string) => void;
}) {
  const language = detectClarificationLanguage(clarification.question || clarification.message);
  const labels = COPY[language];
  const options = (clarification.options || []).filter(option => String(option.physical_table || '').trim());
  // A clarification card is only valid for a fail-closed, non-executing
  // response.  Do not let an incomplete or stale metadata payload look like
  // an actionable success state.
  if (!isActionableClarification(clarification)) return null;

  const handleSelect = (option: ClarificationOption) => {
    onSelect(buildClarificationFollowup(clarification, option));
  };

  return (
    <section className="nl2sql-clarification" dir={language === 'ar' ? 'rtl' : 'ltr'} role="status">
      <div className="nl2sql-clarification-heading">
        <Database size={15} />
        <strong>{labels.title}</strong>
      </div>
      <p>{clarification.message || labels.hint}</p>
      <div className="nl2sql-clarification-options">
        {options.map(option => (
          <button
            key={`${option.physical_table}:${option.semantic_asset_id || ''}`}
            type="button"
            className="nl2sql-clarification-option"
            onClick={() => handleSelect(option)}
          >
            <span className="nl2sql-clarification-option-main">
              <code>{option.physical_table}</code>
              {option.semantic_asset_id && <small>{option.semantic_asset_id}</small>}
            </span>
            <span className="nl2sql-clarification-option-action">{labels.continue}<ArrowRight size={13} /></span>
          </button>
        ))}
      </div>
    </section>
  );
}

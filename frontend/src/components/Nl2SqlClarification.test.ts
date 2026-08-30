import { describe, expect, it } from 'vitest';
import { buildClarificationFollowup, detectClarificationLanguage, isActionableClarification } from './Nl2SqlClarification';

describe('NL2SQL clarification follow-up', () => {
  it('preserves the original question and adds an exact table qualifier', () => {
    const value = buildClarificationFollowup(
      { required: true, scope: 'makani', question: 'Count centers' },
      { physical_table: 'public.poi_civildefense_centers' },
    );
    expect(value).toContain('Count centers');
    expect(value).toContain('public.poi_civildefense_centers');
    expect(value).toContain('@Makani');
  });

  it('localizes language detection without changing the table identity', () => {
    expect(detectClarificationLanguage('请统计中心数量')).toBe('zh');
    expect(detectClarificationLanguage('احسب عدد المراكز')).toBe('ar');
    expect(detectClarificationLanguage('Count centers')).toBe('en');
    expect(buildClarificationFollowup(
      { required: true, scope: 'liveability', question: '统计中心数量' },
      { physical_table: 'public.centers' },
    )).toContain('public.centers');
  });

  it('does not treat an incomplete rejection payload as actionable', () => {
    expect(isActionableClarification({ required: true, options: [{ physical_table: 'public.poi_a' }] })).toBe(false);
    expect(isActionableClarification({ required: true, answer_not_executed: true, options: [{ physical_table: 'public.poi_a' }] })).toBe(true);
  });
});

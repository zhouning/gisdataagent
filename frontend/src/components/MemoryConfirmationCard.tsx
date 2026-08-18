import { useState } from 'react';
import { Brain, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface Fact {
  key: string;
  value: string;
  category: string;
}

interface MemoryConfirmationCardProps {
  facts: Fact[];
  onSave: (facts: Fact[]) => void;
  onDiscard: () => void;
}

export default function MemoryConfirmationCard({ facts: initialFacts, onSave, onDiscard }: MemoryConfirmationCardProps) {
  const { t } = useTranslation('common');
  const [facts, setFacts] = useState<Fact[]>(initialFacts);
  const [selected, setSelected] = useState<Set<number>>(new Set(initialFacts.map((_, i) => i)));

  const toggleSelect = (idx: number) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const updateFact = (idx: number, field: keyof Fact, value: string) => {
    setFacts(prev => prev.map((f, i) => i === idx ? { ...f, [field]: value } : f));
  };

  const removeFact = (idx: number) => {
    setFacts(prev => prev.filter((_, i) => i !== idx));
    setSelected(prev => { const next = new Set(prev); next.delete(idx); return next; });
  };

  const addFact = () => {
    setFacts(prev => [...prev, { key: '', value: '', category: 'user_preference' }]);
  };

  const handleSave = () => {
    const toSave = facts.filter((_, i) => selected.has(i) && facts[i].key && facts[i].value);
    onSave(toSave);
  };

  return (
    <div style={{ background: 'var(--surface)', padding: '16px', borderRadius: 'var(--radius-md)', marginBottom: '12px' }}>
      <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
        <Brain size={16} /> {t('memoryConfirmation.title')}
      </h4>
      <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
        {t('memoryConfirmation.description')}
      </p>

      <div style={{ maxHeight: '300px', overflow: 'auto', marginBottom: '12px' }}>
        {facts.map((fact, idx) => (
          <div key={idx} style={{ background: 'var(--surface-elevated)', padding: '10px', borderRadius: 'var(--radius-sm)', marginBottom: '8px', display: 'flex', gap: '8px', alignItems: 'start' }}>
            <input
              type="checkbox"
              checked={selected.has(idx)}
              onChange={() => toggleSelect(idx)}
              aria-label={t('memoryConfirmation.toggleFact', { index: idx + 1 })}
              style={{ marginTop: '4px' }}
            />
            <div style={{ flex: 1 }}>
              <input
                value={fact.key}
                onChange={e => updateFact(idx, 'key', e.target.value)}
                placeholder={t('memoryConfirmation.keywordPlaceholder')}
                style={{ width: '100%', padding: '4px 6px', fontSize: '12px', marginBottom: '4px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
              />
              <textarea
                value={fact.value}
                onChange={e => updateFact(idx, 'value', e.target.value)}
                placeholder={t('memoryConfirmation.contentPlaceholder')}
                rows={2}
                style={{ width: '100%', padding: '4px 6px', fontSize: '12px', marginBottom: '4px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', resize: 'vertical' }}
              />
              <select
                value={fact.category}
                onChange={e => updateFact(idx, 'category', e.target.value)}
                style={{ width: '100%', padding: '4px 6px', fontSize: '11px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
              >
                <option value="data_characteristic">{t('memoryConfirmation.categories.dataCharacteristic')}</option>
                <option value="analysis_conclusion">{t('memoryConfirmation.categories.analysisConclusion')}</option>
                <option value="user_preference">{t('memoryConfirmation.categories.userPreference')}</option>
              </select>
            </div>
            <button onClick={() => removeFact(idx)} style={{ padding: '4px 8px', fontSize: '11px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--text-secondary)' }}>
              <Trash2 size={13} /> {t('memoryConfirmation.remove')}
            </button>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '8px', justifyContent: 'space-between', alignItems: 'center' }}>
        <button onClick={addFact} style={{ padding: '6px 12px', fontSize: '12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
          <Plus size={13} /> {t('memoryConfirmation.add')}
        </button>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={onDiscard} style={{ padding: '6px 12px', fontSize: '12px', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
            {t('memoryConfirmation.discardAll')}
          </button>
          <button onClick={handleSave} style={{ padding: '6px 12px', fontSize: '12px', background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
            {t('memoryConfirmation.saveSelected', { count: selected.size })}
          </button>
        </div>
      </div>
    </div>
  );
}

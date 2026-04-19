import { useState, useEffect } from 'react';

interface ModuleItem {
  module_id: string;
  module_name: string;
  class_count: number;
}

interface ClassItem {
  class_id: string;
  class_name: string;
  package_path: string[];
}

interface Props {
  onModuleSelect: (moduleId: string) => void;
  onClassSelect: (classId: string) => void;
  selectedModuleId: string | null;
}

export default function ModuleList({ onModuleSelect, onClassSelect, selectedModuleId }: Props) {
  const [modules, setModules] = useState<ModuleItem[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [loadingModules, setLoadingModules] = useState(false);
  const [loadingClasses, setLoadingClasses] = useState(false);
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);

  useEffect(() => {
    setLoadingModules(true);
    fetch('/api/xmi/modules', { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setModules(data.modules || data || []))
      .catch(() => setModules([]))
      .finally(() => setLoadingModules(false));
  }, []);

  const handleModuleClick = (mod: ModuleItem) => {
    onModuleSelect(mod.module_id);
    setSelectedClassId(null);
    setLoadingClasses(true);
    fetch(`/api/xmi/classes?module_id=${encodeURIComponent(mod.module_id)}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setClasses(data.classes || data || []))
      .catch(() => setClasses([]))
      .finally(() => setLoadingClasses(false));
  };

  const handleClassClick = (cls: ClassItem) => {
    setSelectedClassId(cls.class_id);
    onClassSelect(cls.class_id);
  };

  if (loadingModules) {
    return <div style={{ padding: 12, color: '#6b7280', fontSize: 12 }}>加载模块...</div>;
  }

  if (modules.length === 0) {
    return (
      <div style={{ padding: 12, color: '#9ca3af', fontSize: 12, textAlign: 'center' }}>
        暂无已编译的领域标准模块
      </div>
    );
  }

  return (
    <div style={{ overflowY: 'auto', height: '100%' }}>
      {modules.map(mod => {
        const isSelected = selectedModuleId === mod.module_id;
        return (
          <div key={mod.module_id}>
            {/* Module row */}
            <div
              onClick={() => handleModuleClick(mod)}
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                background: isSelected ? '#eff6ff' : 'transparent',
                borderLeft: isSelected ? '3px solid #3b82f6' : '3px solid transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                borderBottom: '1px solid #f3f4f6',
                transition: 'background 0.15s',
              }}
            >
              <span style={{
                fontSize: 13, fontWeight: isSelected ? 600 : 400,
                color: isSelected ? '#1e40af' : '#374151',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {mod.module_name}
              </span>
              <span style={{
                background: '#dbeafe', color: '#1d4ed8',
                borderRadius: 10, padding: '1px 7px', fontSize: 11, fontWeight: 600,
                flexShrink: 0, marginLeft: 6,
              }}>
                {mod.class_count}
              </span>
            </div>

            {/* Class sub-list */}
            {isSelected && (
              <div style={{ background: '#f8fafc' }}>
                {loadingClasses ? (
                  <div style={{ padding: '6px 20px', color: '#9ca3af', fontSize: 11 }}>加载类...</div>
                ) : classes.length === 0 ? (
                  <div style={{ padding: '6px 20px', color: '#9ca3af', fontSize: 11 }}>无类定义</div>
                ) : (
                  classes.map(cls => (
                    <div
                      key={cls.class_id}
                      onClick={() => handleClassClick(cls)}
                      style={{
                        padding: '5px 12px 5px 24px',
                        cursor: 'pointer',
                        background: selectedClassId === cls.class_id ? '#dbeafe' : 'transparent',
                        borderBottom: '1px solid #f3f4f6',
                      }}
                    >
                      <div style={{
                        fontSize: 12, color: selectedClassId === cls.class_id ? '#1e40af' : '#374151',
                        fontWeight: selectedClassId === cls.class_id ? 600 : 400,
                      }}>
                        {cls.class_name}
                      </div>
                      {cls.package_path.length > 0 && (
                        <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 1 }}>
                          {cls.package_path.join(' › ')}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

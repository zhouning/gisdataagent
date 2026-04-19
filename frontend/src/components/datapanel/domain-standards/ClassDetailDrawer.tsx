interface AttributeRow {
  attribute_name: string;
  attribute_type: string;
  attribute_id: string;
}

interface GeneralizationRow {
  target_class_id: string;
  target_class_name: string;
}

interface AssociationEnd {
  type_name: string;
  type_ref: string;
}

interface AssociationRow {
  association_name: string;
  ends: AssociationEnd[];
}

export interface ClassDetail {
  class_id: string;
  class_name: string;
  class_id_raw: string;
  package_path: string[];
  attributes: AttributeRow[];
  generalizations: GeneralizationRow[];
  associations: AssociationRow[];
  super_class_id?: string;
  super_class_id_raw?: string;
}

interface Props {
  classDetail: ClassDetail | null;
  onClose: () => void;
  onClassNavigate?: (classId: string) => void;
}

export default function ClassDetailDrawer({ classDetail, onClose, onClassNavigate }: Props) {
  const open = classDetail !== null;

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      right: 0,
      bottom: 0,
      width: 320,
      background: '#fff',
      borderLeft: '1px solid #e5e7eb',
      boxShadow: '-4px 0 16px rgba(0,0,0,0.08)',
      transform: open ? 'translateX(0)' : 'translateX(100%)',
      transition: 'transform 0.22s ease',
      zIndex: 10,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {classDetail && (
        <>
          {/* Header */}
          <div style={{
            padding: '12px 14px',
            borderBottom: '1px solid #e5e7eb',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#f8fafc',
          }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: '#1e40af' }}>{classDetail.class_name}</div>
              {classDetail.package_path.length > 0 && (
                <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
                  {classDetail.package_path.join(' › ')}
                </div>
              )}
            </div>
            <button
              onClick={onClose}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: '#6b7280', fontSize: 18, lineHeight: 1, padding: '2px 6px',
              }}
              title="关闭"
            >×</button>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
            {/* Attributes */}
            <Section title="属性">
              {classDetail.attributes.length === 0 ? (
                <div style={{ color: '#9ca3af', fontSize: 12 }}>无属性</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: '#f3f4f6' }}>
                      <th style={thStyle}>名称</th>
                      <th style={thStyle}>类型</th>
                    </tr>
                  </thead>
                  <tbody>
                    {classDetail.attributes.map((a, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
                        <td style={tdStyle}>{a.attribute_name}</td>
                        <td style={{ ...tdStyle, color: '#1d4ed8' }}>{a.attribute_type}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>

            {/* Generalizations */}
            <Section title="继承">
              {classDetail.generalizations.length === 0 ? (
                <div style={{ color: '#9ca3af', fontSize: 12 }}>无继承关系</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {classDetail.generalizations.map((g, i) => (
                    <button
                      key={i}
                      onClick={() => onClassNavigate && onClassNavigate(g.target_class_id)}
                      style={{
                        background: '#eff6ff', border: '1px solid #bfdbfe',
                        borderRadius: 4, padding: '4px 8px', cursor: 'pointer',
                        color: '#1d4ed8', fontSize: 12, textAlign: 'left',
                      }}
                    >
                      ↑ {g.target_class_name}
                    </button>
                  ))}
                </div>
              )}
            </Section>

            {/* Associations */}
            <Section title="关联">
              {classDetail.associations.length === 0 ? (
                <div style={{ color: '#9ca3af', fontSize: 12 }}>无关联关系</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {classDetail.associations.map((a, i) => (
                    <div key={i} style={{
                      background: '#fffbeb', border: '1px solid #fde68a',
                      borderRadius: 4, padding: '5px 8px', fontSize: 12,
                    }}>
                      <div style={{ fontWeight: 600, color: '#92400e', marginBottom: 2 }}>{a.association_name || '(未命名)'}</div>
                      {a.ends.map((e, j) => (
                        <div key={j} style={{ color: '#78350f' }}>→ {e.type_name}</div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: '#6b7280',
        textTransform: 'uppercase', letterSpacing: '0.05em',
        marginBottom: 6, paddingBottom: 4,
        borderBottom: '1px solid #f3f4f6',
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: '4px 6px', textAlign: 'left', fontWeight: 600,
  color: '#374151', fontSize: 11,
};

const tdStyle: React.CSSProperties = {
  padding: '3px 6px', color: '#374151',
};

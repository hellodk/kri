import { useState } from 'react'

interface Props {
  state: string
  minionIds: string[]
  onClose: () => void
  // The second arg carries dry-run intent: true = `state.apply test=True`,
  // which evaluates the state tree but makes no changes (#prod-salt-test).
  onConfirm: (pillar: Record<string, string>, test: boolean) => void
}

export function SaltPillarDialog({ state, minionIds, onClose, onConfirm }: Props) {
  const [pairs, setPairs] = useState<Array<{ _key: string; key: string; value: string }>>([])
  const [testMode, setTestMode] = useState(false)

  const add = () => setPairs((p) => [...p, { _key: crypto.randomUUID(), key: '', value: '' }])
  const remove = (i: number) => setPairs((p) => p.filter((_, idx) => idx !== i))
  const update = (i: number, field: 'key' | 'value', val: string) =>
    setPairs((p) => p.map((row, idx) => (idx === i ? { ...row, [field]: val } : row)))

  const handleConfirm = () => {
    const pillar: Record<string, string> = {}
    for (const { key, value } of pairs) {
      if (key.trim()) pillar[key.trim()] = value
    }
    onConfirm(pillar, testMode)
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          padding: 24,
          maxWidth: 520,
          width: '90%',
          maxHeight: '80vh',
          overflowY: 'auto',
          boxShadow: '0 4px 24px rgba(0,0,0,0.18)',
        }}
      >
        <h2 style={{ fontSize: 16, fontWeight: 700, color: '#111827', marginBottom: 4 }}>
          Run Salt State
        </h2>
        <p style={{ fontSize: 13, color: '#6B7280', marginBottom: 20 }}>
          <code style={{ background: '#F3F4F6', padding: '2px 6px', borderRadius: 4 }}>{state}</code>
          {' → '}
          {minionIds.length} minion{minionIds.length !== 1 ? 's' : ''}
        </p>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
            Pillar overrides{' '}
            <span style={{ fontWeight: 400, color: '#9CA3AF' }}>(optional)</span>
          </div>
          {pairs.map((row, i) => (
            <div
              key={row._key}
              style={{
                display: 'flex',
                gap: 8,
                marginBottom: 8,
                alignItems: 'center',
              }}
            >
              <input
                placeholder="key"
                value={row.key}
                onChange={(e) => update(i, 'key', e.target.value)}
                style={{
                  flex: 1,
                  border: '1px solid #D1D5DB',
                  borderRadius: 6,
                  padding: '6px 10px',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
              <input
                placeholder="value"
                value={row.value}
                onChange={(e) => update(i, 'value', e.target.value)}
                style={{
                  flex: 1,
                  border: '1px solid #D1D5DB',
                  borderRadius: 6,
                  padding: '6px 10px',
                  fontSize: 13,
                  outline: 'none',
                }}
              />
              <button
                onClick={() => remove(i)}
                style={{
                  color: '#9CA3AF',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 16,
                  lineHeight: 1,
                  padding: '0 4px',
                }}
              >
                ×
              </button>
            </div>
          ))}
          <button
            onClick={add}
            style={{
              fontSize: 12,
              color: '#2563EB',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
              fontWeight: 600,
            }}
          >
            + Add pillar key
          </button>
        </div>

        {/* Dry-run toggle. When enabled, the request is dispatched with
            test=True so Salt reports what would change without writing
            any changes. Maps to the Celery task's test_mode kwarg. */}
        <label
          htmlFor="salt-test-mode"
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            padding: '10px 12px',
            background: testMode ? '#FEF3C7' : '#F9FAFB',
            border: testMode ? '1px solid #FCD34D' : '1px solid #E5E7EB',
            borderRadius: 8,
            cursor: 'pointer',
            transition: 'background 120ms, border-color 120ms',
          }}
        >
          <input
            id="salt-test-mode"
            type="checkbox"
            checked={testMode}
            onChange={(e) => setTestMode(e.target.checked)}
            style={{ marginTop: 3, cursor: 'pointer' }}
          />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>
              Dry-run (test=True)
            </div>
            <div style={{ fontSize: 12, color: '#6B7280', marginTop: 2 }}>
              Evaluate the state and show what would change. No changes are
              applied. Equivalent to <code>salt-call state.apply test=True</code>.
            </div>
          </div>
        </label>

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 10,
            marginTop: 24,
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '8px 18px',
              borderRadius: 8,
              border: '1px solid #E5E7EB',
              background: '#fff',
              color: '#374151',
              fontSize: 14,
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            style={{
              padding: '8px 18px',
              borderRadius: 8,
              border: 'none',
              background: testMode ? '#D97706' : '#2563EB',
              color: '#fff',
              fontSize: 14,
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            {testMode ? 'Dry-run' : 'Run State'}
          </button>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';

export type BuilderStep = {
  id: string;
  order: number;
  role: string;
  action: string;
  execution: 'sequential' | 'parallel';
  deadline_hours: number | null;
  notification_channel: 'email' | 'sms';
};

export type PartySuggestion = {
  role: string;
  email: string | null;
  phone_number: string | null;
};

interface StepBuilderProps {
  value: BuilderStep[];
  onChange: (steps: BuilderStep[]) => void;
  partySuggestions?: PartySuggestion[];
}

const emptyStep = (order: number): BuilderStep => ({
  id: crypto.randomUUID(),
  order,
  role: 'signer',
  action: 'sign',
  execution: 'sequential',
  deadline_hours: null,
  notification_channel: 'email',
});

const StepCard = ({ children }: { children: React.ReactNode }) => (
  <div className="border border-slate-200 rounded-lg bg-white shadow-sm p-4 space-y-3">{children}</div>
);

const StepBuilder = ({ value, onChange, partySuggestions = [] }: StepBuilderProps) => {
  const [items, setItems] = useState<BuilderStep[]>(value);

  useEffect(() => {
    setItems(value);
  }, [value]);

  const roleOptions = useMemo(
    () => Array.from(new Set(partySuggestions.map(suggestion => suggestion.role))),
    [partySuggestions],
  );

  const update = (next: BuilderStep[]) => {
    setItems(next);
    onChange(next);
  };

  const addStep = () => update([...items, emptyStep(items.length + 1)]);

  const removeStep = (id: string) => {
    const next = items
      .filter(step => step.id !== id)
      .map((step, index) => ({ ...step, order: index + 1 }));
    update(next);
  };

  const updateStep = (id: string, patch: Partial<BuilderStep>) => {
    const next = items.map(step => (step.id === id ? { ...step, ...patch } : step));
    update(next);
  };

  const handleMove = (index: number, direction: -1 | 1) => {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= items.length) return;
    const copy = [...items];
    const [moved] = copy.splice(index, 1);
    copy.splice(newIndex, 0, moved);
    const reordered = copy.map((step, i) => ({ ...step, order: i + 1 }));
    update(reordered);
  };

  const warningsForStep = (step: BuilderStep): string[] => {
    const matching = partySuggestions.find(
      suggestion => suggestion.role.trim().toLowerCase() === step.role.trim().toLowerCase(),
    );
    const warnings: string[] = [];

    if (!matching) {
      warnings.push('Nenhuma parte cadastrada com este papel.');
    } else {
      if (step.notification_channel === 'email' && !matching.email) {
        warnings.push('Canal email selecionado, mas a parte não possui e-mail.');
      }
      if (step.notification_channel === 'sms' && !matching.phone_number) {
        warnings.push('Canal SMS selecionado, mas a parte não possui telefone.');
      }
    }

    return warnings;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Etapas configuradas</h3>
        <button type="button" onClick={addStep} className="btn btn-secondary">
          Adicionar etapa
        </button>
      </div>
      {partySuggestions.length > 0 && (
        <p className="text-sm text-slate-500">
          Papéis sugeridos: {roleOptions.join(', ')}
        </p>
      )}
      <div className="space-y-3">
        {items.map((step, index) => (
          <StepCard key={step.id}>
            <div className="flex flex-wrap gap-3">
              <div className="flex-1 min-w-[160px]">
                <label className="block text-sm font-medium text-slate-600">Papel</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={step.role}
                  list={`roles-${step.id}`}
                  onChange={event => updateStep(step.id, { role: event.target.value })}
                />
                {roleOptions.length > 0 && (
                  <datalist id={`roles-${step.id}`}>
                    {roleOptions.map(option => (
                      <option key={`${step.id}-${option}`} value={option} />
                    ))}
                  </datalist>
                )}
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="block text-sm font-medium text-slate-600">Ação</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={step.action}
                  onChange={event => updateStep(step.id, { action: event.target.value })}
                />
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="block text-sm font-medium text-slate-600">Execução</label>
                <select
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={step.execution}
                  onChange={event => updateStep(step.id, { execution: event.target.value as BuilderStep['execution'] })}
                >
                  <option value="sequential">Sequencial</option>
                  <option value="parallel">Paralelo</option>
                </select>
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="block text-sm font-medium text-slate-600">Deadline (horas)</label>
                <input
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  type="number"
                  min={1}
                  max={2160}
                  value={step.deadline_hours ?? ''}
                  onChange={event => updateStep(step.id, { deadline_hours: event.target.value ? Number(event.target.value) : null })}
                />
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="block text-sm font-medium text-slate-600">Canal</label>
                <select
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={step.notification_channel}
                  onChange={event => updateStep(step.id, { notification_channel: event.target.value as BuilderStep['notification_channel'] })}
                >
                  <option value="email">Email</option>
                  <option value="sms">SMS</option>
                </select>
              </div>
            </div>
            {(() => {
              const warnings = warningsForStep(step);
              if (!warnings.length) return null;
              return (
                <ul className="text-xs text-red-600 list-disc list-inside">
                  {warnings.map((warning, i) => (
                    <li key={i}>{warning}</li>
                  ))}
                </ul>
              );
            })()}
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2">
                <button type="button" className="btn btn-ghost" onClick={() => handleMove(index, -1)} disabled={index === 0}>
                  ↑
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => handleMove(index, 1)} disabled={index === items.length - 1}>
                  ↓
                </button>
                <span className="text-sm text-slate-500">Ordem #{step.order}</span>
              </div>
              <button type="button" className={clsx('btn btn-danger')} onClick={() => removeStep(step.id)}>
                Remover
              </button>
            </div>
          </StepCard>
        ))}
      </div>
    </div>
  );
};

export default StepBuilder;

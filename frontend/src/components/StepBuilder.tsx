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
  signature_method: 'electronic' | 'digital';
  representative_name: string;
  representative_cpf: string;
  company_name: string;
  company_tax_id: string;
  representative_email: string;
  representative_phone: string;
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
  signature_method: 'electronic',
  representative_name: '',
  representative_cpf: '',
  company_name: '',
  company_tax_id: '',
  representative_email: '',
  representative_phone: '',
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
              <div className="flex-1 min-w-[180px]">
                <label className="block text-sm font-medium text-slate-600">Tipo de assinatura</label>
                <select
                  className="w-full border border-slate-300 rounded-md px-3 py-2"
                  value={step.signature_method}
                  onChange={event => updateStep(step.id, { signature_method: event.target.value as BuilderStep['signature_method'] })}
                >
                  <option value="electronic">Eletrônica</option>
                  <option value="digital">Digital (certificado ICP)</option>
                </select>
              </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-slate-600">Nome do representante</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                value={step.representative_name}
                onChange={event => updateStep(step.id, { representative_name: event.target.value })}
                placeholder="Ex.: Maria Silva"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">CPF do representante</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                value={step.representative_cpf}
                onChange={event => updateStep(step.id, { representative_cpf: event.target.value.replace(/\D/g, '') })}
                placeholder="Somente numeros"
                maxLength={11}
                inputMode="numeric"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">Empresa</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                value={step.company_name}
                onChange={event => updateStep(step.id, { company_name: event.target.value })}
                placeholder="Nome fantasia ou razao social"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">CNPJ</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                value={step.company_tax_id}
                onChange={event => updateStep(step.id, { company_tax_id: event.target.value.replace(/\D/g, '') })}
                placeholder="Somente numeros"
                maxLength={14}
                inputMode="numeric"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">Email sugerido</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                type="email"
                value={step.representative_email}
                onChange={event => updateStep(step.id, { representative_email: event.target.value })}
                placeholder="contato@empresa.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600">Telefone sugerido</label>
              <input
                className="w-full border border-slate-300 rounded-md px-3 py-2"
                value={step.representative_phone}
                onChange={event => updateStep(step.id, { representative_phone: event.target.value })}
                placeholder="(11) 99999-0000"
              />
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

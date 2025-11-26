import { useState } from 'react';
import type { DocumentParty } from '../api';
import { updateDocumentParty } from '../api';
import toast from 'react-hot-toast';

interface Props {
  documentId: string;
  party: DocumentParty;
  onUpdated?: (p: DocumentParty) => void;
}

export default function PartiesSignatureMethodSelector({ documentId, party, onUpdated }: Props) {
  const [loading, setLoading] = useState(false);
  const value = party.requires_certificate ? 'digital' : 'electronic';

  const handleChange = async (next: 'electronic' | 'digital') => {
    try {
      setLoading(true);
      const requires_certificate = next === 'digital';
      const updated = await updateDocumentParty(documentId, party.id, {
        requires_certificate,
        // travas de UX coerentes com a escolha
        allow_typed_name: !requires_certificate,
        allow_signature_image: !requires_certificate,
        allow_signature_draw: !requires_certificate,
      });
      toast.success('Tipo de assinatura atualizado');
      onUpdated?.(updated);
    } catch (e: any) {
      console.error(e);
      toast.error(e?.message ?? 'Falha ao atualizar tipo de assinatura');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-4">
      <span className="text-sm text-gray-500">Assinatura:</span>
      <label className="flex items-center gap-1 cursor-pointer">
        <input
          type="radio"
          name={`sig-type-${party.id}`}
          disabled={loading}
          checked={value === 'electronic'}
          onChange={() => handleChange('electronic')}
        />
        <span>Eletronica</span>
      </label>
      <label className="flex items-center gap-1 cursor-pointer">
        <input
          type="radio"
          name={`sig-type-${party.id}`}
          disabled={loading}
          checked={value === 'digital'}
          onChange={() => handleChange('digital')}
        />
        <span>Digital (A1/A3)</span>
      </label>
    </div>
  );
}




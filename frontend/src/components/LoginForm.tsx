import { FormEvent, useState } from 'react';

interface LoginFormProps {
  onSubmit: (email: string, password: string) => Promise<void>;
  isLoading?: boolean;
  error?: string | null;
  onForgotPassword?: (email: string) => Promise<void>;
}

const LoginForm = ({ onSubmit, isLoading, error, onForgotPassword }: LoginFormProps) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setFeedback(null);
    await onSubmit(email, password);
  };

  const handleForgotPassword = async () => {
    if (!onForgotPassword) return;
    if (!email.trim()) {
      setFeedback('Informe o e-mail para recuperar a senha.');
      return;
    }
    setFeedback(null);
    try {
      await onForgotPassword(email.trim());
      setFeedback('Se o e-mail existir, você receberá uma senha temporária.');
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Falha ao solicitar redefinição.';
      setFeedback(detail);
    }
  };

  return (
    <div className="max-w-md mx-auto bg-white border border-slate-200 rounded-xl shadow-sm p-6 mt-12">
      <h2 className="text-xl font-semibold text-slate-800">Entrar</h2>
      <p className="text-sm text-slate-500 mb-4">Use suas credenciais da API para acessar o painel de templates.</p>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="block text-sm font-medium text-slate-600">E-mail</label>
          <input
            className="w-full border border-slate-300 rounded-md px-3 py-2"
            type="email"
            value={email}
            onChange={event => setEmail(event.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-600">Senha</label>
          <input
            className="w-full border border-slate-300 rounded-md px-3 py-2"
            type="password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            required
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {feedback && !error && <p className="text-sm text-slate-600">{feedback}</p>}
        <div className="space-y-2">
          <button type="submit" className="btn btn-primary w-full" disabled={isLoading}>
            {isLoading ? 'Entrando...' : 'Entrar'}
          </button>
          {onForgotPassword && (
            <button
              type="button"
              className="w-full text-sm text-slate-600 underline hover:text-slate-900"
              onClick={handleForgotPassword}
              disabled={isLoading}
            >
              Esqueci minha senha
            </button>
          )}
        </div>
      </form>
    </div>
  );
};

export default LoginForm;

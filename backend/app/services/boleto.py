import requests
from typing import Optional

class BoletoService:
    """Exemplo de integração simplificada para emissão de boletos via Gerencianet/PagSeguro."""
    def __init__(self, api_url: str, client_id: str, client_secret: str):
        self.api_url = api_url
        self.client_id = client_id
        self.client_secret = client_secret

    def emitir_boleto(self, valor_cents: int, vencimento: str, nome: str, cpf: str, descricao: str) -> Optional[dict]:
        payload = {
            "valor": valor_cents / 100,
            "vencimento": vencimento,
            "nome": nome,
            "cpf": cpf,
            "descricao": descricao,
        }
        # Exemplo: chamada fictícia, adapte para API real
        try:
            response = requests.post(
                f"{self.api_url}/boletos",
                json=payload,
                auth=(self.client_id, self.client_secret),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            print(f"Erro ao emitir boleto: {exc}")
            return None

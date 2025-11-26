import logging
import sys

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('log/server.log', encoding='utf-8')
    ]
)

logger = logging.getLogger('nacionalsign')

# Exemplo de uso:
# logger.info('Servidor iniciado')
# logger.error('Erro crítico!')

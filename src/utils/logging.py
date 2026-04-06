"""
Configuração centralizada de logging com Loguru.

- Saída colorida no stderr para desenvolvimento
- Arquivo rotativo diário em logs/ com retenção de 7 dias
- Nível configurável via variável de ambiente LOG_LEVEL
"""

import os
import sys

from loguru import logger


def setup_logging(log_level: str | None = None) -> None:
    """
    Configura o logger global.

    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR).
                   Se não informado, lê de LOG_LEVEL no ambiente, defaultando para INFO.
    """
    level = log_level or os.getenv("LOG_LEVEL", "INFO").upper()

    # Remove o handler padrão do loguru
    logger.remove()

    # Handler de console (stderr) — colorido, nível configurável
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=level,
        colorize=True,
    )

    # Handler de arquivo — rotação diária, retenção de 7 dias
    try:
        logger.add(
            "logs/estoca_inventory_{time:YYYY-MM-DD}.log",
            rotation="00:00",       # rotaciona à meia-noite
            retention="7 days",
            compression="zip",
            level="DEBUG",          # arquivo sempre em DEBUG para diagnóstico
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
            encoding="utf-8",
        )
    except Exception:
        # Não falha o startup se o diretório logs/ não puder ser criado
        logger.warning("Não foi possível criar arquivo de log em logs/. Apenas saída em console ativa.")

    logger.debug(f"Logger configurado. Nível: {level}")


# Exporta o logger configurado para uso em outros módulos
__all__ = ["logger", "setup_logging"]

"""
Cliente HTTP para a API Estoca.

Responsabilidades:
- Gerenciar sessão HTTP com headers de autenticação
- Retry automático com backoff exponencial (tenacity)
- Tratamento de rate limit (429) com respeito ao Retry-After
- Levantamento de exceções semânticas para erros não-retriáveis

Não contém lógica de negócio — apenas transporte HTTP.
"""

import time
from typing import Any

import requests
from loguru import logger
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class EstocaAuthError(Exception):
    """Erro de autenticação (HTTP 401). Não deve ser retriado."""
    pass


class EstocaNotFoundError(Exception):
    """Recurso não encontrado (HTTP 404). Não deve ser retriado."""
    pass


class EstocaRateLimitError(Exception):
    """Rate limit excedido (HTTP 429) após todas as tentativas de retry."""
    pass


class EstocaAPIError(Exception):
    """Erro genérico da API (5xx ou resposta inesperada)."""
    pass


class EstocaHttpClient:
    """
    Cliente HTTP autenticado para a API Estoca.

    Uma instância por api_key — crie uma nova instância para cada operação/credencial.
    """

    # Limite documentado de SKUs por requisição de inventário
    INVENTORY_BATCH_SIZE = 50

    def __init__(self, api_key: str, base_url: str = "https://api.estoca.com.br") -> None:
        """
        Args:
            api_key:  API key da operação (X-Api-Key header).
            base_url: URL base da API. Default: produção.
        """
        self.base_url = base_url.rstrip("/") + "/ollie"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Api-Key": api_key,
                "X-Api-Version": "v1",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        """
        Valida o status HTTP e retorna o JSON parseado.

        Raises:
            EstocaAuthError:      HTTP 401
            EstocaNotFoundError:  HTTP 404
            EstocaRateLimitError: HTTP 429 (após esgotamento de retries)
            EstocaAPIError:       demais erros HTTP
        """
        if response.status_code == 200:
            try:
                return response.json()
            except Exception as exc:
                raise EstocaAPIError(
                    f"Resposta HTTP 200 mas JSON inválido: {response.text[:200]}"
                ) from exc

        if response.status_code == 401:
            raise EstocaAuthError(
                "Autenticação falhou (HTTP 401). Verifique a API key no arquivo .env."
            )

        if response.status_code == 404:
            raise EstocaNotFoundError(
                f"Recurso não encontrado (HTTP 404): {response.url}"
            )

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 10))
            logger.warning(
                f"Rate limit atingido (HTTP 429). Aguardando {retry_after}s antes de retry..."
            )
            time.sleep(retry_after)
            # Re-levanta para acionar o retry do tenacity
            raise requests.exceptions.RetryError(
                f"HTTP 429 — aguardou {retry_after}s", response=response
            )

        raise EstocaAPIError(
            f"Erro HTTP {response.status_code}: {response.text[:300]}"
        )

    @retry(
        retry=retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RetryError)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def get_products_page(self, page: int = 1, per_page: int = 100) -> dict[str, Any]:
        """
        Busca uma página do catálogo de produtos.

        Args:
            page:     Número da página (1-based).
            per_page: Itens por página (máx 100 documentado).

        Returns:
            JSON da resposta como dict.
        """
        url = f"{self.base_url}/products"
        params = {"page": page, "per_page": per_page}
        logger.debug(f"GET {url} page={page} per_page={per_page}")

        try:
            response = self.session.get(url, params=params, timeout=30)
            return self._handle_response(response)
        except (EstocaAuthError, EstocaNotFoundError):
            raise  # não retriar erros semânticos
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout em GET /products page={page}. Tentando novamente...")
            raise

    @retry(
        retry=retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RetryError)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def get_inventory_batch(self, warehouse_id: str, skus: list[str]) -> dict[str, Any]:
        """
        Busca saldos de inventário para um batch de SKUs.

        Args:
            warehouse_id: UUID do warehouse (obrigatório pela API).
            skus:         Lista de SKUs — máx INVENTORY_BATCH_SIZE por chamada.

        Returns:
            JSON da resposta como dict.

        Raises:
            ValueError: Se skus tiver mais de INVENTORY_BATCH_SIZE itens.
        """
        if len(skus) > self.INVENTORY_BATCH_SIZE:
            raise ValueError(
                f"Máximo {self.INVENTORY_BATCH_SIZE} SKUs por requisição. "
                f"Recebido: {len(skus)}. Use batching."
            )

        url = f"{self.base_url}/inventories"
        params: dict[str, Any] = {"warehouse": warehouse_id}

        if len(skus) == 1:
            params["sku"] = skus[0]
        else:
            params["skus"] = ",".join(skus)

        logger.debug(
            f"GET {url} warehouse={warehouse_id} skus_count={len(skus)}"
        )

        try:
            response = self.session.get(url, params=params, timeout=30)
            return self._handle_response(response)
        except (EstocaAuthError, EstocaNotFoundError):
            raise
        except requests.exceptions.Timeout:
            logger.warning(
                f"Timeout em GET /inventories warehouse={warehouse_id} skus={len(skus)}. "
                "Tentando novamente..."
            )
            raise

"""
Interface abstrata para providers de inventário.

Qualquer WMS futuro (SAP, Magento, NetSuite, etc.) deve implementar esta
interface para se integrar com o InventoryAggregationService sem nenhuma
mudança nas camadas de serviço ou dashboard.

Padrão de extensão:
  src/providers/
    base.py              ← este arquivo (contrato)
    estoca/
      provider.py        ← EstocaInventoryProvider (implementação atual)
    magento/
      provider.py        ← futuro MagentoInventoryProvider
    sap/
      provider.py        ← futuro SAPInventoryProvider
"""

from abc import ABC, abstractmethod

from src.models.inventory import InventoryRecord
from src.models.store import StoreConfig


class InventoryProvider(ABC):
    """
    Contrato que todo provider de estoque deve implementar.

    O método principal para uso externo é get_full_inventory().
    Os métodos get_all_skus() e get_inventory() existem para
    flexibilidade em cenários onde o chamador já conhece os SKUs.
    """

    @abstractmethod
    def get_all_skus(self, store_config: StoreConfig, operation_index: int) -> list[str]:
        """
        Descobre todos os SKUs disponíveis para uma operação.

        Implementações devem lidar com paginação internamente.

        Args:
            store_config:     Configuração da loja.
            operation_index:  Índice da operação em store_config.operations.

        Returns:
            Lista de SKUs únicos. Lista vazia se nenhum produto for encontrado.
        """
        ...

    @abstractmethod
    def get_inventory(
        self,
        store_config: StoreConfig,
        operation_index: int,
        skus: list[str],
    ) -> list[InventoryRecord]:
        """
        Busca saldos de inventário para uma lista de SKUs.

        Implementações devem lidar com batching (ex: máx 50 SKUs/req na Estoca).

        Args:
            store_config:     Configuração da loja.
            operation_index:  Índice da operação em store_config.operations.
            skus:             Lista de SKUs a consultar.

        Returns:
            Lista de InventoryRecord canônicos. Pode ter menos itens que skus
            se alguns não forem encontrados no warehouse.
        """
        ...

    def get_full_inventory(
        self,
        store_config: StoreConfig,
        operation_index: int,
    ) -> list[InventoryRecord]:
        """
        Descobre todos os SKUs e busca seus saldos.

        Implementação padrão combina get_all_skus() + get_inventory().
        Providers podem sobrescrever se houver endpoint mais eficiente.

        Args:
            store_config:     Configuração da loja.
            operation_index:  Índice da operação em store_config.operations.

        Returns:
            Lista completa de InventoryRecord canônicos.
        """
        skus = self.get_all_skus(store_config, operation_index)
        if not skus:
            return []
        return self.get_inventory(store_config, operation_index, skus)

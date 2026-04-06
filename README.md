# Estoque Estoca — Dashboard de Consolidação

Aplicação Python + Streamlit que consolida os saldos de inventário de todas as lojas e operações do WMS Estoca, gerando uma visão unificada com filtros, métricas e exportação para CSV/Excel.

---

## Estrutura do Projeto

```
estoca-inventory/
├── .env                          # Credenciais reais (NÃO commitar — gitignored)
├── .env.example                  # Template de variáveis de ambiente
├── .gitignore
├── requirements.txt
├── README.md
│
├── config/
│   └── stores.yaml               # Mapeamento estrutural: lojas, warehouses, operações
│
├── src/
│   ├── config/
│   │   ├── settings.py           # GlobalSettings via pydantic-settings
│   │   └── stores.py             # Carrega stores.yaml e injeta API keys do .env
│   │
│   ├── models/
│   │   ├── inventory.py          # InventoryRecord — modelo canônico
│   │   └── store.py              # StoreConfig, OperationConfig
│   │
│   ├── providers/
│   │   ├── base.py               # InventoryProvider ABC (interface para futuros WMS)
│   │   └── estoca/
│   │       ├── client.py         # EstocaHttpClient (requests + tenacity)
│   │       ├── schemas.py        # Schemas Pydantic para respostas brutas da API
│   │       └── provider.py       # EstocaInventoryProvider
│   │
│   ├── services/
│   │   └── aggregation.py        # InventoryAggregationService + FetchResult
│   │
│   └── utils/
│       ├── logging.py            # Setup loguru
│       └── export.py             # CSV/Excel em memória
│
└── app/
    ├── main.py                   # Entry point Streamlit
    └── components/
        ├── filters.py            # Sidebar com FilterState
        ├── tables.py             # Tabelas detalhada e consolidada
        └── export.py             # Botões de download
```

---

## Instalação e Execução

### Pré-requisitos

- Python 3.11+
- pip

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar credenciais

```bash
# Copie o template e preencha com as credenciais reais
cp .env.example .env
```

Edite o `.env` com as API keys de cada operação. Consulte `.env.example` para o formato correto.

> **IMPORTANTE:** Nunca commite o arquivo `.env`. Ele já está no `.gitignore`.

### 3. Executar o dashboard

```bash
streamlit run app/main.py
```

O dashboard abrirá automaticamente no navegador em `http://localhost:8501`.

---

## Como Usar

1. Clique em **🔄 Atualizar Dados** na sidebar para consultar a API Estoca
2. Use os filtros laterais para refinar a visualização:
   - **SKU**: busca por substring no código do produto
   - **Loja**: filtra por código da loja (0101, 0102, 0103)
   - **Operação**: filtra por tipo (B2B, B2C, MKT, CROSS)
   - **Warehouse ID**: filtra por UUID do warehouse
3. Alterne entre as abas **Detalhada** e **Consolidada**
4. Use os botões de exportação para baixar os dados em CSV ou Excel

---

## API Estoca — Referência Técnica

### Autenticação

Todos os endpoints requerem dois headers:

```
X-Api-Key: {api_key}
X-Api-Version: v1
```

### Endpoints Utilizados

| Endpoint | Método | Propósito |
|---|---|---|
| `/products?page=1&per_page=100` | GET | Discovery de SKUs por operação |
| `/inventories?warehouse={id}&skus={lista}` | GET | Saldos de inventário (máx 50 SKUs/req) |

### Campos de Saldo

| Campo API | Campo Canônico | Descrição |
|---|---|---|
| `in_stock` | `stock_total` | Estoque físico total no warehouse |
| `available` | `stock_available` | Disponível para novos pedidos |
| `holded` | `stock_reserved` | Alocado em pedidos em andamento |
| `blocked` | `stock_blocked` | Bloqueado por divergência/avaria |

### Limitações Conhecidas

- **Máximo 50 SKUs por requisição** de inventário — a aplicação faz batching automático
- **Não existe endpoint para listar warehouses** — IDs configurados manualmente em `stores.yaml`
- **Rate limit não documentado numericamente** — a aplicação respeita o header `Retry-After` em respostas 429

---

## Configuração de Lojas (`config/stores.yaml`)

Este arquivo define a estrutura de lojas, warehouses e operações. **Não contém segredos** — pode ser commitado com segurança.

```yaml
estoca:
  stores:
    - store_code: "0101"
      warehouse_id: "uuid-do-warehouse"
      operations:
        - operation_type: "B2B"
          store_id: "uuid-do-store"
          env_key: "ESTOCA_0101_B2B_API_KEY"  # variável no .env
```

### dedup_group

A loja **0101** tem B2B e B2C com as **mesmas credenciais**. Para evitar double-count no saldo consolidado, o campo `dedup_group: "0101_MAIN"` instrui a aplicação a:

1. Fazer apenas **uma chamada API** para o grupo
2. Clonar os registros com `operation_type` diferente na **visão detalhada**
3. Contar o estoque **uma única vez** na **visão consolidada**

---

## Arquitetura — Extensibilidade para Múltiplos WMS

A aplicação foi projetada para suportar WMS internacionais no futuro:

### Adicionando um novo provider

1. Crie `src/providers/novo_wms/provider.py` implementando `InventoryProvider`:

```python
from src.providers.base import InventoryProvider
from src.models.inventory import InventoryRecord

class NovoWMSProvider(InventoryProvider):
    def get_all_skus(self, store_config, operation_index) -> list[str]:
        ...
    def get_inventory(self, store_config, operation_index, skus) -> list[InventoryRecord]:
        ...
```

2. Adicione a configuração do novo WMS em `config/stores.yaml`
3. Passe a nova instância do provider para `InventoryAggregationService`

**Nenhuma mudança** é necessária no dashboard, nos modelos ou no serviço de agregação.

---

## Logs

Logs são gravados em:
- **Console (stderr)**: colorido, nível configurável via `LOG_LEVEL` no `.env`
- **Arquivo**: `logs/estoca_inventory_YYYY-MM-DD.log` — rotação diária, retenção 7 dias

Para modo debug detalhado, adicione ao `.env`:
```
LOG_LEVEL=DEBUG
```

---

## Tratamento de Erros

| Código HTTP | Comportamento |
|---|---|
| 401 | Sem retry — operação marcada como falha, demais continuam |
| 404 | Sem retry — batch ignorado, continua |
| 429 | Retry com backoff — respeita `Retry-After`, até 5 tentativas |
| Timeout | Retry exponencial (2s → 60s), até 5 tentativas |
| 5xx | Retry até 3x, depois marca operação como falha |

Erros parciais são exibidos no dashboard em um banner expansível. O dashboard exibe dados das operações que tiveram sucesso mesmo quando outras falharem.

---

## Próximos Passos Sugeridos

1. **Cache de SKUs**: armazenar o catálogo de produtos localmente para acelerar refreshes
2. **Agendamento automático**: usar `apscheduler` ou `streamlit-autorefresh` para atualização periódica
3. **Histórico de saldos**: persistir snapshots em SQLite ou PostgreSQL para análise de tendências
4. **Alertas de estoque**: notificações quando `stock_available` cair abaixo de thresholds configuráveis
5. **Webhooks Estoca**: configurar webhook de inventário para atualizações em tempo real
6. **Novos WMS**: integrar providers para operações internacionais (SAP, NetSuite, Magento, etc.)
7. **Autenticação no dashboard**: adicionar login com `streamlit-authenticator` para ambientes compartilhados

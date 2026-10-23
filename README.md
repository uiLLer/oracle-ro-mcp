# oracle-ro-mcp

Servidor MCP (stdio) **somente leitura** para Oracle. Permite que um agente de IA consulte dados, metadados, índices e o fonte de PL/SQL sem poder alterar nada.

## Ferramentas
| Ferramenta | O que faz |
|---|---|
| `oracle_query(sql, max_rows, save_to)` | `SELECT`/`WITH`; opcionalmente grava CSV em `ORACLE_OUT_DIR` |
| `oracle_describe(table, owner)` | colunas de tabela/view |
| `oracle_tables(name_like, owner)` | tabelas e `NUM_ROWS` estimado |
| `oracle_indexes(table_like, owner)` | índices e colunas |
| `oracle_source(name_like, type, owner, save_to)` | fonte de procedure/function/package/trigger (`ALL_SOURCE`); `save_to` grava um `.sql` por objeto |

## Segurança (três camadas)
1. **Validador de SQL** (`guard.py`): só `SELECT`/`WITH`, sem `;` múltiplo, `DML/DDL`, `FOR UPDATE`, `INTO`, `DBMS_*`/`UTL_*`, database link ou PL/SQL embutido.
2. **Transação `SET TRANSACTION READ ONLY`** em toda conexão, com `rollback` ao final, timeout e teto de linhas.
3. **Grants do banco — a que realmente vale.** Use um usuário com apenas `SELECT` (e acesso a `ALL_SOURCE`, `ALL_INDEXES`, etc.). O validador é heurístico e não substitui isso. **Em produção, não use um usuário dono do esquema.**

A senha só entra por variável de ambiente; nunca como argumento nem no repositório.

## Instalação
```bash
pip install -e .
python -m unittest discover -s tests      # com PYTHONPATH=src, se não instalou
```

## Configuração
| Variável | Descrição |
|---|---|
| `ORACLE_DSN` | `host:porta/service_name`, `host:porta:SID` ou alias do `tnsnames.ora` (exige `TNS_ADMIN`) |
| `ORACLE_USER` / `ORACLE_PASSWORD` | credenciais |
| `ORACLE_MAX_ROWS` | teto de linhas (padrão 500) |
| `ORACLE_TIMEOUT_S` | timeout por chamada (padrão 60) |
| `ORACLE_OUT_DIR` | pasta onde `save_to` pode gravar (sem ela, gravar é desativado) |

### Claude Code
O `.mcp.json` do projeto **expande variáveis de ambiente**, então nada de segredo no arquivo:
```json
{
  "mcpServers": {
    "oracle-ro": {
      "command": "oracle-ro-mcp",
      "env": {
        "ORACLE_DSN": "${ORACLE_DSN}",
        "ORACLE_USER": "${ORACLE_USER}",
        "ORACLE_PASSWORD": "${ORACLE_PASSWORD}",
        "ORACLE_OUT_DIR": "${ORACLE_OUT_DIR}"
      }
    }
  }
}
```
Ou: `claude mcp add oracle-ro -- oracle-ro-mcp` (com as variáveis já no ambiente).

## Limitações
- Não há `EXPLAIN PLAN`: ele grava na `PLAN_TABLE`, o que a transação somente leitura recusa.
- Oracle 12.1+ (`oracledb` em modo thin, sem Oracle Client).
- Testado só o validador (`tests/`); as ferramentas que falam com o banco não têm teste automatizado.

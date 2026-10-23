# oracle-ro-mcp

Servidor MCP (stdio) **somente leitura** para Oracle. Permite que um agente de IA consulte dados, metadados, índices e o fonte de PL/SQL sem poder alterar nada.

## Ferramentas
Todas aceitam `profile` (opcional; sem ele vale o perfil `default`).

| Ferramenta | O que faz |
|---|---|
| `oracle_profiles()` | lista os perfis configurados (sem segredos) |
| `oracle_ping(profile)` | testa o perfil com `SELECT 1 FROM dual` |
| `oracle_query(sql, profile, max_rows, save_to)` | `SELECT`/`WITH`; opcionalmente grava CSV no `out_dir` do perfil |
| `oracle_describe(table, owner, profile)` | colunas de tabela/view |
| `oracle_tables(name_like, owner, profile)` | tabelas e `NUM_ROWS` estimado |
| `oracle_indexes(table_like, owner, profile)` | índices e colunas |
| `oracle_source(name_like, type, owner, profile, save_to)` | fonte de procedure/function/package/trigger (`ALL_SOURCE`); `save_to` grava um `.sql` por objeto |

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

## Configuração: perfis (estilo HikariCP)
Cada perfil é uma conexão nomeada, com **pool próprio** criado só no primeiro uso (`min=0`, `max=pool_max`). O arquivo é relido a cada chamada: editar perfis não exige reiniciar.

Arquivo TOML em `~/.oracle-ro-mcp/profiles.toml` (ou o caminho em `ORACLE_MCP_CONFIG`):
```toml
default = "dev"

[profiles.dev]
dsn          = "host-dev:1521/servico"
user         = "RO_DEV"
password_env = "ORACLE_PWD_DEV"        # NOME da variável; a senha nunca fica no arquivo
description  = "Desenvolvimento"

[profiles.prd]
dsn          = "host-prd:1521/servico"
user         = "RO_PRD"
password_env = "ORACLE_PWD_PRD"
max_rows     = 200                      # padrão 500
timeout_s    = 30                       # padrão 60
pool_max     = 2                        # padrão 2
out_dir      = "C:/saida/prd"           # sem isso, save_to fica desativado
```
Um `password` literal no arquivo é **recusado**. As senhas ficam em variáveis de ambiente (`ORACLE_PWD_DEV`, ...).

**Sem arquivo**, vale um perfil único `default` montado de `ORACLE_DSN`, `ORACLE_USER`, `ORACLE_PASSWORD` (e, opcionalmente, `ORACLE_MAX_ROWS`, `ORACLE_TIMEOUT_S`, `ORACLE_OUT_DIR`). `TNS_ADMIN` é necessário se o DSN for alias do `tnsnames.ora`.

### Claude Code
Os perfis vêm do TOML, então o `.mcp.json` não precisa de segredo nenhum. Pode apontar outro arquivo com `"env": {"ORACLE_MCP_CONFIG": "..."}`:
```json
{
  "mcpServers": {
    "oracle-ro": { "command": "oracle-ro-mcp" }
  }
}
```
Ou: `claude mcp add oracle-ro -- oracle-ro-mcp`.

## Limitações
- Não há `EXPLAIN PLAN`: ele grava na `PLAN_TABLE`, o que a transação somente leitura recusa.
- Oracle 12.1+ (`oracledb` em modo thin, sem Oracle Client).
- Testados só o validador e o carregamento de perfis (`tests/`); as ferramentas que falam com o banco não têm teste automatizado.

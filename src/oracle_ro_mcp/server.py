"""Servidor MCP (stdio) somente leitura para Oracle.

Variáveis de ambiente (nunca argumentos):
  ORACLE_DSN       host:porta/service_name, host:porta:SID, ou alias do tnsnames.ora (exige TNS_ADMIN)
  ORACLE_USER      usuário do banco (use um com apenas SELECT)
  ORACLE_PASSWORD  senha
  ORACLE_MAX_ROWS  teto de linhas por consulta (padrão 500)
  ORACLE_TIMEOUT_S timeout por chamada, em segundos (padrão 60)
  ORACLE_OUT_DIR   pasta onde `save_to` pode gravar (padrão: não permite gravar)
"""
import csv
import os
import re
from contextlib import contextmanager
from pathlib import Path

import oracledb

try:  # mcp >= 2: FastMCP foi renomeado para MCPServer
    from mcp.server.mcpserver import MCPServer as _Servidor
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Servidor

from .guard import SqlRecusado, validar_somente_leitura

oracledb.defaults.fetch_lobs = False  # CLOB/BLOB chegam como str/bytes

mcp = _Servidor("oracle-ro")

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
LIKE_PAT = re.compile(r"^[A-Za-z0-9_$#%]+$")


def _env(nome: str, padrao: str | None = None) -> str:
    valor = os.environ.get(nome, padrao)
    if valor is None:
        raise RuntimeError(f"Variável de ambiente {nome} não definida.")
    return valor


@contextmanager
def _conexao():
    timeout = int(_env("ORACLE_TIMEOUT_S", "60"))
    con = oracledb.connect(
        user=_env("ORACLE_USER"), password=_env("ORACLE_PASSWORD"), dsn=_env("ORACLE_DSN")
    )
    con.call_timeout = timeout * 1000
    try:
        cur = con.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.close()
        yield con
    finally:
        try:
            con.rollback()
        finally:
            con.close()


def _executar(sql: str, params: dict | None = None, max_rows: int | None = None) -> dict:
    limite = min(max_rows or int(_env("ORACLE_MAX_ROWS", "500")), int(_env("ORACLE_MAX_ROWS", "500")))
    with _conexao() as con:
        cur = con.cursor()
        cur.execute(sql, params or {})
        colunas = [d[0] for d in cur.description]
        linhas = cur.fetchmany(limite + 1)
    truncado = len(linhas) > limite
    linhas = [list(map(_texto, l)) for l in linhas[:limite]]
    return {"columns": colunas, "rows": linhas, "row_count": len(linhas), "truncated": truncado}


def _texto(valor):
    if valor is None or isinstance(valor, (int, float, str)):
        return valor
    return str(valor)


def _gravar(resultado: dict, save_to: str) -> str:
    base = os.environ.get("ORACLE_OUT_DIR")
    if not base:
        raise RuntimeError("ORACLE_OUT_DIR não definida: gravação em arquivo desativada.")
    raiz = Path(base).resolve()
    destino = (raiz / save_to).resolve()
    if raiz != destino and raiz not in destino.parents:
        raise RuntimeError("save_to precisa ficar dentro de ORACLE_OUT_DIR.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(resultado["columns"])
        w.writerows(resultado["rows"])
    return str(destino)


@mcp.tool()
def oracle_query(sql: str, max_rows: int = 200, save_to: str | None = None) -> dict:
    """Executa um SELECT/WITH somente leitura. `save_to` (opcional) grava CSV em ORACLE_OUT_DIR."""
    try:
        sql = validar_somente_leitura(sql)
    except SqlRecusado as e:
        return {"error": str(e)}
    resultado = _executar(sql, max_rows=max_rows)
    if save_to:
        resultado["saved_to"] = _gravar(resultado, save_to)
    return resultado


@mcp.tool()
def oracle_describe(table: str, owner: str | None = None) -> dict:
    """Colunas de uma tabela/view: nome, tipo, tamanho, anulável."""
    if not IDENT.match(table) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    return _executar(
        "SELECT column_id, column_name, data_type, data_length, data_precision, data_scale, nullable "
        "FROM all_tab_columns WHERE table_name = :t AND (:o IS NULL OR owner = :o) "
        "ORDER BY owner, column_id",
        {"t": table.upper(), "o": owner.upper() if owner else None},
        max_rows=1000,
    )


@mcp.tool()
def oracle_source(
    name_like: str, type: str = "PROCEDURE", owner: str | None = None, save_to: str | None = None
) -> dict:
    """Fonte PL/SQL de objetos (ALL_SOURCE) cujo nome case com `name_like` (use % como curinga).
    type: PROCEDURE, FUNCTION, PACKAGE, PACKAGE BODY, TRIGGER, TYPE. `save_to` grava um .sql por objeto
    dentro de ORACLE_OUT_DIR."""
    if not LIKE_PAT.match(name_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    if type.upper() not in {"PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER", "TYPE", "TYPE BODY"}:
        return {"error": "Tipo não suportado."}
    r = _executar(
        "SELECT owner, name, type, line, text FROM all_source "
        "WHERE name LIKE :n AND type = :t AND (:o IS NULL OR owner = :o) "
        "ORDER BY owner, name, type, line",
        {"n": name_like.upper(), "t": type.upper(), "o": owner.upper() if owner else None},
        max_rows=50000,
    )
    objetos: dict[tuple, list[str]] = {}
    for o, n, t, _l, texto in r["rows"]:
        objetos.setdefault((o, n, t), []).append(texto or "")
    saida = {"objects": [{"owner": o, "name": n, "type": t, "lines": len(v)} for (o, n, t), v in objetos.items()],
             "truncated": r["truncated"]}
    if save_to:
        base = os.environ.get("ORACLE_OUT_DIR")
        if not base:
            return {**saida, "error": "ORACLE_OUT_DIR não definida: gravação desativada."}
        raiz = Path(base).resolve()
        pasta = (raiz / save_to).resolve()
        if raiz != pasta and raiz not in pasta.parents:
            return {**saida, "error": "save_to precisa ficar dentro de ORACLE_OUT_DIR."}
        pasta.mkdir(parents=True, exist_ok=True)
        arquivos = []
        for (o, n, t), v in objetos.items():
            p = pasta / f"{n}.sql"
            p.write_text("CREATE OR REPLACE " + "".join(v), encoding="utf-8")
            arquivos.append(str(p))
        saida["saved_files"] = arquivos
    elif objetos:
        (o, n, t), v = next(iter(objetos.items()))
        saida["first_object_source"] = "".join(v)
    return saida


@mcp.tool()
def oracle_indexes(table_like: str, owner: str | None = None) -> dict:
    """Índices e colunas (ALL_INDEXES/ALL_IND_COLUMNS) das tabelas cujo nome case com `table_like`."""
    if not LIKE_PAT.match(table_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    return _executar(
        "SELECT i.table_owner, i.table_name, i.index_name, i.uniqueness, i.status, "
        "c.column_position, c.column_name "
        "FROM all_indexes i JOIN all_ind_columns c "
        "ON c.index_owner = i.owner AND c.index_name = i.index_name "
        "WHERE i.table_name LIKE :t AND (:o IS NULL OR i.table_owner = :o) "
        "ORDER BY i.table_owner, i.table_name, i.index_name, c.column_position",
        {"t": table_like.upper(), "o": owner.upper() if owner else None},
        max_rows=2000,
    )


@mcp.tool()
def oracle_tables(name_like: str = "%", owner: str | None = None) -> dict:
    """Lista tabelas (ALL_TABLES) com contagem estimada de linhas (NUM_ROWS, das estatísticas)."""
    if not LIKE_PAT.match(name_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    return _executar(
        "SELECT owner, table_name, num_rows, last_analyzed FROM all_tables "
        "WHERE table_name LIKE :n AND (:o IS NULL OR owner = :o) ORDER BY owner, table_name",
        {"n": name_like.upper(), "o": owner.upper() if owner else None},
        max_rows=1000,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

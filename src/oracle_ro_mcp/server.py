"""Servidor MCP (stdio) somente leitura para Oracle, com perfis de conexão e pool por perfil.

Configuração: veja perfis.py e o README. Segredos só por variável de ambiente.
"""
import csv
import re
import threading
from contextlib import contextmanager
from pathlib import Path

import oracledb

try:  # mcp >= 2: FastMCP foi renomeado para MCPServer
    from mcp.server.mcpserver import MCPServer as _Servidor
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Servidor

from . import perfis as _perfis
from .guard import SqlRecusado, validar_somente_leitura

oracledb.defaults.fetch_lobs = False  # CLOB/BLOB chegam como str/bytes

mcp = _Servidor("oracle-ro")

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
LIKE_PAT = re.compile(r"^[A-Za-z0-9_$#%]+$")

_pools: dict[str, oracledb.ConnectionPool] = {}
_trava = threading.Lock()


def _perfil(nome: str | None) -> _perfis.Perfil:
    todos, padrao = _perfis.carregar()  # relê o arquivo: editar perfis não exige reiniciar
    return _perfis.escolher(todos, padrao, nome)


def _pool(p: _perfis.Perfil) -> oracledb.ConnectionPool:
    with _trava:
        pool = _pools.get(p.nome)
        if pool is None:
            pool = oracledb.create_pool(user=p.user, password=p.senha(), dsn=p.dsn,
                                        min=0, max=p.pool_max, increment=1, timeout=300)
            _pools[p.nome] = pool
        return pool


@contextmanager
def _conexao(p: _perfis.Perfil):
    con = _pool(p).acquire()
    con.call_timeout = p.timeout_s * 1000
    try:
        cur = con.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.close()
        yield con
    finally:
        try:
            con.rollback()  # encerra a transação somente leitura antes de devolver ao pool
        finally:
            con.close()  # devolve ao pool


def _executar(p: _perfis.Perfil, sql: str, params: dict | None = None, max_rows: int | None = None) -> dict:
    limite = min(max_rows or p.max_rows, p.max_rows)
    with _conexao(p) as con:
        cur = con.cursor()
        cur.execute(sql, params or {})
        colunas = [d[0] for d in cur.description]
        linhas = cur.fetchmany(limite + 1)
    truncado = len(linhas) > limite
    linhas = [[_texto(v) for v in l] for l in linhas[:limite]]
    return {"profile": p.nome, "columns": colunas, "rows": linhas, "row_count": len(linhas), "truncated": truncado}


def _texto(valor):
    if valor is None or isinstance(valor, (int, float, str)):
        return valor
    return str(valor)


def _destino(p: _perfis.Perfil, save_to: str, out_dir: str | None) -> Path:
    """Pasta = parâmetro `out_dir` da chamada, ou o `out_dir` do perfil como padrão.
    Precisa ser caminho absoluto; `save_to` não pode sair dela."""
    base = out_dir or p.out_dir
    if not base:
        raise RuntimeError("Informe out_dir (ou configure out_dir no perfil): gravação em arquivo desativada.")
    if not Path(base).is_absolute():
        raise RuntimeError("out_dir precisa ser um caminho absoluto.")
    raiz = Path(base).resolve()
    destino = (raiz / save_to).resolve()
    if raiz != destino and raiz not in destino.parents:
        raise RuntimeError("save_to precisa ficar dentro de out_dir.")
    return destino


def _gravar_csv(p: _perfis.Perfil, resultado: dict, save_to: str, out_dir: str | None) -> str:
    if not save_to.lower().endswith(".csv"):
        save_to += ".csv"
    destino = _destino(p, save_to, out_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(resultado["columns"])
        w.writerows(resultado["rows"])
    return str(destino)


def _erro(e: Exception) -> dict:
    return {"error": str(e)}


@mcp.tool()
def oracle_profiles() -> dict:
    """Lista os perfis de conexão configurados (sem segredos) e qual é o padrão."""
    try:
        todos, padrao = _perfis.carregar()
    except _perfis.PerfilInvalido as e:
        return _erro(e)
    return {"default": padrao, "config_file": str(_perfis.caminho_config()),
            "profiles": [p.publico() for p in todos.values()]}


@mcp.tool()
def oracle_ping(profile: str | None = None) -> dict:
    """Testa o perfil: conecta pelo pool e executa SELECT 1 FROM dual."""
    try:
        return _executar(_perfil(profile), "SELECT 1 AS ok FROM dual")
    except (_perfis.PerfilInvalido, oracledb.Error) as e:
        return _erro(e)


@mcp.tool()
def oracle_query(sql: str, profile: str | None = None, max_rows: int = 200,
                 save_to: str | None = None, out_dir: str | None = None) -> dict:
    """Executa um SELECT/WITH somente leitura no perfil escolhido. `save_to` grava um CSV em `out_dir`
    (caminho absoluto; se omitido, usa o out_dir do perfil)."""
    try:
        sql = validar_somente_leitura(sql)
        p = _perfil(profile)
        resultado = _executar(p, sql, max_rows=max_rows)
        if save_to:
            resultado["saved_to"] = _gravar_csv(p, resultado, save_to, out_dir)
        return resultado
    except (SqlRecusado, _perfis.PerfilInvalido, oracledb.Error, RuntimeError) as e:
        return _erro(e)


@mcp.tool()
def oracle_describe(table: str, owner: str | None = None, profile: str | None = None) -> dict:
    """Colunas de uma tabela/view: nome, tipo, tamanho, anulável."""
    if not IDENT.match(table) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    try:
        return _executar(
            _perfil(profile),
            "SELECT owner, column_id, column_name, data_type, data_length, data_precision, data_scale, nullable "
            "FROM all_tab_columns WHERE table_name = :t AND (:o IS NULL OR owner = :o) "
            "ORDER BY owner, column_id",
            {"t": table.upper(), "o": owner.upper() if owner else None}, max_rows=1000)
    except (_perfis.PerfilInvalido, oracledb.Error) as e:
        return _erro(e)


@mcp.tool()
def oracle_tables(name_like: str = "%", owner: str | None = None, profile: str | None = None) -> dict:
    """Lista tabelas (ALL_TABLES) com contagem estimada de linhas (NUM_ROWS, das estatísticas)."""
    if not LIKE_PAT.match(name_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    try:
        return _executar(
            _perfil(profile),
            "SELECT owner, table_name, num_rows, last_analyzed FROM all_tables "
            "WHERE table_name LIKE :n AND (:o IS NULL OR owner = :o) ORDER BY owner, table_name",
            {"n": name_like.upper(), "o": owner.upper() if owner else None}, max_rows=1000)
    except (_perfis.PerfilInvalido, oracledb.Error) as e:
        return _erro(e)


@mcp.tool()
def oracle_indexes(table_like: str, owner: str | None = None, profile: str | None = None) -> dict:
    """Índices e colunas (ALL_INDEXES/ALL_IND_COLUMNS) das tabelas cujo nome case com `table_like`."""
    if not LIKE_PAT.match(table_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    try:
        return _executar(
            _perfil(profile),
            "SELECT i.table_owner, i.table_name, i.index_name, i.uniqueness, i.status, "
            "c.column_position, c.column_name "
            "FROM all_indexes i JOIN all_ind_columns c "
            "ON c.index_owner = i.owner AND c.index_name = i.index_name "
            "WHERE i.table_name LIKE :t AND (:o IS NULL OR i.table_owner = :o) "
            "ORDER BY i.table_owner, i.table_name, i.index_name, c.column_position",
            {"t": table_like.upper(), "o": owner.upper() if owner else None}, max_rows=2000)
    except (_perfis.PerfilInvalido, oracledb.Error) as e:
        return _erro(e)


@mcp.tool()
def oracle_source(name_like: str, type: str = "PROCEDURE", owner: str | None = None,
                  profile: str | None = None, save_to: str | None = None, out_dir: str | None = None) -> dict:
    """Fonte PL/SQL de objetos (ALL_SOURCE) cujo nome case com `name_like` (% é curinga).
    type: PROCEDURE, FUNCTION, PACKAGE, PACKAGE BODY, TRIGGER, TYPE, TYPE BODY. Com `save_to` (subpasta,
    use "." para a própria pasta) grava um .sql por objeto em `out_dir` (absoluto; padrão: out_dir do perfil)."""
    if not LIKE_PAT.match(name_like) or (owner and not IDENT.match(owner)):
        return {"error": "Nome inválido."}
    if type.upper() not in {"PROCEDURE", "FUNCTION", "PACKAGE", "PACKAGE BODY", "TRIGGER", "TYPE", "TYPE BODY"}:
        return {"error": "Tipo não suportado."}
    try:
        p = _perfil(profile)
        r = _executar(
            p,
            "SELECT owner, name, type, line, text FROM all_source "
            "WHERE name LIKE :n AND type = :t AND (:o IS NULL OR owner = :o) "
            "ORDER BY owner, name, type, line",
            {"n": name_like.upper(), "t": type.upper(), "o": owner.upper() if owner else None},
            max_rows=50000)
        objetos: dict[tuple, list[str]] = {}
        for o, n, t, _l, texto in r["rows"]:
            objetos.setdefault((o, n, t), []).append(texto or "")
        saida = {"profile": p.nome,
                 "objects": [{"owner": o, "name": n, "type": t, "lines": len(v)} for (o, n, t), v in objetos.items()],
                 "truncated": r["truncated"]}
        if save_to:
            pasta = _destino(p, save_to, out_dir)
            pasta.mkdir(parents=True, exist_ok=True)
            saida["saved_files"] = []
            for (o, n, t), v in objetos.items():
                arq = pasta / f"{n}.sql"
                arq.write_text("CREATE OR REPLACE " + "".join(v), encoding="utf-8")
                saida["saved_files"].append(str(arq))
        elif objetos:
            saida["first_object_source"] = "".join(next(iter(objetos.values())))
        return saida
    except (_perfis.PerfilInvalido, oracledb.Error, RuntimeError) as e:
        return _erro(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

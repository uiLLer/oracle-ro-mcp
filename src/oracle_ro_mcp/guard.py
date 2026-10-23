"""Validação de SQL somente leitura.

Esta é a primeira camada. A segunda é a transação `SET TRANSACTION READ ONLY` aberta
pelo servidor. A terceira, e a que realmente vale, são os grants do usuário do banco:
use um usuário com apenas SELECT.
"""
import re

PROIBIDAS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "EXECUTE", "EXEC", "CALL", "BEGIN", "DECLARE", "LOCK",
    "COMMIT", "ROLLBACK", "SAVEPOINT", "RENAME", "COMMENT", "ANALYZE", "FLASHBACK",
    "PURGE", "AUDIT", "NOAUDIT", "FUNCTION", "PROCEDURE", "PRAGMA", "INTO",
}
PREFIXOS_PROIBIDOS = ("DBMS_", "UTL_", "SYS.DBMS", "SYS.UTL")


class SqlRecusado(ValueError):
    pass


def _sem_literais_e_comentarios(sql: str) -> str:
    """Troca literais 'x', identificadores "x" e comentários por espaço, mantendo o resto."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"q'(.).*?\1'", "''", sql, flags=re.S | re.I)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def validar_somente_leitura(sql: str) -> str:
    """Devolve o SQL limpo (sem `;` final) ou levanta SqlRecusado."""
    if not sql or not sql.strip():
        raise SqlRecusado("SQL vazio.")
    limpo = _sem_literais_e_comentarios(sql).strip()
    if limpo.endswith(";"):
        limpo = limpo[:-1].rstrip()
        sql = sql.strip()
        sql = sql[:-1] if sql.endswith(";") else sql
    if ";" in limpo:
        raise SqlRecusado("Mais de um comando (';') não é permitido.")
    maiusculo = limpo.upper()
    primeira = re.match(r"\s*\(*\s*([A-Z]+)", maiusculo)
    if not primeira or primeira.group(1) not in ("SELECT", "WITH"):
        raise SqlRecusado("Só são aceitos comandos que comecem com SELECT ou WITH.")
    for palavra in re.findall(r"[A-Z_][A-Z0-9_$#.]*", maiusculo):
        if palavra in PROIBIDAS:
            raise SqlRecusado(f"Palavra não permitida: {palavra}.")
        if palavra.startswith(PREFIXOS_PROIBIDOS):
            raise SqlRecusado(f"Pacote não permitido: {palavra}.")
    if re.search(r"\bFOR\s+UPDATE\b", maiusculo):
        raise SqlRecusado("FOR UPDATE não é permitido.")
    if "@" in limpo:
        raise SqlRecusado("Database link (@) não é permitido.")
    return sql.strip()

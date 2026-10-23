import unittest

from oracle_ro_mcp.guard import SqlRecusado, validar_somente_leitura


class GuardTest(unittest.TestCase):
    def test_aceita(self):
        for sql in [
            "SELECT 1 FROM dual",
            "select * from t where a = 'DELETE me' -- UPDATE",
            "WITH x AS (SELECT 1 a FROM dual) SELECT a FROM x;",
            "SELECT created_at, updated_by FROM t",
            "(SELECT 1 FROM dual) UNION ALL (SELECT 2 FROM dual)",
            "SELECT q'[INSERT; DROP]' FROM dual",
            'SELECT "UPDATE" FROM t',
        ]:
            validar_somente_leitura(sql)

    def test_recusa(self):
        for sql in [
            "",
            "DELETE FROM t",
            "SELECT 1 FROM dual; DROP TABLE t",
            "SELECT * FROM t FOR UPDATE",
            "SELECT DBMS_LOCK.SLEEP(10) FROM dual",
            "SELECT utl_http.request('x') FROM dual",
            "WITH FUNCTION f RETURN NUMBER IS BEGIN RETURN 1; END; SELECT f FROM dual",
            "SELECT * FROM t@outro_banco",
            "INSERT INTO t SELECT * FROM u",
            "SELECT * INTO x FROM t",
            "BEGIN NULL; END;",
            "CALL p()",
        ]:
            with self.assertRaises(SqlRecusado, msg=sql):
                validar_somente_leitura(sql)


if __name__ == "__main__":
    unittest.main()

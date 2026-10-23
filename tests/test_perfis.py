import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from oracle_ro_mcp import perfis

TOML = """
default = "dev"
[profiles.dev]
dsn = "h1:1521/svc"
user = "RO"
password_env = "PWD_DEV"
[profiles.prd]
dsn = "h2:1521/svc"
user = "RO"
password_env = "PWD_PRD"
max_rows = 100
pool_max = 4
"""


def _arq(texto: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / "profiles.toml"
    p.write_text(texto, encoding="utf-8")
    return p


class PerfisTest(unittest.TestCase):
    def test_carrega_e_escolhe(self):
        todos, padrao = perfis.carregar(_arq(TOML))
        self.assertEqual(padrao, "dev")
        self.assertEqual(perfis.escolher(todos, padrao, None).nome, "dev")
        self.assertEqual(perfis.escolher(todos, padrao, "prd").max_rows, 100)
        with self.assertRaises(perfis.PerfilInvalido):
            perfis.escolher(todos, padrao, "nao_existe")

    def test_recusa_senha_no_arquivo(self):
        with self.assertRaises(perfis.PerfilInvalido):
            perfis.carregar(_arq('[profiles.x]\ndsn="a"\nuser="u"\npassword_env="P"\npassword="segredo"\n'))

    def test_recusa_chave_desconhecida_e_faltante(self):
        with self.assertRaises(perfis.PerfilInvalido):
            perfis.carregar(_arq('[profiles.x]\ndsn="a"\nuser="u"\npassword_env="P"\nfoo=1\n'))
        with self.assertRaises(perfis.PerfilInvalido):
            perfis.carregar(_arq('[profiles.x]\ndsn="a"\nuser="u"\n'))

    def test_publico_nao_vaza_senha(self):
        todos, _ = perfis.carregar(_arq(TOML))
        with mock.patch.dict(os.environ, {"PWD_DEV": "s3gredo"}):
            pub = todos["dev"].publico()
        self.assertNotIn("s3gredo", str(pub))
        self.assertTrue(pub["password_set"])

    def test_senha_ausente(self):
        todos, _ = perfis.carregar(_arq(TOML))
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(perfis.PerfilInvalido):
                todos["prd"].senha()

    def test_fallback_variaveis_legadas(self):
        env = {"ORACLE_DSN": "h:1521/s", "ORACLE_USER": "u", "ORACLE_PASSWORD": "p"}
        with mock.patch.dict(os.environ, env, clear=True):
            todos, padrao = perfis.carregar(Path(tempfile.mkdtemp()) / "nao_existe.toml")
        self.assertEqual((list(todos), padrao), (["default"], "default"))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from oracle_ro_mcp import server
from oracle_ro_mcp.perfis import Perfil


def _p(out_dir=None):
    return Perfil(nome="t", dsn="d", user="u", password_env="P", out_dir=out_dir)


class DestinoTest(unittest.TestCase):
    def test_parametro_da_chamada(self):
        d = tempfile.mkdtemp()
        self.assertEqual(server._destino(_p(), "a/b.csv", d), (Path(d) / "a" / "b.csv").resolve())

    def test_padrao_do_perfil_e_override(self):
        pad, outra = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.assertEqual(server._destino(_p(pad), "x.sql", None).parent, Path(pad).resolve())
        self.assertEqual(server._destino(_p(pad), "x.sql", outra).parent, Path(outra).resolve())

    def test_recusas(self):
        d = tempfile.mkdtemp()
        for p, save, out in [(_p(), "x.csv", None), (_p(), "x.csv", "relativo/pasta"), (_p(), "../fora.csv", d)]:
            with self.assertRaises(RuntimeError):
                server._destino(p, save, out)

    def test_csv_ganha_extensao(self):
        d = tempfile.mkdtemp()
        r = {"columns": ["A"], "rows": [[1]]}
        self.assertTrue(server._gravar_csv(_p(), r, "saida", d).endswith("saida.csv"))


if __name__ == "__main__":
    unittest.main()

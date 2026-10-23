"""Perfis de conexão (estilo HikariCP): nome -> DSN, usuário, variável da senha, limites.

Arquivo TOML apontado por ORACLE_MCP_CONFIG (padrão: ~/.oracle-ro-mcp/profiles.toml).
A senha NUNCA fica no arquivo: o perfil guarda só o nome da variável de ambiente (`password_env`).
Sem arquivo, vale um perfil único "default" montado de ORACLE_DSN / ORACLE_USER / ORACLE_PASSWORD.
"""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CHAVES = {"dsn", "user", "password_env", "max_rows", "timeout_s", "pool_max", "out_dir", "description"}


class PerfilInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Perfil:
    nome: str
    dsn: str
    user: str
    password_env: str
    max_rows: int = 500
    timeout_s: int = 60
    pool_max: int = 2
    out_dir: str | None = None
    description: str = ""

    def senha(self) -> str:
        valor = os.environ.get(self.password_env)
        if not valor:
            raise PerfilInvalido(f"Variável {self.password_env} (senha do perfil '{self.nome}') não definida.")
        return valor

    def publico(self) -> dict:
        """Sem segredo: o que pode aparecer para o agente."""
        return {"name": self.nome, "dsn": self.dsn, "user": self.user, "password_env": self.password_env,
                "password_set": bool(os.environ.get(self.password_env)), "max_rows": self.max_rows,
                "timeout_s": self.timeout_s, "pool_max": self.pool_max,
                "out_dir_set": bool(self.out_dir), "description": self.description}


def caminho_config() -> Path:
    return Path(os.environ.get("ORACLE_MCP_CONFIG") or Path.home() / ".oracle-ro-mcp" / "profiles.toml")


def _perfil(nome: str, bruto: dict) -> Perfil:
    if "password" in bruto:
        raise PerfilInvalido(f"Perfil '{nome}': 'password' não é aceito no arquivo; use password_env.")
    desconhecidas = set(bruto) - CHAVES
    if desconhecidas:
        raise PerfilInvalido(f"Perfil '{nome}': chaves desconhecidas {sorted(desconhecidas)}.")
    for obrigatoria in ("dsn", "user", "password_env"):
        if not bruto.get(obrigatoria):
            raise PerfilInvalido(f"Perfil '{nome}': falta '{obrigatoria}'.")
    return Perfil(nome=nome, **bruto)


def carregar(caminho: Path | None = None) -> tuple[dict[str, Perfil], str | None]:
    """Devolve (perfis, nome_do_padrão)."""
    caminho = caminho or caminho_config()
    if caminho.is_file():
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
        brutos = dados.get("profiles") or {}
        if not brutos:
            raise PerfilInvalido("Arquivo sem seção [profiles.<nome>].")
        perfis = {n: _perfil(n, b) for n, b in brutos.items()}
        padrao = dados.get("default")
        if padrao and padrao not in perfis:
            raise PerfilInvalido(f"default='{padrao}' não existe em [profiles].")
        if not padrao and len(perfis) == 1:
            padrao = next(iter(perfis))
        return perfis, padrao
    if os.environ.get("ORACLE_DSN"):
        p = Perfil(nome="default", dsn=os.environ["ORACLE_DSN"], user=os.environ.get("ORACLE_USER", ""),
                   password_env="ORACLE_PASSWORD", max_rows=int(os.environ.get("ORACLE_MAX_ROWS", "500")),
                   timeout_s=int(os.environ.get("ORACLE_TIMEOUT_S", "60")),
                   out_dir=os.environ.get("ORACLE_OUT_DIR"))
        return {"default": p}, "default"
    return {}, None


def escolher(perfis: dict[str, Perfil], padrao: str | None, nome: str | None) -> Perfil:
    if not perfis:
        raise PerfilInvalido(f"Nenhum perfil configurado. Crie {caminho_config()} (veja o README).")
    alvo = nome or padrao
    if not alvo:
        raise PerfilInvalido(f"Informe 'profile'. Disponíveis: {sorted(perfis)}.")
    if alvo not in perfis:
        raise PerfilInvalido(f"Perfil '{alvo}' não existe. Disponíveis: {sorted(perfis)}.")
    return perfis[alvo]

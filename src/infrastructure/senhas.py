"""Hash das senhas com o werkzeug (scrypt/pbkdf2 com sal): a senha nunca é guardada."""

from werkzeug.security import check_password_hash, generate_password_hash


class SenhasWerkzeug:
    def gerar(self, senha: str) -> str:
        return generate_password_hash(senha)

    def confere(self, senha_hash: str, senha: str) -> bool:
        return bool(senha_hash) and check_password_hash(senha_hash, senha or "")

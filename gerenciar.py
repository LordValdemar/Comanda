"""
Ferramentas de administração pela linha de comando.

    python gerenciar.py listar-usuarios
    python gerenciar.py criar-usuario NOME [--papel admin|caixa|garcom|cozinha]
    python gerenciar.py trocar-senha NOME          # esqueceu a senha
    python gerenciar.py backup
    python gerenciar.py restaurar CAMINHO_DO_BACKUP.zip   # pare o serviço antes
"""

import argparse
import getpass
import sys

from comanda import arquivo_config, create_app, db
from comanda.auth import PAPEIS, ErroUsuario, criar_usuario, trocar_senha
from comanda.backup import criar_backup, restaurar_backup


def pedir_senha():
    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem.")
    return senha


def main(argumentos=None):
    parser = argparse.ArgumentParser(description="Administração da Comanda")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("listar-usuarios", help="mostra os usuários cadastrados")
    criar = comandos.add_parser("criar-usuario", help="cria um usuário")
    criar.add_argument("usuario")
    criar.add_argument("--papel", choices=sorted(PAPEIS), default="admin")
    trocar = comandos.add_parser("trocar-senha", help="redefine a senha (e reativa o usuário)")
    trocar.add_argument("usuario")
    comandos.add_parser("backup", help="faz um backup agora")
    restaurar = comandos.add_parser("restaurar", help="volta um backup (pare o serviço antes)")
    restaurar.add_argument("arquivo")
    args = parser.parse_args(argumentos)

    arquivo_config.carregar()
    app = create_app()
    with app.app_context():
        conexao = db.obter()
        if args.comando == "listar-usuarios":
            for linha in conexao.execute("SELECT * FROM usuarios ORDER BY usuario"):
                situacao = "" if linha["ativo"] else " (desativado)"
                print(f"{linha['usuario']:<25} {PAPEIS[linha['papel']]}{situacao}")
        elif args.comando == "criar-usuario":
            try:
                criar_usuario(conexao, args.usuario, pedir_senha(), args.papel)
            except ErroUsuario as erro:
                sys.exit(str(erro))
            print(f"Usuário “{args.usuario}” criado ({PAPEIS[args.papel]}).")
        elif args.comando == "trocar-senha":
            linha = conexao.execute("SELECT id FROM usuarios WHERE usuario = ?", (args.usuario,)).fetchone()
            if linha is None:
                sys.exit(f"Usuário “{args.usuario}” não encontrado.")
            try:
                trocar_senha(conexao, linha["id"], pedir_senha())
            except ErroUsuario as erro:
                sys.exit(str(erro))
            with conexao:
                conexao.execute("UPDATE usuarios SET ativo = 1 WHERE id = ?", (linha["id"],))
            print("Senha trocada.")
        elif args.comando == "backup":
            print(f"Backup criado: {criar_backup(app.config)}")
        elif args.comando == "restaurar":
            db.fechar()
            guardados = restaurar_backup(app.config, args.arquivo)
            print(f"Backup restaurado. Os dados anteriores foram guardados em: {guardados}")
            print("Agora inicie o serviço de novo: sudo systemctl start comanda")


if __name__ == "__main__":
    main()

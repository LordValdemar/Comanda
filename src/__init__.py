"""Código-fonte em camadas (arquitetura limpa).

- config:          variáveis de ambiente e arquivo configuracao.env
- domain:          regras de negócio puras (entidades e casos de uso), sem Flask nem banco
- infrastructure:  implementações (banco SQLite, Asaas, e-mail)
- interfaces:      portas de entrada (rotas HTTP)

A migração é feita por partes: o que ainda não passou para cá continua no pacote `propagandas`.
"""

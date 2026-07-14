# Alembic assíncrono sem modelos

## Objetivo

Preparar a infraestrutura mínima de migrations do Pertinho para usar a conexão
PostgreSQL assíncrona já existente. Este recorte cria uma base declarativa vazia,
configura o Alembic e comprova que uma revisão vazia pode ser aplicada ao banco
local.

## Escopo aprovado

- Criar uma `DeclarativeBase` compartilhada, ainda sem tabelas registradas.
- Inicializar o Alembic com execução assíncrona por `asyncpg`.
- Obter a URL do banco por `Settings`, sem duplicar credenciais em
  `alembic.ini`.
- Apontar `target_metadata` para a metadata da base declarativa.
- Criar uma revisão inicial vazia, com `upgrade` e `downgrade` sem operações de
  esquema.
- Testar a configuração e aplicar a revisão no PostgreSQL local.
- Documentar os comandos operacionais essenciais.

## Fora do escopo

- Modelos `Bracelet`, `Child`, `Parent`, `EmergencyProfile` ou `ChildParent`.
- Criação de tabelas, colunas, índices ou restrições de negócio.
- Definição dos dados privados de crianças e responsáveis.
- Endpoints, repositórios, serviços, autenticação ou dados iniciais.
- Alterações no Docker Compose ou criação de bancos exclusivos para testes.

## Arquitetura

A base declarativa ficará junto da infraestrutura de persistência em
`app/database.py`. Isso evita criar antecipadamente um pacote de modelos vazio.
Quando os modelos forem aprovados, eles herdarão dessa base.

O `alembic.ini` conterá apenas configurações operacionais, sem URL ou segredo
real. Em `alembic/env.py`, `Settings` fornecerá `DATABASE_URL` em tempo de
execução. O ambiente usará engine assíncrona e executará as operações do
Alembic por `run_sync`, que é a ponte oficial para migrations do SQLAlchemy.

A revisão inicial representará somente o marco de ativação do Alembic. Aplicá-la
criará apenas a tabela interna `alembic_version`; nenhuma tabela de negócio será
criada.

## Fluxo de execução

1. O comando do Alembic carrega `alembic.ini`.
2. `alembic/env.py` instancia `Settings` e injeta `DATABASE_URL` na configuração.
3. A engine assíncrona abre uma conexão com o PostgreSQL local.
4. O Alembic executa a revisão inicial vazia.
5. O banco registra a revisão em `alembic_version`.

## Erros e segurança

- A ausência ou invalidade de `DATABASE_URL` continuará falhando pela validação
  de `Settings`.
- Credenciais não serão escritas em `alembic.ini` nem em novos arquivos
  versionáveis.
- Falhas de conexão ou de migration não serão ocultadas; o comando terminará
  com erro para impedir um estado falsamente bem-sucedido.
- O teste não apagará volumes nem tabelas existentes.

## Estratégia TDD

1. Criar testes que exijam uma base declarativa com metadata inicialmente vazia.
2. Criar teste de integração que tente aplicar `upgrade head` e confirme a
   revisão atual no PostgreSQL.
3. Executar os testes e registrar a falha pela ausência da infraestrutura.
4. Implementar a base e os arquivos do Alembic.
5. Criar a revisão vazia e fazer os testes passarem.
6. Executar a suíte completa e o Ruff.

O teste de integração usará o PostgreSQL local em `127.0.0.1:5433`, seguindo a
infraestrutura atual. Ele poderá aplicar repetidamente `upgrade head`, que é
idempotente quando o banco já está na revisão atual.

## Critérios de aceitação

- A metadata da base declarativa não contém tabelas de negócio.
- `poetry run alembic upgrade head` funciona com a URL obtida de `Settings`.
- `poetry run alembic current` informa a revisão inicial.
- Apenas `alembic_version` é criada por este recorte.
- A suíte completa e o Ruff passam.
- Nenhum modelo ou endpoint é introduzido.

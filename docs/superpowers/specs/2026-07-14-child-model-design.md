# Modelo físico inicial de Child

## Objetivo

Criar a primeira entidade física do Pertinho com minimização de dados por
padrão. `Child` representará somente a identidade interna de uma criança, sem
armazenar qualquer dado pessoal, identificável ou sensível.

## Escopo aprovado

- Criar o modelo SQLAlchemy `Child`.
- Criar a tabela `children`.
- Adicionar somente a coluna `id`, do tipo UUID e chave primária.
- Gerar o UUID na aplicação com `uuid4`.
- Registrar o modelo na metadata usada pelo Alembic.
- Criar a migration `0002` com criação e remoção da tabela.
- Validar o modelo e a migration por TDD.

## Fora do escopo

- Nome, data de nascimento, foto, condição médica, endereço ou qualquer dado
  identificável.
- Timestamps de criação ou atualização.
- `EmergencyProfile`, `Bracelet`, `Parent` ou `ChildParent`.
- Relacionamentos, schemas Pydantic, repositórios, serviços e endpoints.
- Autenticação, autorização ou dados iniciais.

## Arquitetura

O modelo ficará em `app/models/child.py` e herdará de `Base`, definida em
`app/database.py`. O pacote `app.models` exportará `Child`, criando um ponto
único de importação para os modelos aprovados.

`alembic/env.py` importará `Child` por `app.models` e usará sua metadata como
`target_metadata`. Como todos os modelos herdarão da mesma `Base`, essa metadata
continuará compartilhada quando novas entidades forem aprovadas.

O UUID será produzido pela aplicação com `uuid.uuid4`. A migration criará uma
coluna UUID sem `server_default`, evitando dependência de extensões ou funções
específicas do PostgreSQL para gerar identificadores.

## Modelo de dados

Tabela `children`:

| Coluna | Tipo | Restrições |
| --- | --- | --- |
| `id` | UUID | chave primária, não nula |

Nenhuma outra coluna será criada nesta etapa.

## Migration

A revisão `0002` dependerá de `0001`.

- `upgrade`: cria `children` somente com a coluna `id` e sua chave primária.
- `downgrade`: remove a tabela `children`.

A migration não criará índices adicionais, pois a chave primária já possui o
índice necessário.

## Estratégia TDD

1. Alterar os testes para exigir `Child`, a tabela `children` e a revisão
   `0002` antes da implementação.
2. Executar os testes e confirmar falha pela ausência do modelo e da migration.
3. Implementar o modelo mínimo e registrá-lo na metadata.
4. Criar a migration `0002`.
5. Aplicar `upgrade head` no PostgreSQL local.
6. Confirmar que `children` possui exclusivamente `id` e que a revisão atual é
   `0002`.
7. Executar a suíte completa e o Ruff.

Os testes de integração continuarão usando `TEST_DATABASE_URL`. Sem essa
variável, eles serão ignorados sem impedir a execução dos testes unitários.

## Critérios de aceitação

- `Child` herda da base declarativa compartilhada.
- `Child.__tablename__` é `children`.
- A metadata registra somente a tabela de negócio `children`.
- `children.id` é UUID, chave primária e não nula.
- Uma inserção via ORM gera um UUID sem fornecê-lo manualmente.
- A migration `0002` sobe e desce sem criar outras tabelas de negócio.
- Nenhum dado pessoal, timestamp, relacionamento ou endpoint é introduzido.
- A suíte completa e o Ruff passam.

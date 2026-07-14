# Modelo físico de Bracelet

## Objetivo

Criar a representação física de uma pulseira do Pertinho com token público
aleatório, estados restritos e integridade entre vínculo e datas. Este recorte
modela somente persistência; as transições de estado serão implementadas em uma
tarefa de domínio posterior.

## Escopo aprovado

- Criar `BraceletStatus` como `StrEnum`.
- Criar o modelo SQLAlchemy `Bracelet` e a tabela `bracelets`.
- Relacionar opcionalmente `Bracelet` com `Child`.
- Gerar UUID e token público na aplicação.
- Restringir status e combinações de vínculo e datas no banco.
- Garantir unicidade de token público e criança vinculada.
- Criar a migration `0003` com upgrade e downgrade.
- Validar o modelo e as restrições reais do PostgreSQL por TDD.

## Fora do escopo

- Endpoints, schemas Pydantic, repositórios ou serviços.
- Operações de ativação, troca, perda ou resgate.
- Trigger ou evento SQLAlchemy para bloquear alteração de token.
- `EmergencyProfile`, `Parent` ou `ChildParent`.
- Dados pessoais ou sensíveis de crianças e responsáveis.
- Timestamps genéricos `created_at` ou `updated_at`.

## Estados

`BraceletStatus` terá exatamente os valores:

- `ESTOQUE`
- `ATIVA`
- `DESVINCULADA`
- `PERDIDA`

O status será persistido como `VARCHAR`, não como enum nativo do PostgreSQL.
Uma `CHECK CONSTRAINT` limitará os valores aceitos. O padrão no modelo e no
banco será `ESTOQUE`.

## Modelo de dados

Tabela `bracelets`:

| Coluna | Tipo | Restrições |
| --- | --- | --- |
| `id` | UUID | chave primária, não nula |
| `public_token` | VARCHAR(43) | único, não nulo |
| `status` | VARCHAR | não nulo, padrão `ESTOQUE`, valor validado |
| `child_id` | UUID | opcional, único, FK para `children.id` |
| `activated_at` | TIMESTAMP WITH TIME ZONE | opcional |
| `revoked_at` | TIMESTAMP WITH TIME ZONE | opcional |

`id` será gerado com `uuid.uuid4`. `public_token` será gerado com
`secrets.token_urlsafe(32)`, produzindo um token URL-safe de 43 caracteres. Não
haverá `server_default` para esses dois campos.

## Integridade de estado

Uma constraint cruzada aceitará somente estas combinações:

| Status | `child_id` | `activated_at` | `revoked_at` |
| --- | --- | --- | --- |
| `ESTOQUE` | nulo | nulo | nulo |
| `ATIVA` | preenchido | preenchido | nulo |
| `DESVINCULADA` | nulo | preenchido | preenchido |
| `PERDIDA` | nulo | preenchido | preenchido |

`child_id` terá `UNIQUE`, garantindo no máximo uma pulseira vinculada a cada
criança. A chave estrangeira não usará `CASCADE` nem `SET NULL`; qualquer
desvinculação deverá ser explícita e atômica na futura camada de domínio.

## Token público

O banco garantirá `UNIQUE` e `NOT NULL`. A imutabilidade será uma regra da
futura camada de domínio, que não oferecerá operação de alteração do token.
Este recorte não adicionará trigger nem evento ORM, evitando complexidade e
acoplamento prematuros.

## Relacionamento ORM

`Bracelet.child` será uma relação opcional com `Child`, sem cascade. Não será
adicionada uma coleção de pulseiras em `Child` neste momento, pois nenhum fluxo
aprovado precisa navegar nessa direção.

## Migration

A revisão `0003` dependerá de `0002`.

- `upgrade`: cria `bracelets`, chave estrangeira, constraints de unicidade,
  status e coerência de estado.
- `downgrade`: remove `bracelets` sem alterar `children`.

Nenhum índice adicional será criado além dos fornecidos pela chave primária e
pelas constraints `UNIQUE` de `public_token` e `child_id`.

## Estratégia TDD

1. Criar testes que exijam enum, colunas, tipos, defaults, relação e
   constraints antes da implementação.
2. Confirmar falha pela ausência de `Bracelet` e `BraceletStatus`.
3. Implementar o modelo mínimo e registrá-lo em `app.models`.
4. Alterar os testes de integração para exigir a revisão `0003` e o schema
   real.
5. Confirmar falha pela ausência da migration.
6. Criar e aplicar a migration `0003`.
7. Validar no PostgreSQL:
   - geração de UUID, token e status padrão;
   - token com 43 caracteres e tokens distintos;
   - unicidade de `public_token` e `child_id`;
   - rejeição de criança inexistente;
   - rejeição de combinações incoerentes de estado;
   - downgrade para `0002` e restauração para `0003`.
8. Executar a suíte completa e o Ruff.

Os testes de integração continuarão condicionados a `TEST_DATABASE_URL`.

## Critérios de aceitação

- `Bracelet` herda da base declarativa compartilhada.
- A metadata registra somente `children` e `bracelets` como tabelas de negócio.
- `BraceletStatus` possui exatamente os quatro estados aprovados.
- Uma nova pulseira recebe UUID, token URL-safe e status `ESTOQUE` pela
  aplicação.
- O banco aplica todas as constraints de status, coerência, FK e unicidade.
- A migration `0003` sobe e desce sem alterar a tabela `children`.
- Nenhum endpoint, serviço, trigger, outra entidade ou dado pessoal é criado.
- A suíte completa e o Ruff passam.

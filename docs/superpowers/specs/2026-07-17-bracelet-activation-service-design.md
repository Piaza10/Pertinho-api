# Design do serviço de ativação de Bracelet

## Objetivo

Implementar o primeiro caso de uso da camada de aplicação do Pertinho: a
ativação transacional de uma `Bracelet` em `ESTOQUE` para uma `Child`.

O recorte deve validar o controle de sessão, transação e concorrência no
PostgreSQL antes que o mesmo padrão seja aplicado a outras transições. Não
fazem parte desta tarefa endpoints HTTP, schemas Pydantic, migrations, novas
entidades ou outras transições de `Bracelet`.

## Arquitetura

O caso de uso ficará em `app/services/bracelet_activation.py`, separado do
modelo ORM e do FastAPI. A interface assíncrona receberá:

- uma `AsyncSession` sem transação ativa;
- o UUID interno da pulseira;
- o UUID interno da criança.

O serviço controlará a transação com `async with session.begin()`. A sessão
continuará pertencendo ao chamador e não será fechada pelo serviço.

## Fluxo de ativação

Dentro de uma única transação, o serviço deve:

1. buscar e bloquear a linha de `Child` com `SELECT ... FOR UPDATE`;
2. buscar e bloquear a linha de `Bracelet` com `SELECT ... FOR UPDATE`;
3. produzir erro neutro se qualquer um dos recursos não existir;
4. verificar se a criança já possui outra pulseira vinculada;
5. gerar o instante atual em UTC dentro do serviço;
6. chamar `bracelet.ativar(child, instante)` para reutilizar as invariantes do
   domínio;
7. executar `flush` para materializar o DML e validar as constraints antes do
   commit;
8. concluir a transação e retornar a entidade `Bracelet` ativada.

O bloqueio da criança vem antes do bloqueio da pulseira em todas as execuções.
Essa ordem serializa ativações concorrentes para a mesma criança e reduz o
risco de deadlock. A unicidade existente de `Bracelet.child_id` permanece como
barreira final de integridade.

## Concorrência

Duas ativações simultâneas para a mesma criança devem usar sessões distintas.
A primeira transação que obtiver o bloqueio poderá concluir. Depois de adquirir
o mesmo bloqueio, a segunda deve observar o vínculo já persistido e terminar
com `ConflitoAtivacaoBracelet`.

O resultado persistido deve conter exatamente uma pulseira vinculada à
criança. A pulseira da tentativa rejeitada deve permanecer em `ESTOQUE`, sem
datas ou vínculo parcial.

## Instante de ativação

O serviço deve gerar `activated_at` em UTC. O instante não faz parte dos
argumentos do caso de uso e, futuramente, não será aceito de um cliente HTTP.
Isso impede que uma entrada externa controle datas internas de auditoria.

## Contrato de erros

### `RecursoAtivacaoNaoEncontrado`

Representa tanto pulseira inexistente quanto criança inexistente. A mensagem
deve ser única e neutra, sem revelar qual recurso faltou e sem conter UUIDs.

### `ConflitoAtivacaoBracelet`

Representa uma criança que já está vinculada a outra pulseira. A mensagem não
deve conter UUIDs ou dados pessoais.

### Erros de domínio e infraestrutura

`TransicaoBraceletInvalida` permanece sendo gerada pelo modelo quando a
pulseira não está em `ESTOQUE`. Erros inesperados de infraestrutura não serão
convertidos em erros de negócio genéricos.

As duas exceções de aplicação ficarão no mesmo módulo do serviço neste primeiro
recorte. Uma hierarquia compartilhada só será considerada quando houver mais
casos de uso que comprovem essa necessidade.

## Atomicidade e rollback

O contexto transacional deve executar commit somente depois de `flush`
bem-sucedido. Recurso ausente, conflito, transição inválida ou falha de banco
devem encerrar a transação com rollback automático.

Depois de qualquer erro esperado, uma nova consulta deve encontrar o mesmo
estado persistido anterior à tentativa. O serviço não deve realizar `commit`
ou `rollback` fora do contexto transacional.

## Estratégia de testes

O desenvolvimento seguirá TDD com PostgreSQL real. Os testes devem comprovar:

- ativação válida persistida com `status`, `child_id` e instante UTC;
- instante criado pelo serviço, sem argumento externo;
- mesma exceção neutra para pulseira ou criança inexistente;
- conflito quando a criança já está vinculada, sem mutação parcial;
- preservação de `TransicaoBraceletInvalida` para pulseira fora de `ESTOQUE`;
- duas ativações concorrentes com exatamente uma vencedora;
- rollback observado por uma nova sessão depois de cada erro esperado;
- ausência de UUIDs e dados pessoais nas mensagens das exceções.

Os testes do serviço serão condicionados a `TEST_DATABASE_URL`, seguindo o
padrão de integração existente. A verificação final executará toda a suíte com
o PostgreSQL local, Ruff, `alembic check`, `alembic current` e
`git diff --check`.

## Limites do recorte

Esta tarefa não deve criar ou alterar:

- endpoints ou dependências FastAPI;
- schemas de entrada ou saída;
- migrations ou estrutura do banco;
- modelos ou entidades;
- serviços de desvinculação ou perda;
- autenticação, autorização ou dados pessoais;
- eventos, mensageria, Redis ou Celery.

Qualquer tratamento HTTP, verificação de permissão do responsável ou novo
caso de uso exige um recorte técnico separado e aprovado.

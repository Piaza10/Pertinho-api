# Design do serviço de perda de Bracelet

## Objetivo

Implementar o caso de uso transacional que marca uma `Bracelet` ativa como
perdida. O serviço deve remover o vínculo com a criança, preservar o instante de
ativação e registrar a revogação em UTC, reutilizando a transição de domínio já
existente.

O recorte valida revalidação sob lock, atomicidade e concorrência sem criar
endpoint, schema, migration, modelo, autorização ou fluxo de troca planejada.

## Interface

O caso de uso ficará em `app/services/bracelet_loss.py` com a interface:

```python
async def marcar_bracelet_como_perdida(
    sessao: AsyncSession,
    bracelet_id: UUID,
) -> Bracelet:
    ...
```

A sessão deve chegar sem transação ativa. O serviço controlará a transação,
mas não fechará a sessão pertencente ao chamador.

O caso de uso recebe somente o identificador interno da pulseira. O chamador
não precisa conhecer nem fornecer `child_id` ou um instante de revogação.

## Fluxo transacional

Dentro de `async with sessao.begin()`, o serviço deve:

1. fazer uma pré-leitura somente de `Bracelet.status` e `Bracelet.child_id`;
2. produzir erro neutro se a pulseira não existir;
3. se a pré-leitura possuir `child_id`, bloquear primeiro a linha de `Child`;
4. bloquear e reler a entidade `Bracelet`;
5. produzir erro neutro se a criança ou a pulseira desaparecer durante a
   operação;
6. revalidar o estado e o vínculo usando a entidade sob lock;
7. gerar o instante atual em UTC;
8. chamar `bracelet.marcar_como_perdida(instante)`;
9. executar `flush` antes de concluir a transação;
10. retornar a entidade `Bracelet` depois do commit.

A pré-leitura deve selecionar colunas, não a entidade ORM. Isso evita inserir
uma instância desatualizada no identity map antes da releitura com lock.

## Ordem de locks

Quando a pré-leitura indicar vínculo, a ordem obrigatória é:

1. `Child` com `SELECT ... FOR UPDATE`;
2. `Bracelet` com `SELECT ... FOR UPDATE`.

Essa é a mesma ordem global adotada pelo serviço de ativação e deve ser
preservada nos casos de uso futuros para reduzir risco de deadlock.

Se a pré-leitura indicar ausência de vínculo, o serviço bloqueará somente a
`Bracelet`. Nesse caminho não existe uma linha de `Child` relacionada a
bloquear, e o domínio rejeitará estados diferentes de `ATIVA`.

## Revalidação

A pré-leitura serve somente para descobrir qual linha de `Child` deve ser
bloqueada. Nenhuma decisão final pode depender exclusivamente dela.

Depois dos locks:

- `Bracelet` inexistente produz `RecursoPerdaNaoEncontrado`;
- estado diferente de `ATIVA` é delegado ao método de domínio e produz
  `TransicaoBraceletInvalida`;
- pulseira ainda ativa, mas com `child_id` diferente da pré-leitura, produz
  `ConflitoPerdaBracelet`;
- estado ativo com o mesmo `child_id` pode prosseguir para a transição.

O conflito de vínculo impede que o serviço opere sobre uma criança cuja linha
não foi bloqueada.

## Instante de revogação

O serviço gerará `revoked_at` com o relógio interno em UTC. O instante não faz
parte da interface e não será controlado por uma futura entrada HTTP.

O método de domínio continuará responsável por validar fuso horário, existência
de `activated_at` e ordem temporal.

## Contrato de erros

### `RecursoPerdaNaoEncontrado`

Representa pulseira inexistente ou inconsistência em que a criança vinculada
não pode ser encontrada. A mensagem deve ser única e neutra, sem indicar qual
recurso faltou e sem conter UUID, token ou dado pessoal.

### `ConflitoPerdaBracelet`

Representa mudança do `child_id` entre a pré-leitura e a releitura sob lock. A
mensagem deve ser neutra e não expor os identificadores envolvidos.

### `TransicaoBraceletInvalida`

Permanece sendo produzida pelo modelo para `ESTOQUE`, `DESVINCULADA` e
`PERDIDA`. O serviço não deve capturar nem substituir essa exceção.

Erros inesperados do PostgreSQL não serão mascarados como erros de negócio.
As exceções de aplicação ficarão no mesmo módulo do serviço neste recorte.

## Atomicidade

O contexto transacional executará commit somente depois de `flush`
bem-sucedido. Recurso ausente, conflito, transição inválida ou falha de banco
devem causar rollback automático.

Depois de qualquer erro esperado, uma nova sessão deve observar o estado
persistido anterior à tentativa. O serviço não deve executar `commit`,
`rollback` ou fechamento de sessão fora do contexto transacional.

## Concorrência

Duas tentativas simultâneas de marcar a mesma pulseira como perdida devem usar
sessões distintas. Uma transação concluirá a mudança para `PERDIDA`; a outra,
depois de adquirir os locks, encontrará um estado final e receberá
`TransicaoBraceletInvalida`.

O estado persistido final deve ter `status = PERDIDA`, `child_id` nulo,
`activated_at` preservado e `revoked_at` preenchido uma única vez.

Uma mudança concorrente de `child_id` depois da pré-leitura deve produzir
`ConflitoPerdaBracelet`, sem aplicar a perda. Esse cenário será controlado no
teste mantendo a criança original bloqueada, observando a espera real do
serviço e alterando o vínculo em outra transação antes de liberar o lock.

## Estratégia de testes

O desenvolvimento seguirá TDD com PostgreSQL real. Os testes devem comprovar:

- perda válida persistida com remoção de vínculo, preservação de ativação e
  revogação UTC gerada pelo serviço;
- erro neutro para pulseira inexistente;
- preservação de `TransicaoBraceletInvalida` e rollback para `ESTOQUE`,
  `DESVINCULADA` e `PERDIDA`;
- SQL real com lock de `Child` antes de `Bracelet` no caminho ativo;
- duas perdas simultâneas com uma conclusão e uma transição inválida;
- conflito quando `child_id` muda entre pré-leitura e locks;
- mensagens de aplicação sem UUIDs, tokens ou dados pessoais;
- estado persistido verificado por nova sessão depois dos erros;
- cancelamento e coleta de todas as `asyncio.Task` antes da limpeza do banco.

Os testes serão condicionados a `TEST_DATABASE_URL` e seguirão o isolamento
existente em `tests/conftest.py`. A verificação final executará a suíte completa,
Ruff, `alembic check`, `alembic current` e `git diff --check`.

## Limites do recorte

Esta tarefa não deve criar ou alterar:

- endpoints, dependências FastAPI ou schemas;
- migrations, tabelas, constraints ou modelos;
- serviço de desvinculação ou troca planejada;
- autenticação, autorização ou dados pessoais;
- eventos, mensageria, Redis ou Celery;
- o comportamento do serviço de ativação.

Qualquer integração HTTP, verificação de permissão, troca de pulseira ou
novo caso de uso exige recorte separado e aprovado.

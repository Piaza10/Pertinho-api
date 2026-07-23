# Design do serviço de troca planejada de Bracelet

## Objetivo

Implementar um serviço de aplicação assíncrono que substitui uma `Bracelet`
ativa por uma nova `Bracelet` em estoque para a mesma `Child`.

A operação deve ser atômica: a pulseira anterior passa para
`DESVINCULADA`, perde o vínculo, e a nova passa para `ATIVA` com o mesmo
vínculo. Qualquer falha reverte as duas mudanças.

O recorte contém somente o serviço transacional interno e testes de integração
com PostgreSQL. Não inclui endpoint, schema HTTP, autorização, migration,
modelo novo ou alteração dos serviços existentes.

## Interface

O serviço será criado em `app/services/bracelet_replacement.py`:

```python
async def trocar_bracelet(
    sessao: AsyncSession,
    bracelet_anterior_id: UUID,
    bracelet_nova_id: UUID,
) -> tuple[Bracelet, Bracelet]:
```

O retorno preserva a ordem dos argumentos: primeiro a pulseira anterior já
desvinculada, depois a nova pulseira ativa.

O chamador fornece uma `AsyncSession` limpa, sem transação ativa. O serviço
controla a transação, mas não fecha a sessão.

Somente os dois UUIDs das pulseiras são recebidos. A `Child` é derivada do
vínculo da pulseira anterior, evitando um terceiro identificador que poderia
divergir do estado persistido.

## Validação anterior à transação

Os UUIDs devem ser diferentes. Quando forem iguais, o serviço levanta
`BraceletsTrocaIguais` antes de abrir a transação.

A mensagem será estática:

```text
As pulseiras da troca devem ser distintas
```

Ela não contém UUID, token ou dado pessoal.

## Fluxo transacional

Dentro de uma única transação, o serviço executa:

1. Pré-leitura somente de `Bracelet.status` e `Bracelet.child_id` da pulseira
   anterior, sem carregar uma entidade no mapa de identidade.
2. Se a pulseira anterior não existir, levanta
   `RecursoTrocaNaoEncontrado`.
3. Se o `child_id` inicial estiver preenchido, bloqueia a `Child` com
   `SELECT ... FOR UPDATE`.
4. Bloqueia individualmente as duas pulseiras, em ordem crescente de UUID.
5. Confirma a existência da `Child`, da pulseira anterior e da nova pulseira.
6. Compara o `child_id` relido sob lock com o valor da pré-leitura.
7. Gera um único instante com `datetime.now(UTC)`.
8. Chama `bracelet_anterior.desvincular(instante)`.
9. Executa o primeiro `flush`.
10. Chama `bracelet_nova.ativar(child, instante)`.
11. Executa o segundo `flush`.
12. Confirma a transação e retorna `(bracelet_anterior, bracelet_nova)`.

O caminho válido sempre possui a ordem global:

```text
Child → Bracelet de menor UUID → Bracelet de maior UUID
```

Nos caminhos em que a pulseira anterior não possui vínculo, não há `Child`
para bloquear. As duas pulseiras ainda são bloqueadas na ordem crescente, e a
entidade de domínio rejeita o estado inválido.

## Dois flushes e atomicidade

`Bracelet.child_id` possui unicidade não adiável. Por isso, o vínculo antigo
deve ser removido no PostgreSQL antes que o mesmo `child_id` seja atribuído à
nova pulseira.

O primeiro `flush` persiste a desvinculação dentro da transação. O segundo
persiste a ativação. Nenhum estado intermediário fica visível para outras
transações.

Se a ativação da nova pulseira ou o segundo `flush` falhar, o rollback também
desfaz o primeiro `flush`. A troca nunca pode terminar com somente uma das
transições confirmada.

## Revalidação e concorrência

Após adquirir os locks, o serviço compara o `child_id` atual da pulseira
anterior com o valor obtido na pré-leitura.

Qualquer mudança, inclusive para `NULL`, produz
`ConflitoTrocaBracelet` com a mensagem:

```text
Vínculo da pulseira anterior mudou durante a operação
```

Nenhuma das pulseiras é alterada nesse cenário.

O lock da `Child` serializa a troca com ativações, perdas e outras trocas que
envolvam a mesma criança. A ordenação dos dois UUIDs evita inversão dos locks
entre operações concorrentes sobre o mesmo par de pulseiras.

Duas trocas simultâneas iniciadas a partir da mesma pulseira anterior não
podem concluir ambas. Uma pode confirmar; a outra deve observar conflito de
vínculo ou transição de domínio inválida, sem alteração parcial.

## Erros

### `RecursoTrocaNaoEncontrado`

Usado quando a pulseira anterior, a pulseira nova ou a `Child` referenciada
não existe.

Mensagem:

```text
Recurso de troca não encontrado
```

A mensagem única não revela qual recurso está ausente.

### `BraceletsTrocaIguais`

Usado quando os dois UUIDs de entrada são iguais.

Mensagem:

```text
As pulseiras da troca devem ser distintas
```

### `ConflitoTrocaBracelet`

Usado quando o vínculo da pulseira anterior muda entre a pré-leitura e a
revalidação sob lock.

Mensagem:

```text
Vínculo da pulseira anterior mudou durante a operação
```

### Erros de domínio preservados

O serviço não converte:

- `TransicaoBraceletInvalida`, quando a pulseira anterior não está `ATIVA` ou
  a nova não está `ESTOQUE`;
- `InstanteBraceletInvalido`, se uma invariável temporal de domínio falhar.

Falhas inesperadas do PostgreSQL também são propagadas após o rollback
automático da transação.

Nenhuma exceção nova inclui UUID, token público ou dado pessoal.

## Instante da troca

O serviço gera internamente um único instante UTC.

Esse mesmo valor é usado em:

- `bracelet_anterior.revoked_at`;
- `bracelet_nova.activated_at`.

Assim, a troca possui uma única referência temporal e o chamador não controla
datas internas da operação.

## Estratégia de testes

Os testes serão criados em `tests/test_bracelet_replacement_service.py` e
usarão PostgreSQL real por `TEST_DATABASE_URL`.

O ciclo será TDD: cada comportamento começa com um teste que falha pelo motivo
esperado, seguido da implementação mínima e da confirmação do estado verde.

### Casos funcionais

- troca válida com persistência das duas pulseiras;
- retorno na ordem `(anterior, nova)`;
- mesmo instante UTC em `revoked_at` e `activated_at`;
- preservação do `activated_at` original da pulseira anterior;
- liberação da unicidade de `child_id` entre os dois `flushes`;
- UUIDs iguais;
- pulseira anterior ausente;
- pulseira nova ausente;
- estados inválidos da pulseira anterior;
- estados inválidos da pulseira nova;
- rollback integral quando a segunda transição falha;
- sessão reutilizável depois de sucesso e depois de erro esperado;
- mensagens sem UUID, token ou dados pessoais.

### Casos de locks e concorrência

- prova da ordem SQL `Child → Bracelet menor → Bracelet maior`;
- duas trocas simultâneas a partir da mesma pulseira anterior;
- mudança controlada do `child_id` entre pré-leitura e locks;
- estado final consistente após cada conflito;
- cancelamento e coleta de todas as tarefas antes da limpeza;
- timeout defensivo em esperas concorrentes para evitar suíte suspensa.

Os testes concorrentes devem controlar o interleaving por estado observável do
PostgreSQL, não por sleeps arbitrários.

### Verificações finais

- suíte completa com `pertinho_test`;
- Ruff global;
- `alembic check` sem novas operações;
- Alembic em `0003 (head)`;
- revisão do escopo e da árvore Git.

O banco de desenvolvimento `pertinho` nunca será usado pelos testes ou pelas
verificações de migration.

## Arquivos previstos

- Criar `app/services/bracelet_replacement.py`.
- Criar `tests/test_bracelet_replacement_service.py`.
- Atualizar `docs/PROJECT_CONTEXT.md` somente após a implementação e todas as
  verificações serem aprovadas.
- Criar o plano de implementação depois da revisão desta especificação.

## Fora do escopo

- endpoint ou schema HTTP;
- autenticação ou autorização;
- migration ou alteração de schema;
- alteração de `Child`, `Bracelet` ou outros modelos;
- modificação dos serviços de ativação e perda;
- `EmergencyProfile`, `Parent` ou `ChildParent`;
- dados adicionais de menores;
- eventos, notificações, Redis ou Celery;
- alteração ou reutilização de token público;
- reativação de pulseiras `DESVINCULADA` ou `PERDIDA`;
- troca iniciada a partir de pulseira perdida;
- front-end ou página pública.

Qualquer integração HTTP, regra de permissão ou ampliação do modelo exige um
novo recorte técnico aprovado.

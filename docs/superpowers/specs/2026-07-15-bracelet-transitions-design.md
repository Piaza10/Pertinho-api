# Transições de domínio de Bracelet

## Objetivo

Adicionar comportamento de domínio à entidade `Bracelet` para executar as
transições de estado aprovadas, mantendo vínculo e datas coerentes antes da
persistência. Este recorte não cria camada HTTP nem antecipa serviços de
aplicação.

## Escopo aprovado

- Implementar `Bracelet.ativar`.
- Implementar `Bracelet.desvincular`.
- Implementar `Bracelet.marcar_como_perdida`.
- Aceitar somente as transições previstas no fluxo do MVP.
- Exigir timestamps conscientes de fuso horário.
- Rejeitar revogação anterior à ativação.
- Garantir que uma validação malsucedida não altere parcialmente a entidade.
- Criar exceções de domínio específicas para estado ou instante inválido.
- Validar o comportamento em memória e sua persistência no PostgreSQL por TDD.

## Fora do escopo

- Endpoints, schemas Pydantic, dependências FastAPI ou respostas HTTP.
- Serviços de aplicação, repositórios ou Unit of Work.
- Autenticação, autorização ou identificação do responsável.
- Criação ou seleção de `Child`.
- Operações de resgate ou consulta por token público.
- `EmergencyProfile`, `Parent`, `ChildParent` ou qualquer nova entidade.
- Nova migration ou alteração do schema existente.
- Eventos, notificações, geolocalização ou auditoria.

## Abordagem arquitetural

As regras ficarão em métodos da própria entidade ORM `Bracelet`. Essa escolha
mantém os invariantes junto do estado que protegem e evita uma abstração de
serviço prematura. As constraints existentes no PostgreSQL continuam como uma
segunda camada de defesa.

Os métodos alteram somente o objeto em memória. Eles não criam sessão, não
consultam o banco e não executam `flush` ou `commit`. A futura camada de
aplicação será responsável por carregar as entidades e controlar a transação.

Triggers e funções PostgreSQL não serão usados. O banco protege combinações de
campos, enquanto as transições e mensagens de erro permanecem testáveis no
domínio Python.

## API de domínio

As interfaces serão:

```python
class TransicaoBraceletInvalida(ValueError): ...


class InstanteBraceletInvalido(ValueError): ...


class Bracelet(Base):
    def ativar(self, child: Child, instante: datetime) -> None: ...

    def desvincular(self, instante: datetime) -> None: ...

    def marcar_como_perdida(self, instante: datetime) -> None: ...
```

As exceções serão exportadas por `app.models` junto de `Bracelet` e
`BraceletStatus`. Suas mensagens poderão mencionar somente os estados e a
regra temporal violada; não incluirão UUID, token público ou dados de criança.

## Regras de transição

### Ativação

`ativar(child, instante)` aceita somente uma pulseira em `ESTOQUE`.

Após sucesso:

- `status` passa para `ATIVA`;
- `child` recebe a criança informada;
- `child_id` será sincronizado pelo relacionamento ORM;
- `activated_at` recebe o instante informado;
- `revoked_at` permanece nulo.

O argumento `child` é obrigatório e deve ser uma instância de `Child`.

### Desvinculação

`desvincular(instante)` aceita somente uma pulseira em `ATIVA`.

Após sucesso:

- `status` passa para `DESVINCULADA`;
- `child` e `child_id` ficam nulos;
- `activated_at` é preservado;
- `revoked_at` recebe o instante informado.

### Perda

`marcar_como_perdida(instante)` aceita somente uma pulseira em `ATIVA`.

Após sucesso:

- `status` passa para `PERDIDA`;
- `child` e `child_id` ficam nulos;
- `activated_at` é preservado;
- `revoked_at` recebe o instante informado.

`DESVINCULADA` e `PERDIDA` continuam estados finais. Nenhum método permite
reativação, troca direta entre estados finais ou retorno a `ESTOQUE`.

## Validação temporal

Todo instante deve possuir `tzinfo` e `utcoffset()` diferente de `None`.
Valores ingênuos serão rejeitados com `InstanteBraceletInvalido`.

Desvinculação e perda também exigem que o instante seja igual ou posterior a
`activated_at`. Um instante anterior será rejeitado com a mesma exceção. A
camada de aplicação futura fornecerá normalmente `datetime.now(UTC)`, mas o
domínio aceitará qualquer fuso horário válido.

Se uma pulseira em `ATIVA` não possuir `activated_at`, a operação será
rejeitada como instante inválido. Isso protege o domínio contra objetos
inconsistentes criados em memória antes que as constraints do banco atuem.

## Atomicidade em memória

Cada método executará todas as validações antes da primeira atribuição. Se uma
exceção for levantada, `status`, vínculo, `activated_at` e `revoked_at`
permanecerão exatamente como estavam.

A ordem será determinística: primeiro o estado de origem, depois os argumentos
obrigatórios da operação e por último as regras temporais. Assim, uma operação
partindo de estado proibido sempre produzirá `TransicaoBraceletInvalida`, mesmo
se também receber argumentos inválidos.

A atomicidade de persistência será responsabilidade da futura camada de
aplicação, por meio de uma única transação SQLAlchemy. Este recorte não define
essa camada.

## Erros

`TransicaoBraceletInvalida` será usada quando o estado atual não permitir o
estado solicitado. A exceção registrará apenas `origem` e `destino` como
`BraceletStatus`, permitindo tratamento tipado sem expor identificadores.

`InstanteBraceletInvalido` será usada para timestamp sem fuso, ausência de
`activated_at` numa revogação ou revogação anterior à ativação.

Um `child` ausente ou de tipo diferente de `Child` será rejeitado com
`TypeError`, antes de qualquer mutação. O contrato tipado continua sendo
`child: Child`.

## Persistência

O fluxo futuro de uso será:

1. Abrir uma `AsyncSession`.
2. Carregar `Bracelet` e, na ativação, `Child` na mesma sessão.
3. Chamar o método de domínio com um instante consciente de fuso.
4. Executar `flush` e `commit` na camada de aplicação.
5. Permitir que as constraints do PostgreSQL validem o estado final.

Os métodos não capturam `IntegrityError`. Erros de concorrência ou violações
do banco pertencem à futura camada transacional.

## Estratégia TDD

1. Criar testes unitários para as transições válidas antes da implementação.
2. Confirmar falha porque os métodos ainda não existem.
3. Implementar o comportamento mínimo para ativação, desvinculação e perda.
4. Criar testes para estados de origem inválidos e estados finais.
5. Confirmar que as falhas não modificam a entidade.
6. Criar testes para timestamp ingênuo, ausência de ativação e ordem temporal
   inválida.
7. Criar testes de integração que façam `flush` dos três estados resultantes
   produzidos pelos métodos.
8. Executar a suíte completa, Ruff, `alembic check` e confirmar o head `0003`.

Os testes de integração continuarão condicionados a `TEST_DATABASE_URL`.

## Critérios de aceitação

- Somente `ESTOQUE → ATIVA`, `ATIVA → DESVINCULADA` e `ATIVA → PERDIDA` são
  aceitas.
- As três transições produzem combinações compatíveis com as constraints do
  PostgreSQL.
- Timestamps sem fuso e revogações anteriores à ativação são rejeitados.
- Estados finais não aceitam novas transições.
- Nenhum erro deixa o objeto parcialmente modificado.
- Os métodos não acessam sessão nem controlam transação.
- Exceções não expõem UUID, token ou dados pessoais.
- Nenhuma migration, endpoint, serviço ou nova entidade é criada.
- A suíte completa, Ruff e a verificação de metadata do Alembic passam.

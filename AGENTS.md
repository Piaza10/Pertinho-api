# Orientações para agentes

## Leitura obrigatória

- Antes de propor ou implementar qualquer tarefa, leia integralmente
  `docs/PROJECT_CONTEXT.md`.
- Trate `docs/PROJECT_CONTEXT.md` como a fonte de verdade do produto, da
  arquitetura, das decisões aprovadas e do estado atual do projeto.

## Fluxo obrigatório de trabalho

- Trabalhe incrementalmente, uma tarefa pequena e verificável por vez.
- Antes de cada tarefa nova, apresente o recorte técnico e aguarde aprovação
  explícita.
- Nunca gere ou implemente o sistema inteiro de uma vez.
- Não amplie o escopo aprovado, mesmo quando uma funcionalidade adjacente
  parecer útil.
- Ao concluir uma tarefa, execute as verificações pertinentes, apresente os
  arquivos alterados e pare para aguardar nova aprovação.
- Priorize simplicidade, baixo custo, segurança, LGPD e manutenção fácil.

## Limites de escopo

- Não implemente dados de menores, banco de dados, autenticação, notificações,
  Docker adicional ou front-end fora de uma tarefa específica e aprovada.
- Não antecipe modelos, migrations, endpoints de negócio, integrações ou
  infraestrutura de etapas futuras.
- Preserve a separação entre perfil público de emergência, dados privados e
  dados internos definida no contexto mestre.
- Nunca exponha telefone, e-mail, endereço ou nome completo de uma criança ou
  responsável em uma leitura pública de NFC ou QR Code.

## Manutenção da documentação

- Atualize `docs/PROJECT_CONTEXT.md` somente quando uma decisão de produto ou
  arquitetura tiver sido explicitamente aprovada.
- Registre decisões aprovadas sem reescrever o histórico como se recursos ainda
  não implementados já estivessem concluídos.
- Em caso de divergência entre a implementação e o contexto documentado, pare,
  apresente a divergência e solicite orientação antes de alterar o sistema.

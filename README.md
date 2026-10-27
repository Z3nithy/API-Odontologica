# Zen API

API de apoio à gestão de uma clínica odontológica. Ela oferece autenticação e recursos para
recepção, gestores e dentistas. Os dados são organizados por clínica, e cada perfil só pode
acessar as operações permitidas para sua função.

> **Importante:** este projeto é uma API de aplicação, não um sistema clínico completo. Consulte
> [O que ainda não está disponível](#o-que-ainda-não-está-disponível) antes de usar em produção.

## Índice

- [O que a API oferece](#o-que-a-api-oferece)
- [Tecnologias](#tecnologias)
- [Começar](#começar)
- [Executar e explorar](#executar-e-explorar)
- [Criar o primeiro usuário](#criar-o-primeiro-usuário)
- [Rotas da API](#rotas-da-api)
- [Regras importantes](#regras-importantes)
- [O que ainda não está disponível](#o-que-ainda-não-está-disponível)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Publicar no GitHub](#publicar-no-github)

## O que a API oferece

- Login com token JWT e alteração de senha.
- Cadastro e organização de pacientes e consultas.
- Agenda, disponibilidade, check-in e painel da recepção.
- Gestão de usuários, produtividade e indicadores para gestores.
- Área da dentista com agenda, histórico, odontograma e planos de tratamento.
- Rascunhos de documentos clínicos e histórico de alterações.
- Preferências pessoais e de notificações.
- Isolamento de dados por clínica e permissões conforme o perfil.

## Tecnologias

| Tecnologia | Uso |
| --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/) | Aplicação web, validação e documentação interativa |
| [Uvicorn](https://www.uvicorn.org/) | Servidor da API |
| [SQLAlchemy](https://www.sqlalchemy.org/) | Acesso ao banco de dados |
| [Pydantic](https://docs.pydantic.dev/) | Validação dos dados de entrada e saída |
| [python-jose](https://python-jose.readthedocs.io/) | Criação e validação de tokens JWT |
| [pwdlib](https://frankie567.github.io/pwdlib/) | Hash de senhas |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | Leitura das configurações locais |

## Começar

### Requisitos

- Python instalado.
- Um terminal, como PowerShell no Windows ou Bash no Linux/macOS.

### 1. Abrir a pasta do backend

Execute os próximos comandos dentro da pasta `backend` do projeto.

### 2. Criar e ativar um ambiente virtual

O ambiente virtual mantém as dependências deste projeto separadas das demais instalações Python.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux ou macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar as dependências

```bash
python -m pip install -r requirements.txt
```

### 4. Criar o arquivo de configuração

Copie o modelo `.env.example` para um arquivo chamado `.env`.

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**Linux ou macOS:**

```bash
cp .env.example .env
```

Gere uma chave secreta aleatória:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Abra o `.env`, cole o resultado após `SECRET_KEY=` e confira as demais configurações:

```env
DATABASE_URL=sqlite:///./database.db
SECRET_KEY=cole-a-chave-aleatoria-aqui
ALGORITHM=HS256
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CLINIC_OPEN_TIME=08:00
CLINIC_CLOSE_TIME=18:00
```

`SECRET_KEY` é obrigatória: sem ela, a API não inicia. Use uma chave diferente para cada ambiente
e nunca compartilhe o arquivo `.env`. `CORS_ORIGINS` deve listar os endereços autorizados do
frontend. Os horários definem o expediente usado na consulta de disponibilidade.

Por padrão, a API usa SQLite e cria o arquivo `database.db` localmente. Para outro banco, configure
`DATABASE_URL` com uma URL compatível com o SQLAlchemy e instale o driver correspondente.

## Executar e explorar

Com o ambiente virtual ativado, inicie o servidor na pasta `backend`:

```bash
uvicorn main:app --reload
```

O modo `--reload` reinicia o servidor quando o código muda; use-o durante o desenvolvimento.

| Endereço | O que você encontra |
| --- | --- |
| <http://127.0.0.1:8000> | Servidor local |
| <http://127.0.0.1:8000/docs> | Documentação interativa (Swagger UI) |
| <http://127.0.0.1:8000/redoc> | Documentação alternativa (ReDoc) |
| <http://127.0.0.1:8000/api/health> | Verificação simples de disponibilidade |

Na página `/docs`, você pode consultar os formatos das requisições e respostas e testar as rotas.
As rotas protegidas exigem um token de acesso.

### Conectar um frontend

No desenvolvimento, o proxy do Vite encaminha as chamadas `/api` para `http://127.0.0.1:8000`.
Em produção, configure `VITE_API_BASE_URL` ou um reverse proxy para apontar para a API e ajuste
`CORS_ORIGINS` com o endereço do frontend.

## Criar o primeiro usuário

Não há cadastro público de usuários. Crie localmente uma clínica e o primeiro usuário gestor com
o script administrativo:

```bash
python -m scripts.create_user --clinic "Minha clínica" --name "Nome da pessoa" --email "pessoa@clinica.com" --role manager
```

O script pede a senha sem exibi-la e exige no mínimo 12 caracteres. Ao aceitar convites para novas
contas, a senha também deve conter uma letra maiúscula, uma minúscula e um número.

Os perfis aceitos são:

| Perfil | Acesso principal |
| --- | --- |
| `manager` | Gestão da equipe, pacientes e indicadores da clínica |
| `receptionist` | Cadastro de pacientes e organização da agenda |
| `dentist` | Agenda própria, odontograma e recursos clínicos disponíveis |

Depois de iniciar a API, o gestor pode criar contas de dentistas e recepcionistas pela rota de
gestão de equipe. A pessoa convidada define sua própria senha ao aceitar o convite.

## Rotas da API

Todas as rotas começam com `/api`. Os campos obrigatórios, filtros e formatos de resposta podem
ser consultados em `/docs`.

### Autenticação e conta

| Método | Rota | O que faz |
| --- | --- | --- |
| `POST` | `/auth/login` | Inicia sessão com e-mail e senha e retorna um token |
| `GET` | `/auth/me` | Consulta o perfil autenticado |
| `PATCH` | `/auth/me` | Altera o nome do perfil autenticado |
| `POST` | `/auth/change-password` | Altera a senha após validar a senha atual |
| `GET` | `/auth/me/preferences` | Consulta preferências pessoais |
| `PUT` | `/auth/me/preferences` | Salva preferências de aparência, acessibilidade e navegação |
| `DELETE` | `/auth/me/preferences` | Remove personalizações e restaura os padrões do perfil |

Depois de fazer login, envie o token nas chamadas protegidas:

```http
Authorization: Bearer <access_token>
```

O token de acesso expira após 60 minutos.

### Recepção

Estas rotas exigem o perfil `receptionist` ou `manager`.

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/reception/dashboard` | Exibe indicadores e resumo diário da recepção |
| `GET` | `/reception/patients` | Pesquisa pacientes por nome, telefone ou CPF |
| `GET` | `/reception/patients/registry` | Lista pacientes com filtros, indicadores e paginação |
| `POST` | `/reception/patients` | Cadastra um paciente |
| `PATCH` | `/reception/patients/{patient_id}` | Atualiza os dados administrativos do paciente |
| `GET` | `/reception/patients/{patient_id}/appointments` | Consulta o histórico administrativo de consultas |
| `GET` | `/reception/dentists` | Lista dentistas ativos da clínica |
| `GET` | `/reception/availability` | Consulta horários disponíveis |
| `GET` | `/reception/appointments` | Lista consultas por data ou período, com filtros |
| `POST` | `/reception/appointments` | Cria uma consulta |
| `PATCH` | `/reception/appointments/{appointment_id}` | Atualiza uma consulta ou seu status |
| `POST` | `/reception/appointments/{appointment_id}/check-in` | Registra a chegada do paciente uma única vez |
| `GET` | `/reception/notification-preferences` | Consulta preferências pessoais de notificação |
| `PUT` | `/reception/notification-preferences` | Salva preferências pessoais de notificação |

### Gestão de equipe

As operações de gestão exigem o perfil `manager` e ficam limitadas à clínica do gestor. Aceitar
um convite é uma operação pública que exige o token de uso único.

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/manager/users` | Lista usuários da equipe com filtros e paginação |
| `GET` | `/manager/users/{user_id}` | Consulta dados administrativos e auditoria de um usuário |
| `POST` | `/manager/users` | Cria uma conta inativa e emite um convite de primeiro acesso |
| `PATCH` | `/manager/users/{user_id}` | Atualiza o nome de um usuário |
| `PATCH` | `/manager/users/{user_id}/status` | Ativa ou desativa uma conta |
| `POST` | `/manager/users/{user_id}/invitation/resend` | Gera um novo convite e invalida o anterior |
| `POST` | `/manager/users/invitation/accept` | Aceita um convite e define a senha da conta |

O convite expira após 48 horas. O token é exibido uma única vez para compartilhamento manual; não
há envio automático de e-mail. Usuários com consultas futuras não podem ser desativados.

### Gestão de pacientes e produtividade

Estas rotas exigem o perfil `manager` e mostram dados da clínica do gestor.

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/manager/patients` | Lista pacientes com filtros administrativos, indicadores e paginação |
| `GET` | `/manager/patients/{patient_id}` | Consulta dados administrativos mínimos de um paciente |
| `GET` | `/manager/productivity` | Consulta indicadores por profissional, série temporal e comparação de períodos |
| `GET` | `/manager/productivity/records` | Lista registros resumidos que compõem um indicador |

A produtividade aceita filtros de período, situação, dentistas e comparação. O intervalo máximo é
de 366 dias. Os registros detalhados de produtividade não incluem dados pessoais do paciente.

### Área da dentista

Estas rotas exigem o perfil `dentist`. Os dados são limitados à dentista autenticada, à sua clínica
e aos pacientes autorizados pela agenda.

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/dentist/dashboard` | Consulta a agenda da dentista por data e período |
| `GET` | `/dentist/patients` | Lista pacientes vinculados à agenda da dentista |
| `GET` | `/dentist/patients/{patient_id}/appointments` | Consulta atendimentos concluídos do paciente |
| `GET` | `/dentist/appointment-history` | Consulta histórico de atendimentos com filtros |
| `GET` | `/dentist/patients/{patient_id}/odontogram` | Consulta odontograma e registros autorizados |
| `POST` | `/dentist/patients/{patient_id}/odontogram` | Registra uma condição ou procedimento no odontograma |
| `GET` | `/dentist/patients/{patient_id}/odontogram/history` | Consulta o histórico do odontograma |
| `GET` | `/dentist/treatment-plans` | Lista planos de tratamento autorizados |
| `POST` | `/dentist/treatment-plans` | Cria um plano como rascunho |
| `GET` | `/dentist/treatment-plans/{plan_id}` | Consulta um plano autorizado |
| `PATCH` | `/dentist/treatment-plans/{plan_id}` | Atualiza, inicia ou cancela um plano |
| `POST` | `/dentist/treatment-plans/{plan_id}/procedures` | Adiciona um procedimento ao plano |
| `PATCH` | `/dentist/treatment-plans/{plan_id}/procedures/{procedure_id}` | Atualiza um procedimento planejado |
| `DELETE` | `/dentist/treatment-plans/{plan_id}/procedures/{procedure_id}` | Remove um procedimento ainda planejado |
| `GET` | `/dentist/treatment-plans/{plan_id}/history` | Consulta o histórico de um plano |
| `GET` | `/dentist/documents` | Lista e pesquisa rascunhos clínicos |
| `POST` | `/dentist/documents` | Cria um rascunho clínico |
| `GET` | `/dentist/documents/{document_id}` | Consulta um rascunho autorizado |
| `PATCH` | `/dentist/documents/{document_id}` | Atualiza um rascunho e registra o histórico |
| `GET` | `/dentist/documents/{document_id}/history` | Consulta o histórico de um rascunho |

### Sistema

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/health` | Informa se a API está em execução |

## Regras importantes

- **Acesso:** as rotas protegidas exigem autenticação e respeitam o perfil do usuário. Os dados
  operacionais são limitados à clínica da conta autenticada.
- **Senhas:** são armazenadas como hash, nunca como texto simples. A troca de senha exige a senha
  atual.
- **Convites:** o token de primeiro acesso é de uso único e expira em 48 horas. Só o hash do token
  é armazenado.
- **Odontograma:** os registros preservam autoria e histórico. Correções são registradas como novos
  itens vinculados aos anteriores. A numeração segue o padrão FDI.
- **Planos de tratamento:** um plano novo começa como rascunho. Marcar um procedimento como
  concluído exige um registro correspondente no odontograma e um atendimento concluído.
- **Agenda:** o status de confirmação é separado do status operacional da consulta. Uma resposta
  negativa de comparecimento não cancela a consulta automaticamente; para cancelar, atualize o
  status para `Cancelada`.
- **Banco de dados:** a aplicação cria as tabelas ao iniciar. Essa criação não substitui migrações
  para atualizar o esquema de um banco já existente.

## O que ainda não está disponível

- Não há envio automático de convites por e-mail, nem integração de WhatsApp ou SMS.
- Preferências de notificação são armazenadas, mas ainda não há entrega de avisos operacionais.
  A notificação do navegador serve apenas para um teste iniciado pela própria pessoa.
- Documentos e receitas são somente rascunhos; não há emissão oficial, assinatura digital ou
  modelos configurados. Uma cópia impressa de rascunho não é um documento clínico oficial.
- Não há fluxo de aprovação de plano pelo paciente, catálogo de procedimentos ou preços.
- Prontuário e evoluções clínicas não estão implementados.
- Os relatórios não incluem dados financeiros, exportação em PDF/XLSX ou auditoria específica de
  exportação. O CSV gerencial é montado no navegador a partir dos dados agregados recebidos.
- A agenda não mantém um histórico imutável de remarcações, autor das alterações ou data da última
  atualização. Esses dados não devem ser inferidos a partir do status atual.
- O banco SQLite local é útil para desenvolvimento, mas não é uma configuração pronta para
  produção. Configure um banco e uma estratégia de migração adequados ao ambiente de implantação.

## Estrutura do projeto

```text
backend/
├── core/           # Configurações, JWT e hash de senhas
├── database/       # Engine, sessões e base do SQLAlchemy
├── dependencies/   # Autenticação e permissões
├── enums/          # Valores enumerados do domínio
├── models/         # Tabelas e modelos do banco
├── routes/         # Endpoints da API
├── schemas/        # Validação de requisições e respostas
├── scripts/        # Ferramentas administrativas locais
├── services/       # Regras de negócio compartilhadas
├── main.py         # Inicialização da aplicação
├── requirements.txt
├── .env.example    # Modelo de configuração, sem chave secreta
└── .gitignore      # Exclusão de arquivos locais e privados
```

## Publicar no GitHub

Antes do primeiro envio, confira os arquivos que serão publicados. O `.gitignore` exclui arquivos
`.env`, bancos locais, ambientes virtuais e caches, mas não remove arquivos que já tenham sido
adicionados ao Git.

- **Não publique** bancos de dados, exportações ou exemplos que contenham informações reais de
  pacientes, usuários ou clínicas.
- **Não publique** chaves, senhas, tokens ou o arquivo `.env`. O `.env.example` é apenas um modelo.
- Se um segredo já tiver sido enviado ao GitHub, troque-o imediatamente. Apagar o arquivo em um
  commit posterior não remove o segredo do histórico.
- Em produção, configure a chave secreta, o banco de dados, as origens CORS e um processo de
  migração seguros para o ambiente de implantação.

## Desenvolver

Ao adicionar uma funcionalidade, mantenha cada responsabilidade na pasta correspondente: modelos
em `models/`, validação em `schemas/`, regras compartilhadas em `services/` e endpoints em
`routes/`. Registre novos routers em `main.py` e crie testes para os comportamentos adicionados.

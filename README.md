# Alerta dos Notebooks Desktop

Cliente desktop local para configurar a conexão com a API HTTP do projeto
Alerta dos Notebooks.

Esta primeira versão não conecta ao Telegram, não usa Brevo e não acessa banco
diretamente. O app apenas guarda a URL/token localmente e testa o endpoint
`GET /health` do servidor.

## Requisitos

- Python 3.11+
- Dependências em `requirements.txt`

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Executar

```bash
python -m app.main
```

Ao abrir, o app carrega `app_config.json` se ele existir, mostra a tela de
conexão e permite testar a API em `GET /health`.

O arquivo `app_config.json` é local e está no `.gitignore`.

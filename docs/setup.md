# Установка и запуск

## Этап 1. Установка и настройка OpenClaw

### 1.1. Установка на Windows

В обычном PowerShell выполните официальный установщик:

```powershell
iwr -useb https://openclaw.ai/install.ps1 | iex
```

Либо после обновления Node до поддерживаемой версии:

```powershell
npm install -g openclaw@latest
openclaw onboard --install-daemon
```

Проверка:

```powershell
openclaw --version
openclaw doctor
openclaw gateway status --json
```

Gateway по умолчанию слушает `127.0.0.1:18789`. Затем откройте панель и
проверьте обычный ответ агента:

```powershell
openclaw dashboard
```

### 1.2. Включение HTTP API

OpenAlice будет использовать OpenResponses-совместимый endpoint. Включите его:

```powershell
openclaw config set gateway.http.endpoints.responses.enabled true --strict-json
```

Убедитесь, что Gateway использует аутентификацию с токеном. Токен не следует
хранить в Git или вставлять в `README.md`. После изменения конфигурации:

```powershell
openclaw gateway restart
openclaw gateway status --json
```

Проверьте API, подставив токен только в локальную переменную процесса:

```powershell
$aliceGatewayToken = Read-Host -AsSecureString "OpenClaw Gateway token"
$aliceTokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($aliceGatewayToken)
$aliceToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($aliceTokenPtr)
$headers = @{ Authorization = "Bearer $aliceToken" }
$body = @{
  model = "openclaw/default"
  input = "Ответь одним словом: работает?"
  user = "openalice:smoke-test"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:18789/v1/responses `
  -Headers $headers -ContentType application/json -Body $body
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($aliceTokenPtr)
Remove-Variable aliceToken,aliceGatewayToken,aliceTokenPtr
```

Endpoint `/v1/responses` имеет права оператора OpenClaw. Не публикуйте порт
18789 в интернет и не используйте для него тот же секрет, что для webhook
Алисы. В типовой установке OpenAlice и Gateway общаются только через loopback.

## Этап 2. Установка и запуск OpenAlice

Приложение уже реализовано на следующем стеке:

- FastAPI — HTTPS/webhook-приложение;
- `httpx` — асинхронный вызов OpenClaw;
- Pydantic — минимальная проверка входного JSON;
- SQLite — очередь и отложенные ответы для одного компьютера;
- Uvicorn — локальный сервер;
- pytest — тесты протокола и дедлайна.

Фактическая структура:

```text
OpenAlice/
├── openalice/
│   ├── __init__.py
│   ├── app.py              # стабильный entry point
│   ├── bootstrap.py        # сборка зависимостей
│   ├── domain/             # значения, состояния и текст
│   ├── application/        # команды и прикладные сценарии
│   ├── infrastructure/     # SQLite и внешние интеграции
│   ├── presentation/alice/ # HTTP и модели протокола
│   └── config.py           # настройки из окружения
├── scripts/
│   └── run-openalice.ps1   # фоновый запуск Windows
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

### 2.1. Создание окружения

Из корня проекта:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . --group dev
Copy-Item .env.example .env
```

Локальная команда `poetry` сейчас повреждена, поэтому инструкция использует
обычное виртуальное окружение. `pyproject.toml` остаётся единственным описанием
зависимостей; Poetry можно восстановить позднее без изменения приложения.

Откройте `.env` и замените все значения `replace-with-...`.
`OPENCLAW_GATEWAY_TOKEN` должен в точности совпадать с токеном Gateway,
настроенным во время onboarding OpenClaw. Для нового `ALICE_WEBHOOK_SECRET`
получите случайное значение так:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Не используйте один секрет одновременно для OpenClaw и webhook Алисы.

### 2.2. Ручной запуск и тесты

```powershell
.\scripts\test.ps1
.\.venv\Scripts\python.exe -m uvicorn openalice.app:create_app `
  --factory --host 127.0.0.1 --port 8765
```

В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Ожидаемый ответ: `status = ok`, `service = openalice`.

Полный список настроек и пояснения находятся в [справочнике конфигурации](configuration.md).

Перед отправкой навыка на модерацию установите `OPENALICE_FAKE_MODE=true`,
перезапустите OpenAlice и проверьте `/health`: поле `mode` должно быть равно
`fake`. Для возврата к домашнему помощнику установите значение `false` и снова
перезапустите приложение.

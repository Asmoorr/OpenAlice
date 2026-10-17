# Проверки Bruno

Откройте bruno/Openalice как коллекцию. Скопируйте её .env.example в .env
и заполните секреты локально. Процессные переменные Bruno доступны через
`{{process.env.OPENCLAW_GATEWAY_TOKEN}}`.

Для безопасной проверки включите OPENALICE_FAKE_MODE и запустите OpenAlice.
Для отложенного ответа задайте OPENALICE_FAKE_DELAY_SECONDS больше
ALICE_FAST_TIMEOUT_SECONDS. После вопроса отправьте команду «готово» с новым message_id.

Диагностический вызов Gateway требует отдельного локального операторского токена.
[Правила обращения с секретами](security.md).

CLI smoke (из каталога коллекции, окружение Fake):

```powershell
bru run OpenAlice/Smoke OpenAlice/Commands OpenAlice/Reliability OpenAlice/Security --env Fake --noproxy
```

Секрет берётся из локального .env; CLI также поддерживает секретную переменную
окружения webhook_secret. Не записывайте реальный секрет в команду или отчёт.
run_id создаётся при запуске, чтобы кеш предыдущего прогона не влиял на проверку.

Deferred запускается отдельно при OPENALICE_FAKE_DELAY_SECONDS=6:
первый и второй запрос возвращают ожидание; перед третьим дождитесь завершения.
Для автоматического прогона передайте пути только Question и Result с `--delay 6500`.
SecurityDenied требует непустой ALICE_ALLOWED_USER_IDS, в котором отсутствует
denied-test-user. Диагностика OpenClaw находится в OpenClaw/Diagnostics.

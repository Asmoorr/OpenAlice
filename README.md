# OpenAlice

Приватный голосовой мост между Яндекс Алисой и домашним OpenClaw Gateway.

Поток запроса: Яндекс Диалоги → HTTPS/ngrok → OpenAlice (8765) →
локальный OpenClaw (18789). Если ответ занимает больше быстрого дедлайна,
адаптер сохраняет результат; пользователь получает его командой «готово».

## Быстрый старт

Требуется Python 3.13 и настроенный локальный Gateway.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . --group dev
Copy-Item .env.example .env
# Заполните секрет webhook и токен Gateway в .env
.\.venv\Scripts\python.exe -m uvicorn openalice.app:create_app --factory --host 127.0.0.1 --port 8765
```

Проверка приложения: GET http://127.0.0.1:8765/health.
Для автономной проверки задайте OPENALICE_FAKE_MODE=true.

## Разработка

```powershell
.\scripts\test.ps1
```

[Документация](docs/index.md) · [Архитектура](docs/architecture.md) ·
[Установка](docs/setup.md) · [Конфигурация](docs/configuration.md) ·
[Публикация навыка](docs/yandex-skill.md) · [Уведомления](docs/notifications.md) ·
[Безопасность](docs/security.md) · [Bruno](docs/bruno.md)

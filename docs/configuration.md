# Конфигурация

Источник имён и значений по умолчанию — [.env.example](../.env.example).
Реальные значения задаются в локальном .env. Чувствительные значения в таблице скрыты.

| Переменная | Пример / значение по умолчанию |
|---|---|
| `OPENCLAW_BASE_URL` | http://127.0.0.1:18789 |
| `OPENCLAW_GATEWAY_TOKEN` | Задать локально |
| `OPENCLAW_AGENT` | openclaw/default |
| `OPENCLAW_TIMEOUT_SECONDS` | 300 |
| `OPENALICE_FAKE_MODE` | false |
| `OPENALICE_FAKE_RESPONSE` | Тестовый режим работает. Запрос обработан без обращения к домашнему помощнику. |
| `OPENALICE_FAKE_DELAY_SECONDS` | 0 |
| `ALICE_WEBHOOK_SECRET` | Задать локально |
| `ALICE_ALLOWED_USER_IDS` | Пусто |
| `ALICE_FAST_TIMEOUT_SECONDS` | 3.8 |
| `ALICE_MAX_RESPONSE_CHARS` | 900 |
| `ALICE_PENDING_PHRASES` | Мне нужно немного времени. Скажите «готово» через несколько секунд.\|Ответ ещё готовится. Скажите «готово» немного позже. |
| `NOTIFICATIONS_ENABLED` | false |
| `NOTIFICATION_PROVIDER` | home_assistant |
| `HOME_ASSISTANT_URL` | http://127.0.0.1:8123 |
| `HOME_ASSISTANT_TOKEN` | Задать локально |
| `HOME_ASSISTANT_ENTITY_ID` | media_player.yandex_station_mini |
| `HOME_ASSISTANT_TIMEOUT_SECONDS` | 3 |
| `GLAGOL_DEVICE_ID` | Пусто |
| `GLAGOL_PLATFORM` | Пусто |
| `GLAGOL_HOST` | Пусто |
| `GLAGOL_PORT` | 1961 |
| `GLAGOL_CREDENTIALS_PATH` | ./data/glagol_credentials.json |
| `GLAGOL_TIMEOUT_SECONDS` | 5 |
| `GLAGOL_DISCOVERY_TIMEOUT_SECONDS` | 3 |
| `NOTIFICATION_READY_PHRASE` | Ответ готов. Скажите «готово», чтобы его услышать. |
| `NOTIFICATION_MAX_ATTEMPTS` | 3 |
| `NOTIFICATION_POLL_SECONDS` | 5 |
| `DATABASE_PATH` | ./openalice.db |
| `LOG_LEVEL` | INFO |

## Пояснения к настройкам

Откуда брать каждое значение:

- `OPENCLAW_BASE_URL` — оставьте `http://127.0.0.1:18789`, если не меняли
  стандартный локальный порт OpenClaw.
- `OPENCLAW_GATEWAY_TOKEN` — после onboarding выполните в интерактивном
  PowerShell `openclaw gateway auth-token --show`. Команда специально не
  поддерживает перенаправление вывода. Если токена ещё нет:
  `openclaw doctor --generate-gateway-token`, затем
  `openclaw gateway restart` и снова `openclaw gateway auth-token --show`.
- `OPENCLAW_AGENT` — для основного агента оставьте `openclaw/default`. Другой
  агент задаётся как `openclaw/<agentId>`.
- `OPENALICE_FAKE_MODE` — установите `true` для модерации или безопасных тестов.
  В этом режиме HTTP-клиент OpenClaw не создаётся, поэтому запросы гарантированно
  не доходят до Gateway и не могут запустить инструменты домашнего помощника.
- `OPENALICE_FAKE_RESPONSE` — ответ на любую обычную реплику в тестовом режиме.
  Служебные команды OpenAlice продолжают работать как обычно.
- `OPENALICE_FAKE_DELAY_SECONDS` — искусственная задержка ответа. Значение `0`
  имитирует быстрый ответ; значение больше `ALICE_FAST_TIMEOUT_SECONDS` позволяет
  проверить сценарий с командой «готово».
- `ALICE_WEBHOOK_SECRET` — создайте самостоятельно командой из раздела выше.
  Это значение станет секретной частью URL, а не токеном Яндекса.
- `ALICE_ALLOWED_USER_IDS` — сначала оставьте пустым. В тестировании навыка
  Яндекс Диалогов откройте тело последнего входного запроса и скопируйте
  `session.user.user_id`. Несколько ID перечисляются через запятую без пробелов.
- `ALICE_FAST_TIMEOUT_SECONDS` — оставьте `3.8`, чтобы сохранить запас до
  дедлайна Яндекс Диалогов около 4,5 секунды.
- `OPENCLAW_TIMEOUT_SECONDS` — полный таймаут фонового запроса к OpenClaw.
  Значение `300` позволяет дождаться долгого ответа после перехода в отложенный режим.
- `ALICE_MAX_RESPONSE_CHARS` — рекомендуется `900`; абсолютный максимум Алисы
  равен 1024 символам.
- `ALICE_PENDING_PHRASES` — варианты ответа, пока результат не готов. Фразы
  разделяются символом `|`; чтобы добавить или удалить вариант, отредактируйте
  эту строку и перезапустите OpenAlice. Должна остаться хотя бы одна фраза.
- `NOTIFICATIONS_ENABLED` — включает фоновое уведомление о готовности.
- `NOTIFICATION_PROVIDER` — канал уведомления: `home_assistant` или `glagol`.
- `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN` и `HOME_ASSISTANT_ENTITY_ID` —
  адрес API, долгоживущий токен и `entity_id` нужной Яндекс Станции.
- `GLAGOL_DEVICE_ID`, `GLAGOL_PLATFORM`, `GLAGOL_HOST` и `GLAGOL_PORT` —
  параметры прямого локального подключения. `HOST` можно не задавать: тогда
  адрес и платформа ищутся по mDNS при каждой попытке доставки.
- `GLAGOL_CREDENTIALS_PATH` — локальный файл токенов Яндекса. Он содержит
  секреты в открытом виде, не должен синхронизироваться или попадать в Git.
- `NOTIFICATION_READY_PHRASE` — короткая фраза, которую произнесёт Станция.
- `NOTIFICATION_MAX_ATTEMPTS` и `NOTIFICATION_POLL_SECONDS` — количество попыток
  доставки и период проверки сохранённой очереди.
- `DATABASE_PATH` — локальная SQLite-база; `./openalice.db` подходит для одного
  ноутбука.
- `LOG_LEVEL` — `INFO` для обычной работы, `DEBUG` только при диагностике.

# OpenAlice: Яндекс Алиса как голосовой интерфейс OpenClaw

Цель проекта — один приватный навык Яндекс Алисы, который передаёт реплики в
OpenClaw и возвращает ответ агента на Яндекс Станцию. Сценарии, память и
инструменты находятся в OpenClaw; отдельные навыки под каждую задачу не нужны.

## Архитектура

```text
Яндекс Станция
    │ голос
    ▼
Яндекс Диалоги
    │ HTTPS POST, протокол 1.0
    ▼
OpenAlice (FastAPI, этот проект)
    │ POST /v1/responses
    ▼
OpenClaw Gateway
    │
    ├── агент и память
    ├── skills
    └── инструменты и внешние сервисы
```

OpenAlice — намеренно тонкий адаптер. Он должен:

1. принять и проверить запрос Яндекс Диалогов;
2. выделить текст из `request.command`;
3. получить стабильный идентификатор беседы;
4. вызвать агента OpenClaw;
5. привести ответ к формату Алисы и ограничить его 1024 символами;
6. уложиться в дедлайн Алисы или сохранить отложенный ответ.

## Что обнаружено в локальном окружении

- Windows, PowerShell;
- Python 3.13.14;
- исходный проект создан с Poetry, но локальная установка Poetry повреждена;
- Node.js 24.1.0 и npm 11.3.0;
- Docker CLI 28.3.3 установлен;
- Docker Desktop/daemon сейчас не запущен;
- команда `openclaw` не установлена;
- каталог пока не является Git-репозиторием.

Текущий Node.js 24.1.0 ниже актуального требования OpenClaw для ветки Node 24
(нужен 24.15 или новее). Самый простой путь — официальный установщик OpenClaw:
он проверит и при необходимости установит подходящий Node. Docker для первого
локального прототипа не требуется.

## Важное ограничение Алисы

Яндекс считает ошибкой, если webhook не успел ответить примерно за 4,5 секунды.
Полный агентский проход OpenClaw с инструментами часто длится дольше. Поэтому
первая рабочая версия должна поддерживать два режима:

- быстрый ответ: ждём OpenClaw около 3,8 секунды и сразу озвучиваем результат;
- отложенный ответ: сохраняем выполняющуюся задачу, отвечаем «Мне нужно немного
  времени. Скажите “готово”», а при следующей реплике отдаём результат.

Самостоятельно заговорить позднее обычный навык Алисы не может. Поэтому вариант
«ответить на следующую реплику» надёжнее обещания push-ответа на колонку.

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
│   ├── app.py              # FastAPI и /alice/webhook/{secret}
│   ├── alice_models.py     # модели запроса/ответа Диалогов
│   ├── openclaw_client.py  # /v1/responses
│   ├── config.py           # настройки из окружения
│   ├── store.py            # SQLite, очередь и дедупликация
│   └── text.py             # подготовка текста для озвучивания
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
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.test-tmp -p no:cacheprovider
.\.venv\Scripts\python.exe -m uvicorn openalice.app:create_app `
  --factory --host 127.0.0.1 --port 8000
```

В другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Ожидаемый ответ: `status = ok`, `service = openalice`.

Переменные окружения:

```dotenv
OPENCLAW_BASE_URL=http://127.0.0.1:18789
OPENCLAW_GATEWAY_TOKEN=replace-with-a-long-random-token
OPENCLAW_AGENT=openclaw/default
ALICE_WEBHOOK_SECRET=replace-with-a-different-random-token
ALICE_ALLOWED_USER_IDS=
ALICE_FAST_TIMEOUT_SECONDS=3.8
ALICE_MAX_RESPONSE_CHARS=900
DATABASE_PATH=./openalice.db
LOG_LEVEL=INFO
```

Реальный `.env` должен быть в `.gitignore`; в репозитории хранится только
`.env.example` без секретов.

Сначала оставьте `ALICE_ALLOWED_USER_IDS` пустым. Во вкладке тестирования Яндекс
Диалогов посмотрите тело входного запроса, скопируйте
`session.user.user_id` в `.env` и перезапустите OpenAlice. Несколько разрешённых
идентификаторов указываются через запятую.

### Идентификатор беседы

Приоритет идентификаторов:

1. `session.user.user_id`, если пользователь авторизован;
2. `session.application.application_id` как fallback.

В OpenClaw передаётся, например:

```text
openalice:yandex-user:<sha256 исходного идентификатора>
```

Передача хеша уменьшает утечку связующего идентификатора в журналы. Поле `user`
в `/v1/responses` обеспечивает стабильную маршрутизацию сессии между запросами.
Для отдельного контекста каждого члена семьи позже можно добавить голосовой
выбор профиля; сама Станция не гарантирует передачу личности говорящего.

### Формат вызова OpenClaw

Минимальный запрос:

```json
{
  "model": "openclaw/default",
  "input": "Текст команды пользователя",
  "user": "openalice:yandex-user:..."
}
```

Из ответа приложение извлекает итоговый текст, удаляет Markdown, непригодный для
озвучивания, и формирует:

```json
{
  "response": {
    "text": "Короткий ответ",
    "tts": "Короткий ответ",
    "end_session": false
  },
  "version": "1.0"
}
```

`text` и `tts` Алисы ограничены 1024 символами. Клиент уже передаёт системное
правило отвечать по-русски без Markdown и желательно до 800 символов. Слишком
длинный результат обрезается по границе предложения или слова.

### Команды самого адаптера

До отправки текста агенту адаптер обрабатывает фиксированный набор:

- «помощь» / «что ты умеешь» — описание навыка;
- «готово» / «проверь результат» — получить отложенный ответ;
- «отмена» — отменить ожидающую задачу, если это позволяет API;
- «новый диалог» — начать новый ключ сессии;
- «выйти» / «хватит» — вернуть `end_session: true`.

Всю остальную маршрутизацию выполняет OpenClaw, а не дерево условий OpenAlice.

## Этап 3. Публичный HTTPS webhook

Яндекс Диалоги должны видеть OpenAlice по публичному HTTPS URL с корректным
сертификатом. Адрес `localhost` не подойдёт. В этой конфигурации публичный вход
организуется через ngrok, а OpenAlice и OpenClaw остаются на домашнем ноутбуке.
Проброс портов на роутере, белый IP и Dynamic DNS не требуются: ngrok создаёт
исходящее TLS-соединение с облаком через порт 443.

### 3.1. Установка ngrok

```powershell
winget install ngrok -s msstore
ngrok version
ngrok config add-authtoken "<ТОКЕН_ИЗ_NGROK_DASHBOARD>"
```

На бесплатном тарифе аккаунту назначается один development-домен вида
`example-name.ngrok-free.app`. Используйте назначенный домен из Dashboard:
случайный адрес нельзя оставлять в настройках навыка, поскольку после его
изменения Алиса потеряет webhook.

Когда OpenAlice слушает `127.0.0.1:8000`, первый ручной запуск выглядит так:

```powershell
ngrok http 8000 --url https://example-name.ngrok-free.app
```

Проверьте публичный endpoint:

```text
https://example-name.ngrok-free.app/health
```

ngrok завершает публичный HTTPS и пересылает обычный HTTP на loopback ноутбука.
Собственный сертификат для FastAPI не нужен.

Публичным должен быть только адрес вида:

```text
https://example-name.ngrok-free.app/alice/webhook/<ALICE_WEBHOOK_SECRET>
```

Дополнительно OpenAlice проверяет allowlist `session.user.user_id`. Секрет в URL
защищает от случайных запросов, но не заменяет allowlist, rate limiting и
фильтрацию журналов. Не включайте ngrok Basic Auth или интерактивный OAuth:
Яндекс Диалоги не смогут пройти такую авторизацию.

Не публикуйте через ngrok порт OpenClaw `18789` или другие локальные сервисы.
Единственный публичный upstream — OpenAlice на порту 8000.

### 3.2. Ограничения домашнего варианта

Навык доступен, только пока ноутбук включён, не спит, подключён к интернету и
работают OpenClaw Gateway, OpenAlice и ngrok. Для личного использования лимитов
бесплатного ngrok обычно достаточно: на момент подготовки инструкции это 20 000
HTTP-запросов и 1 ГБ исходящего трафика в месяц. Актуальные значения следует
проверять в Dashboard.

## Этап 4. Создание приватного навыка

1. Откройте консоль разработчика Яндекс Диалогов.
2. Создайте «Навык в Алисе».
3. Укажите короткое уникальное имя, например «Открытый помощник».
4. В Backend выберите Webhook URL и вставьте публичный адрес OpenAlice.
5. Выберите поверхность «Яндекс Станция».
6. Установите тип доступа «Приватный».
7. Добавьте понятное приветствие и обработку команд «Помощь» и
   «Что ты умеешь».
8. Сначала проверьте запросы во вкладке тестирования.
9. Опубликуйте приватный навык и дождитесь автоматической проверки.
10. На колонке с тем же аккаунтом скажите: «Алиса, запусти навык Открытый
    помощник».

Приватный навык не виден в общем каталоге. По актуальной документации Яндекса
навыки, включая приватные, проходят проверку; для предоставления доступа другому
аккаунту используется одноразовая ссылка на вкладке «Доступ».

## Этап 5. Автоматический запуск вместе с ноутбуком

Автоматически запускаются три независимых компонента:

1. OpenClaw Gateway — управляемая задача OpenClaw;
2. OpenAlice — задача Планировщика Windows;
3. ngrok — системная служба Windows.

Рекомендуемый режим для личного ноутбука — запуск после входа пользователя в
Windows. Если система должна отвечать ещё до входа, OpenAlice нужно оформить как
Windows-службу либо выбрать в задаче «Выполнять вне зависимости от регистрации
пользователя», что потребует сохранения учётных данных задачи.

### 5.1. OpenClaw Gateway

Во время первоначальной настройки установите управляемый запуск:

```powershell
openclaw onboard --install-daemon
```

Если onboarding уже выполнен:

```powershell
openclaw gateway install
openclaw gateway status --json
```

На Windows OpenClaw использует Планировщик заданий, а при недостатке разрешений
может использовать пользовательскую папку Startup.

### 5.2. OpenAlice через Планировщик Windows

В проект добавлен `scripts/run-openalice.ps1`. Скрипт:

1. перейти в `C:\Programming\2026\OpenAlice`;
2. загрузить секреты из локального `.env`;
3. запускает `.venv\Scripts\python.exe -m uvicorn openalice.app:create_app
   --factory --host 127.0.0.1 --port 8000`;
4. писать технические логи в `logs/`, не сохраняя секреты и полные реплики.

В Планировщике заданий создайте задачу `OpenAlice`:

- триггер: «При входе в систему» текущего пользователя;
- задержка: 20 секунд для запуска сети и Gateway;
- программа: `powershell.exe`;
- аргументы:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\Programming\2026\OpenAlice\scripts\run-openalice.ps1"
```

- рабочая папка: `C:\Programming\2026\OpenAlice`;
- отключить условия «только при питании от электросети» и «останавливать при
  переходе на батарею»;
- при сбое перезапускать каждую минуту, минимум 5 попыток;
- если задача уже работает — не запускать второй экземпляр.

Не используйте `--reload`: это режим разработки. Uvicorn должен слушать только
`127.0.0.1`, поскольку ngrok находится на том же компьютере.

### 5.3. ngrok как Windows-служба

Создайте постоянный файл `C:\ProgramData\OpenAlice\ngrok.yml`:

```yaml
version: 3
agent:
  authtoken: <ТОКЕН_NGROK>
endpoints:
  - name: openalice
    url: https://example-name.ngrok-free.app
    upstream:
      url: http://127.0.0.1:8000
```

Не храните этот файл в Git. Ограничьте доступ к нему, поскольку он содержит
authtoken. Затем откройте PowerShell от имени администратора:

```powershell
ngrok config check --config C:\ProgramData\OpenAlice\ngrok.yml
ngrok service install --config C:\ProgramData\OpenAlice\ngrok.yml
ngrok service start
```

Служба запускается при загрузке Windows, поднимает endpoints из конфигурации и
автоматически восстанавливается после сбоя. Управление:

```powershell
ngrok service restart
ngrok service stop
ngrok service uninstall
```

Если ngrok запустится раньше OpenAlice, некоторое время он будет возвращать
ошибку upstream. После запуска Uvicorn пересылка восстановится автоматически.

### 5.4. Питание и сеть

В параметрах электропитания Windows отключите автоматический сон при питании от
сети. Если ноутбук должен работать сервером с закрытой крышкой, установите для
закрытия крышки действие «Действие не требуется» при питании от сети. Выключение
экрана работе не мешает; сон и гибернация делают навык недоступным.

После смены Wi-Fi ngrok обычно переподключается самостоятельно. Открывать
входящие порты Windows Firewall не требуется: FastAPI слушает loopback, а ngrok
создаёт исходящее соединение.

### 5.5. Проверка после перезагрузки

Перезагрузите ноутбук, войдите в Windows и ничего не запускайте вручную. Через
30–60 секунд выполните:

```powershell
openclaw gateway status --json
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod https://example-name.ngrok-free.app/health
```

Затем отправьте реплику во вкладке тестирования Яндекс Диалогов и запустите навык
на Станции. Автозапуск считается настроенным, только если вся цепочка поднялась
после перезагрузки без открытых терминалов.

## Этап 6. Проверки перед реальным использованием

Обязательные тесты:

- новый сеанс возвращает приветствие быстрее 4 секунд;
- короткий ответ OpenClaw возвращается синхронно;
- медленный ответ превращается в отложенную задачу;
- «готово» во время выполнения сообщает, что задача ещё работает;
- «готово» после завершения возвращает результат;
- ответы длиннее 1024 символов корректно сокращаются;
- неизвестный `user_id` получает отказ без вызова OpenClaw;
- неправильный секрет webhook даёт HTTP 404 или 401;
- недоступный Gateway возвращает дружелюбную реплику, а не HTTP 500;
- токены и полные пользовательские реплики не попадают в обычные логи;
- повтор одного `message_id` не запускает опасное действие дважды.

Последний пункт особенно важен для агента с инструментами. Для действий с
побочными эффектами нужны подтверждения: OpenAlice не должен превращать
ошибочное распознавание речи в удаление файлов, отправку сообщений или покупки.

## Оставшиеся шаги развёртывания

1. Обновить Node и установить OpenClaw.
2. Завершить onboarding и проверить агента через Control UI.
3. Включить и проверить локальный `/v1/responses`.
4. Заполнить `.env` и проверить локальный OpenAlice.
5. Настроить постоянный HTTPS endpoint ngrok и проверить Диалоги.
6. Настроить приватный навык на Станции.
7. Настроить автозапуск трёх компонентов и выполнить тест перезагрузки.
8. Только после этого подключать к агенту потенциально опасные инструменты.

## Первоисточники

- Яндекс: протокол навыков — <https://yandex.ru/dev/dialogs/alice/doc/ru/protocol>
- Яндекс: формат запроса — <https://yandex.ru/dev/dialogs/alice/doc/ru/request>
- Яндекс: формат ответа — <https://yandex.ru/dev/dialogs/alice/doc/ru/response>
- Яндекс: запуск, выход и дедлайн — <https://yandex.ru/dev/dialogs/alice/doc/ru/activation>
- Яндекс: управление доступом — <https://yandex.ru/dev/dialogs/alice/doc/ru/access>
- OpenClaw: установка — <https://docs.openclaw.ai/install>
- OpenClaw: Windows — <https://docs.openclaw.ai/windows>
- OpenClaw: OpenResponses API — <https://docs.openclaw.ai/gateway/openresponses-http-api>
- OpenClaw: конфигурация — <https://docs.openclaw.ai/gateway/configuration>
- ngrok: агент и Windows-служба — <https://ngrok.com/docs/agent>
- ngrok: лимиты бесплатного плана — <https://ngrok.com/docs/pricing-limits/free-plan-limits>
- Референс похожего проекта — <https://github.com/eluceon/alice-llm-bridge>

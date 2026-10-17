## Context

См. мотивацию в `proposal.md` и проверяемые требования в `specs/`.

Текущая реализация компактна, но имеет несколько концентраторов ответственности:

- `openalice/app.py` (471 строка) одновременно создаёт зависимости, описывает lifespan и маршруты, классифицирует команды, управляет дедупликацией и keyed locks, запускает Gateway-задачи и сохраняет отложенные ответы.
- `openalice/store.py` предоставляет прикладной API и непосредственно выполняет SQL; возвращаемые job представлены нетипизированными словарями, а атомарная запись результата с уведомлением скрыта среди CRUD-методов.
- Внешние интеграции уже частично используют Protocol и подменяемые реализации, но composition root, application ports и границы импортов формально не выделены.
- Набор содержит 46 тестов, однако отдельных тестовых модулей для `store`, `openclaw_client`, `config`, `text` и моделей протокола нет. Контрольный запуск дал 29 успешных тестов и 17 setup errors из-за недоступного системного `%TEMP%`, что подтверждает необходимость локального test workspace.
- В корне накоплено более пятнадцати каталогов `.test-tmp-*`; README содержит около 680 строк; Bruno содержит один прямой Gateway-запрос с отслеживаемым bearer-токеном.
- В `openalice/openclaw_client.py` имеется незакоммиченное пользовательское изменение timeout. Миграция обязана сохранить его без перезаписи и не должна автоматически включать его в несвязанный коммит.

Ограничения: Python 3.13, полностью асинхронный внешний путь, SQLite, webhook-дедлайн Алисы, локальный Gateway на порту 18789 и запрет на логирование реплик, токенов и полных идентификаторов.

## Goals / Non-Goals

**Goals:**

- Получить односторонний граф зависимостей `presentation → application → domain`, где infrastructure подключается только в composition root и реализует внутренние порты.
- Сделать правила диалога тестируемыми через детерминированные in-memory doubles, не меняя публичный контракт.
- Сделать архитектурные паттерны явными, небольшими и проверяемыми, без классов-обёрток ради формального ООП.
- Ввести воспроизводимый quality-check и безопасную для Windows стратегию временных файлов.
- Разделить миграцию на коммиты, каждый из которых проходит тесты и допускает локальный откат.

**Non-Goals:**

- Изменение webhook-протокола Яндекс Диалогов, пользовательских фраз и набора служебных команд.
- Замена FastAPI, SQLite, OpenResponses API, Home Assistant или Glagol.
- Перенос сценариев, памяти или инструментов из OpenClaw в OpenAlice.
- Долгое ожидание webhook вместо существующего механизма deferred result.
- Введение DI-контейнера, ORM, event bus или универсального framework слоя.
- Переписывание истории Git для удаления раскрытого токена: файл будет очищен, но отзыв токена выполняет оператор; history rewrite требует отдельного решения.

## Decisions

### 1. Слои и целевая структура

Целевая структура:

```text
openalice/
  domain/                 # значения, состояния и правила без I/O
  application/            # use cases, ports, координация запросов
  infrastructure/
    gateway/              # OpenClaw HTTP adapter
    persistence/          # SQLite repositories и outbox
    notifications/        # Home Assistant и Glagol adapters
  presentation/
    alice/                # Pydantic DTO, mapper и FastAPI router
  bootstrap.py            # composition root
  app.py                  # стабильный create_app и совместимый entry point
```

`domain` не импортирует другие слои. `application` импортирует только `domain` и стандартную библиотеку. `presentation` и `infrastructure` реализуют или вызывают порты application. `bootstrap.py` — единственное место, где выбираются конкретные реализации по `Settings`.

Альтернатива: оставить плоские модули и только разбить `app.py` на функции. Это уменьшило бы diff, но не обеспечило бы проверяемое направление зависимостей и изолированные use cases. Альтернатива с отдельным классом на каждую операцию отклонена как избыточная для небольшого сервиса.

### 2. Модель приложения и порты

В domain вводятся типизированные `JobStatus`, `PendingJob`, `CompletedJob`, `FailedJob`, `ConversationKey` и `CommandIntent`. Строковые статусы и словари не пересекают границу persistence adapter.

Application ports разделяются по ответственности:

- `AssistantGateway` — запрос ответа и закрытие ресурса;
- `JobRepository` — состояние текущей работы;
- `RequestCache` — дедупликация webhook;
- `ConversationGenerationRepository` — версия стабильной сессии;
- `DeferredCompletionRepository` — атомарное завершение job вместе с записью notification outbox;
- `Notifier`, `PendingPhraseStrategy`, `Clock` и генератор идентификаторов — внешние или недетерминированные зависимости.

Один `SqliteStore` может реализовать несколько узких repository ports, сохраняя одну блокировку и транзакции. Атомарная операция результата и уведомления остаётся отдельным портом: это Transactional Outbox, предотвращающий состояние «ответ сохранён, уведомление потеряно».

Альтернатива: единый широкий `Store` protocol. Она проще вначале, но нарушает interface segregation и заставляет unit-тесты подделывать несвязанные методы.

### 3. Прикладная orchestration и конкурентность

`ConversationService` становится фасадом прикладных use cases: открыть навык, обработать сообщение или локальную команду, получить результат, отменить работу и начать новое поколение. Он возвращает transport-neutral результат (`Reply` с текстом и `end_session`), который Alice mapper преобразует в DTO.

`RequestCoordinator` владеет только process-local состоянием: inflight webhook, Gateway tasks и keyed conversation locks. Записи освобождаются после завершения; keyed locks используют счётчик владельцев/ожидающих, чтобы словарь не рос бесконечно. SQLite остаётся источником истины для переживающих рестарт jobs, cache и outbox.

Граница быстрого ответа инкапсулируется в use case и использует внедряемые timeout/clock primitives. Callback сохранения deferred result заменяется именованной coroutine, которой владеет coordinator, чтобы shutdown мог дождаться или отменить её предсказуемо.

Альтернатива: хранить все asyncio-структуры в FastAPI `app.state`. Она сохраняет текущую связанность transport и application и затрудняет unit-тестирование.

### 4. Точное применение паттернов

- **Adapter**: Alice/FastAPI, OpenClaw HTTP, SQLite, Home Assistant и Glagol преобразуют внешние протоколы во внутренние ports. Польза — изоляция форматов и ошибок сторонних систем.
- **Strategy**: notifier channel, выбор фразы ожидания и Gateway retry policy взаимозаменяемы через небольшие контракты. Польза — вариативность настройки и детерминированные тесты.
- **Command**: `CommandDispatcher` сопоставляет `CommandIntent` с обработчиком `Help`, `Result`, `Cancel`, `NewDialog`, `Exit`. Обработчик инкапсулирует ровно один сценарий; обычное сообщение идёт отдельным путём. Польза — удаление растущей условной цепочки и локальные тесты команд.
- **Repository**: persistence ports скрывают SQL и отображение строк в domain-модели. Это enterprise pattern, а не GoF; он применяется ради инверсии зависимости.
- **Factory / Composition Root**: `build_runtime(settings, overrides)` создаёт конкретные adapters и сервисы. Factory не распространяется на domain-объекты и не превращается в service locator.
- **Facade**: `ConversationService` предоставляет presentation-слою небольшой прикладной API. Он не знает FastAPI/Pydantic.

State, Observer, Abstract Factory и Mediator намеренно не вводятся: текущая вариативность не оправдывает стоимость этих объектов. Переходы job проверяются типами и repository methods; доставка уведомлений уже обеспечивается persisted outbox worker, а не in-memory Observer.

### 5. Совместимая поэтапная миграция

Сначала создаются characterization/contract tests текущего поведения. Затем вводятся domain types и ports без переключения HTTP-пути. SQLite и внешние клиенты переносятся за ports с временными re-export для существующих импортов тестов. После этого orchestration переносится в application service, а `create_app` переключается на новый composition root. Только после зелёного полного набора удаляются совместимые прокладки и мёртвый код.

Каждый архитектурный коммит должен сохранять запускаемый `create_app` и не менять схему SQLite. Новая миграция базы не требуется.

Альтернатива: одномоментно переместить все модули. Она быстрее по числу шагов, но делает регрессию concurrency/deferred flow трудной для локализации и отката.

### 6. Тестовая стратегия и quality gate

Тесты группируются в `tests/unit`, `tests/integration`, `tests/contract` и `tests/quality`. Unit-тесты используют ручные fakes/spies; network adapters используют mock transports/sessions; SQLite-тесты работают только в локальном pytest workspace. Реальные сервисы и сеть не используются.

В dev group добавляются `pytest-cov`, `ruff`, `mypy` и средство проверки import contracts. Конфигурация хранится в `pyproject.toml`: Python 3.13, branch coverage, fail-under 90, форматирование/lint, строгие типы для production package с точечными обоснованными исключениями для сторонних SDK. `scripts/check.ps1` последовательно выполняет format-check, lint, type-check, import contracts, tests и локальные doc-link tests.

Покрытие считается защитой от непроверенных ветвей, а не целью само по себе: исключаются только defensive guards, которые доказуемо недостижимы, и entry-point `if __name__ == "__main__"`.

### 7. Один test workspace

`pyproject.toml` задаёт `--basetemp=.test-tmp` и отключает cacheprovider, поэтому даже прямой pytest использует одно имя. `scripts/test.ps1` разрешает абсолютный путь `<repo>/.test-tmp`, проверяет его родителя и leaf name перед очисткой, выполняет pytest в `try/finally` и никогда не генерирует соседнее имя при ошибке удаления. Quality-check вызывает этот же скрипт.

Существующие `.test-tmp-*` удаляются отдельным chore-коммитом после read-only перечисления и проверки разрешённых путей. `.gitignore` сужается с `.test-tmp*/` до `.test-tmp/`, чтобы случайное появление нового варианта было видно в `git status`.

Альтернатива: системный Temp. Она уже не работает в текущем ограниченном Windows-окружении. Уникальный каталог на каждый запуск отклонён, поскольку именно он создаёт накопление.

### 8. Bruno и обращение с секретом

Коллекция делится на `OpenAlice/Smoke`, `OpenAlice/Commands`, `OpenAlice/Reliability`, `OpenAlice/Security` и отдельную `OpenClaw/Diagnostics`. Общие base URLs и нечувствительные defaults хранятся в versioned environment example; секреты читаются из локального игнорируемого environment-файла или process environment. Pre-request checks останавливают запрос при отсутствии обязательного секрета.

Последовательные сценарии используют фиксированный тестовый `session_id`, общий `skill_id` и управляемый `message_id`; assertions проверяют status, `version`, `response.text`, `response.tts` и `end_session`. Deferred workflow документирует требуемый fake delay и состоит из вопроса и последующего `готово`.

Текущий bearer-токен удаляется из коллекции первым security-коммитом. В design и логах значение не воспроизводится. Оператор должен отозвать его до использования новой коллекции. Переписывание истории не выполняется автоматически.

### 9. Документация

README ограничивается назначением, короткой схемой, prerequisites, quick start, health check, quality-check и оглавлением. Подробности распределяются так:

- `docs/architecture.md` — слои, поток immediate/deferred и каталог паттернов;
- `docs/setup.md` — OpenClaw и OpenAlice;
- `docs/configuration.md` — единая таблица переменных из `.env.example`;
- `docs/yandex-skill.md` — ngrok и приватный навык;
- `docs/notifications.md` — Home Assistant и Glagol;
- `docs/operations.md` — автозапуск, backup, health и обновление;
- `docs/development.md` — тесты, quality gate, структура и commit style;
- `docs/bruno.md` — environments и порядок сценариев;
- `docs/security.md` — секреты, allowlist, логи и ротация;
- `docs/troubleshooting.md` — диагностические симптомы и решения.

`docs/index.md` служит картой. Локальный test проверяет ссылки и соответствие списка переменных `.env.example`; страницы ссылаются на каноническую таблицу вместо копирования.

## Risks / Trade-offs

- [Большой diff может скрыть регрессию deferred/concurrency] → Сначала зафиксировать characterization tests, переносить по одному адаптеру/use case и запускать полный gate после каждого коммита.
- [Число модулей вырастет для небольшого сервиса] → Ограничить слои реальными границами, не создавать interface без вариативности или тестовой ценности, документировать каждый pattern participant.
- [Strict typing сторонних библиотек может требовать заглушек] → Изолировать untyped SDK в adapters и разрешать точечные исключения только с комментарием, не ослабляя весь пакет.
- [Порог 90% стимулирует малоценные тесты] → Требовать branch coverage и поведенческие assertions; не считать smoke-тесты заменой unit-тестам.
- [Очистка `.test-tmp` потенциально разрушительна] → Разрешать только вычисленный абсолютный `<repo>/.test-tmp`, проверять parent и leaf, не следовать произвольным переменным или glob при удалении.
- [Windows может удерживать SQLite-файл после теста] → Гарантированно закрывать clients/connections, выполнять cleanup в `finally` и завершать запуск ошибкой вместо создания нового каталога.
- [Удалённый из текущего файла токен останется в Git history] → Немедленная ротация оператором; history rewrite выносится в отдельную явно подтверждённую операцию.
- [Пользовательская правка timeout может конфликтовать с переносом Gateway adapter] → Снять diff перед каждым затрагивающим коммитом, перенести её семантику без staging чужого изменения либо попросить владельца сначала оформить отдельный commit.

## Migration Plan

1. Зафиксировать planning artifacts и baseline-аудит; не включать пользовательский diff Gateway.
2. Удалить секрет из текущего Bruno-файла и добавить безопасную конфигурацию; оператор отдельно отзывает старый токен.
3. Добавить единый test workspace и безопасно удалить проверенные `.test-tmp-*`.
4. Добавить characterization tests публичного поведения и текущих concurrency/deferred сценариев.
5. Ввести domain types, application ports и import contracts без переключения production flow.
6. Перенести SQLite, Gateway и notification adapters, сохраняя временные re-export.
7. Ввести Command handlers, `ConversationService` и `RequestCoordinator`; переключить Alice controller и composition root.
8. Добавить оставшиеся unit/integration/contract tests, coverage и статические проверки; удалить compatibility shims.
9. Расширить и проверить Bruno-коллекцию.
10. Разделить README и `docs/`, проверить ссылки и соответствие конфигурации.
11. Выполнить полный quality-check и ручной Bruno smoke в fake mode.

Rollback выполняется обратным revert конкретного коммита. Поскольку схема SQLite и публичный API не меняются, откат не требует миграции данных. Security-коммит с удалением токена не откатывается; при проблемах используется новый локальный secret.

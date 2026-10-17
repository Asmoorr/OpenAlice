## 1. `[docs]: Подготовлен план архитектурного рефакторинга`

- [x] 1.1 Добавить в коммит только `.agents/`, `openspec/config.yaml` и change `refactor-architecture-and-quality`; проверить `git diff --cached`, что пользовательское изменение `openalice/openclaw_client.py` и другие файлы не проиндексированы.
- [x] 1.2 Выполнить `openspec validate refactor-architecture-and-quality --strict` и проверить, что proposal, пять specs, design и tasks проходят валидацию до создания коммита.

## 2. `[fix]: Удалён секрет из коллекции Bruno`

- [x] 2.1 Заменить встроенный bearer-токен в диагностическом Bruno-запросе обязательной локальной переменной и проверить поиском по отслеживаемым файлам, что исходное значение и похожие токены отсутствуют.
- [x] 2.2 Добавить игнорируемый локальный Bruno environment и versioned example только с нечувствительными значениями; проверить `git check-ignore` для локального файла и просмотреть staged diff на отсутствие секретов.
- [ ] 2.3 Сообщить оператору о необходимости отозвать раскрытый Gateway token и зафиксировать подтверждение ротации как внешнюю проверку; не переписывать историю Git без отдельного явного разрешения.

## 3. `[test]: Унифицировано временное окружение тестов`

- [x] 3.1 Настроить pytest на единственный `--basetemp=.test-tmp` и отключённый cacheprovider, добавить `scripts/test.ps1` с проверкой абсолютного parent и leaf перед очисткой; проверить тестом защиты, что скрипт отказывается удалять путь вне `<repo>/.test-tmp`.
- [x] 3.2 Сузить `.gitignore` до `.test-tmp/`, заменить все документированные варианты тестовой команды единым entry point и проверить, что поиск `.test-tmp-` в отслеживаемых файлах не находит инструкций создания новых вариантов.
- [x] 3.3 Read-only командой перечислить текущие `.test-tmp-*`, проверить каждый resolved path на принадлежность корню проекта и соответствие шаблону, затем удалить только проверенные каталоги; дважды выполнить `scripts/test.ps1` и убедиться, что новых sibling-каталогов нет.
- [x] 3.4 Создать коммит только с test-workspace настройками и убедиться, что полный существующий набор больше не падает с `PermissionError` системного `%TEMP%`.

## 4. `[test]: Зафиксировано поведение голосового моста`

- [x] 4.1 Дополнить HTTP characterization tests для открытия навыка, пустой команды, всех служебных команд, wrong secret, allowlist и точной формы ответа; проверить новый contract-набор отдельно.
- [x] 4.2 Зафиксировать тестами immediate/deferred/failed/cancelled flow, дедупликацию concurrent webhook, запрет второго запроса в одной беседе, поколения и shutdown с активными задачами; проверить отсутствие реального ожидания через управляемые fakes/events.
- [x] 4.3 Добавить проверки приватности логов для реплик, токенов и полных идентификаторов; выполнить полный набор и убедиться, что существующий публичный контракт остаётся зелёным.

## 5. `[refactor]: Выделены доменная модель и порты приложения`

- [x] 5.1 Создать domain types для reply, conversation key и состояний job с валидируемыми переходами; проверить unit-тестами допустимые и запрещённые состояния без I/O.
- [x] 5.2 Создать узкие application ports для Gateway, jobs, cache, generations, atomic deferred completion, notifier, pending phrases, clock и id generation; проверить статически, что ports не импортируют infrastructure или presentation.
- [x] 5.3 Перенести `CommandIntent` во внутренний слой с совместимым re-export старого импорта; выполнить существующие тесты команд и полный набор.

## 6. `[refactor]: Изолировано хранилище SQLite`

- [x] 6.1 Перенести SQL в infrastructure persistence adapter, преобразовывать строки SQLite в типизированные domain-модели и сохранить текущую схему; проверить integration-тестом чтение существующей базы, созданной старой реализацией.
- [x] 6.2 Реализовать раздельные repository ports и атомарную запись completed job с notification outbox в одной транзакции; проверить rollback при искусственной ошибке второй операции.
- [x] 6.3 Покрыть initialize cleanup, jobs, cache retention/deduplication, generation increment, notification retries/delivery/cancellation и concurrent access; выполнить integration-набор SQLite и полный набор.
- [x] 6.4 Оставить временный совместимый re-export `Store` только при необходимости текущих импортов и проверить, что application/domain не импортируют `sqlite3`.

## 7. `[refactor]: Изолированы внешние интеграции`

- [x] 7.1 Перед переносом Gateway adapter повторно проверить пользовательский diff timeout; сохранить его семантику, не индексировать чужую правку отдельным коммитом и запросить решение владельца, если чистое разделение невозможно.
- [x] 7.2 Перенести OpenClaw HTTP client за `AssistantGateway`, выделить retry strategy с внедряемыми задержками и проверить contract-тестами payload, configurable timeout, 502/503/504 retries, network errors, invalid JSON и оба формата output text.
- [x] 7.3 Перенести Home Assistant и Glagol implementations за notifier/adapter contracts; проверить contract-тестами payload, безопасные ошибки, token refresh, private-address validation, mDNS и закрытие принадлежащих сессий.
- [x] 7.4 Сохранить совместимые re-export для публичных импортов на время миграции и выполнить полный тестовый набор без сетевого доступа.

## 8. `[refactor]: Выделена обработка служебных команд`

- [x] 8.1 Реализовать `CommandDispatcher` и отдельные handlers Help, Result, Cancel, NewDialog и Exit с явными зависимостями; проверить unit-тестом dispatch каждого intent и отсутствие перехвата обычной реплики.
- [x] 8.2 Перенести пользовательские ответы и side effects команд из HTTP-обработчика в handlers, сохранив точные текущие фразы; выполнить characterization tests команд.
- [x] 8.3 Удалить заменённую условную цепочку из transport слоя и проверить, что новый handler добавляется регистрацией без изменения controller.

## 9. `[refactor]: Выделена координация диалогов`

- [x] 9.1 Реализовать `ConversationService` для message, result, cancel и new-generation use cases с transport-neutral `Reply`; проверить unit-тестами все ветви через in-memory ports.
- [x] 9.2 Реализовать `RequestCoordinator` для inflight deduplication, Gateway tasks и keyed locks с освобождением записей; нагрузочным unit-тестом проверить один вызов на дубликаты, сериализацию беседы и пустые registries после завершения.
- [x] 9.3 Заменить callback deferred result именованной управляемой coroutine и проверить completion, failure, cancellation, notification wake и shutdown без потерянных задач.
- [x] 9.4 Выполнить полный набор, включая timing boundary около `alice_fast_timeout_seconds`, без изменения лимита webhook.

## 10. `[refactor]: Собрана чистая архитектура приложения`

- [x] 10.1 Выделить Alice DTO/mapper/router в presentation и оставить `openalice.app:create_app` стабильным entry point; проверить контракт обоих публичных маршрутов.
- [x] 10.2 Реализовать единственный composition root `build_runtime(settings, overrides)` для fake/live Gateway и notifier providers; проверить unit-тестами все комбинации настройки без открытия реальной сети.
- [x] 10.3 Централизовать lifespan и ровно однократное закрытие store, coordinator, worker и внешних клиентов при нормальном и аварийном выходе; проверить lifecycle tests.
- [x] 10.4 Добавить автоматические import contracts `presentation → application → domain` и `infrastructure → application/domain`, затем выполнить их вместе с полным набором.

## 11. `[test]: Расширено модульное покрытие проекта`

- [x] 11.1 Реорганизовать тесты по `unit`, `integration`, `contract`, `quality`, вынести общие builders/fakes в fixtures и проверить, что unit-набор не создаёт файлов и не открывает сеть.
- [x] 11.2 Добавить сфокусированные тесты config validators, text cleanup/shortening, Alice models, pending phrase strategy, typed logging и всех composition branches; выполнить каждый новый модуль отдельно.
- [x] 11.3 Добавить `pytest-cov`, включить line и branch coverage пакета `openalice` с `fail-under=90` и минимальными обоснованными исключениями; проверить успешный полный отчёт и отдельный отрицательный тест порога.
- [x] 11.4 Удалить устаревшие compatibility shims и дублирующие тесты только после достижения порога; выполнить полный набор повторно и проверить отсутствие импортов старых путей.

## 12. `[chore]: Добавлена единая проверка качества`

- [x] 12.1 Добавить и зафиксировать конфигурацию Ruff, mypy и import contracts для Python 3.13, обновить lock-файл; проверить установку dev group в чистом окружении.
- [x] 12.2 Исправить production package и тесты до нулевых ошибок format-check, lint и type-check, используя только точечные документированные исключения для сторонних SDK.
- [x] 12.3 Создать `scripts/check.ps1`, последовательно вызывающий статические проверки, архитектурные контракты, doc checks и единый test entry point; проверить ненулевой код при искусственно нарушенной проверке и зелёный результат после отката этой мутации.

## 13. `[test]: Расширена коллекция запросов Bruno`

- [x] 13.1 Разделить коллекцию на Smoke, Commands, Reliability, Security и отдельную Gateway Diagnostics; проверить, что OpenAlice-набор запускается без Gateway credentials в fake mode.
- [x] 13.2 Добавить запросы health, skill open, message, help, result, cancel, new dialog, exit, wrong secret, denied user, duplicate delivery и deferred flow с согласованными session/message identifiers.
- [x] 13.3 Добавить pre-request validation обязательных variables и assertions статуса, version, text, tts и end_session; намеренно нарушить локальный base URL и проверить понятный failed result, затем вернуть корректную настройку.
- [ ] 13.4 Выполнить Bruno smoke в fake mode и отдельно диагностический Gateway-запрос только с ротированным локальным токеном; сохранить результат проверки без секретов в Git или логах.

## 14. `[docs]: Унифицирована документация проекта`

- [x] 14.1 Сократить README до назначения, схемы, prerequisites, quick start, health/quality commands и ссылок; проверить, что подробные инструкции не дублируются.
- [x] 14.2 Создать `docs/index.md`, `architecture.md`, `setup.md`, `configuration.md`, `yandex-skill.md`, `notifications.md`, `operations.md`, `development.md`, `bruno.md`, `security.md` и `troubleshooting.md`, перенеся всю актуальную информацию из README.
- [x] 14.3 Описать в architecture точных участников и причины Adapter, Strategy, Command, Repository, Factory и Facade, а также явно неприменённые паттерны; сверить документ с фактическими imports и composition root.
- [x] 14.4 Добавить quality tests локальных Markdown-ссылок и соответствия переменных `docs/configuration.md` файлу `.env.example`; выполнить doc checks и полный quality-check.

## 15. `[chore]: Завершён архитектурный рефакторинг`

- [x] 15.1 Проверить `rg` на мёртвые импорты, старые пути, `.test-tmp-`, встроенные секреты и неиспользуемые compatibility notes; удалить только подтверждённый мёртвый код и повторить quality-check.
- [x] 15.2 Дважды выполнить полный `scripts/check.ps1`, убедиться в покрытии не ниже 90%, отсутствии сетевых обращений и отсутствии новых временных sibling-каталогов.
- [x] 15.3 Запустить OpenAlice в fake mode, проверить `/health` и полный Bruno smoke, затем корректно остановить приложение и убедиться по логам, что ресурсы закрылись без раскрытия реплик или идентификаторов.
- [x] 15.4 Просмотреть всю серию коммитов: каждый заголовок соответствует шаблону `[тип]: Описание`, каждый diff тематически независим, а пользовательская правка timeout либо сохранена вне серии, либо оформлена владельцем отдельно.

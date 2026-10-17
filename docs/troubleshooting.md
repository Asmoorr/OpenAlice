# Проверка и диагностика

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

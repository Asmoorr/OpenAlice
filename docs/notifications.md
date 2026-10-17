# Уведомления

## Home Assistant

Установите NOTIFICATIONS_ENABLED=true и NOTIFICATION_PROVIDER=home_assistant.
В локальном .env укажите HOME_ASSISTANT_URL, долгоживущий HOME_ASSISTANT_TOKEN
и HOME_ASSISTANT_ENTITY_ID нужного media_player. Станция должна быть доступна
в Home Assistant и поддерживать воспроизведение текста через play_media.

После сохранения отложенного ответа OpenAlice ставит уведомление в SQLite outbox.
Ошибка доставки не удаляет готовый ответ: его по-прежнему можно получить командой
«готово». Количество попыток и период опроса задаются настройками очереди.
Получение ответа и отмена запроса отменяют ещё не отправленные уведомления.

Все настройки перечислены в [справочнике конфигурации](configuration.md).

### Уведомление через Яндекс Станцию

Поддерживаются два взаимозаменяемых канала. Стабильный вариант работает через
REST API Home Assistant и компонент
[AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation). Установите
компонент через HACS, добавьте Станцию в Home Assistant и убедитесь, что у неё
есть сущность вида `media_player.yandex_station_mini`.

Создайте в профиле Home Assistant долгоживущий токен доступа, запишите его в
`HOME_ASSISTANT_TOKEN`, укажите сущность колонки в `HOME_ASSISTANT_ENTITY_ID` и
установите `NOTIFICATIONS_ENABLED=true`. Токен нельзя публиковать или добавлять
в Git.

Когда отложенный ответ готов, OpenAlice атомарно сохраняет ответ и уведомление в
SQLite. Фоновый worker отправляет короткую TTS-фразу через
`media_player.play_media`. Если Home Assistant недоступен, доставка повторяется,
но сам результат остаётся доступен по команде «готово». При получении или отмене
результата ещё не отправленное уведомление отменяется.

Для прямого подключения без Home Assistant используется неофициальный локальный
протокол Glagol. Компьютер и Станция должны находиться в одной локальной сети.
Сначала выполните интерактивную авторизацию и найдите колонку:

```powershell
.\.venv\Scripts\python.exe -m openalice.glagol_setup login
.\.venv\Scripts\python.exe -m openalice.glagol_setup discover
```

Первая команда покажет адрес и код входа Яндекса и сохранит полученные токены в
`./data/glagol_credentials.json`. Вторая выведет готовые значения параметров
устройств. Добавьте выбранные значения в `.env`, затем установите:

```dotenv
NOTIFICATIONS_ENABLED=true
NOTIFICATION_PROVIDER=glagol
GLAGOL_DEVICE_ID=идентификатор-из-discover
GLAGOL_PLATFORM=платформа-из-discover
GLAGOL_HOST=локальный-ip-из-discover
GLAGOL_PORT=1961
```

`GLAGOL_HOST` допустимо оставить пустым для автоматического mDNS-поиска.
Прямой канал зависит от закрытого протокола Яндекса и может перестать работать
после изменения прошивки или серверной авторизации. Сбой произнесения не теряет
подготовленный ответ: его по-прежнему можно получить командой «готово».

Токен ngrok в `.env` OpenAlice не добавляется. Он хранится в конфигурации самой
службы ngrok и берётся на странице
<https://dashboard.ngrok.com/get-started/your-authtoken>. Назначенный публичный
домен показан в Dashboard: <https://dashboard.ngrok.com/domains>.

Реальный `.env` должен быть в `.gitignore`; в репозитории хранится только
`.env.example` без секретов.

Сначала оставьте `ALICE_ALLOWED_USER_IDS` пустым. Во вкладке тестирования Яндекс
Диалогов посмотрите тело входного запроса, скопируйте
`session.user.user_id` в `.env` и перезапустите OpenAlice. Несколько разрешённых
идентификаторов указываются через запятую.

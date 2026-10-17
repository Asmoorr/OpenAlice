# Эксплуатация и автозапуск

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
   --factory --host 127.0.0.1 --port 8765`;
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
      url: http://127.0.0.1:8765
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
Invoke-RestMethod http://127.0.0.1:8765/health
Invoke-RestMethod `
  -Uri "https://example-name.ngrok-free.app/health" `
  -Headers @{ "ngrok-skip-browser-warning" = "1" }
```

Затем отправьте реплику во вкладке тестирования Яндекс Диалогов и запустите навык
на Станции. Автозапуск считается настроенным, только если вся цепочка поднялась
после перезагрузки без открытых терминалов.

# Русификатор TCG Card Shop Simulator

Русский язык добавляется прямо в таблицу локализации игры (I2 Localization) —
без мод-лоадеров, патчеров и перехвата текста. Ставится подменой одного файла,
удаляется возвратом бэкапа.

Русский занимает место французского: после установки выберите **Français** в
**Settings → Language** — игра заговорит по-русски. Отдельного пункта «Русский» нет:
меню языков в игре — фиксированный набор кнопок, и добавить в него пункт можно только
правкой сцен, чего мы сознательно не делаем. Французский на время установки пропадает.

> Шрифты трогать не нужно: в игре уже есть кириллический шрифт `RussianOutline`,
> подключённый в fallback основного шрифта.

## Что нужно

- **Python 3.9+** — [python.org/downloads](https://www.python.org/downloads/)
  (при установке отметьте «Add Python to PATH»)
- ~1.6 ГБ свободного места (собранный файл + бэкап оригинала)

## Установка

Положите папку `ru-translation` внутрь папки с игрой — рядом с `Card Shop Simulator.exe`:

```
TCG Card Shop Simulator/
├── Card Shop Simulator.exe
├── Card Shop Simulator_Data/
└── ru-translation/        <- сюда
```

Откройте терминал в папке `ru-translation` и выполните:

```bash
pip install -r requirements.txt
```

```bash
python tools/build_translation.py
```

```bash
python tools/install.py
```

Скрипт установки спросит подтверждение, сам сделает бэкап оригинала и подменит файл.
Запустите игру и выберите **Français** в настройках — это и есть русский.

Если папка с игрой в другом месте, укажите её явно:

```bash
python tools/build_translation.py --game "D:/Games/Steam/steamapps/common/TCG Card Shop Simulator"
```

## Удаление

```bash
python tools/install.py --restore
```

Вернёт оригинальный `resources.assets` из бэкапа. Альтернатива — проверка целостности
файлов в Steam (Свойства → Установленные файлы → Проверить целостность).

## Проверить текущее состояние

```bash
python tools/install.py --status
```

Покажет, есть ли бэкап, собран ли перевод и установлен ли сейчас русский.

## После обновления игры

Steam перезапишет `resources.assets`, и перевод слетит. Пересоберите и поставьте заново:

```bash
python tools/build_translation.py && python tools/install.py
```

Сборка всегда берёт за основу бэкап оригинала, если он есть, поэтому переводы не наслаиваются.
Если игра обновилась и строк стало больше — сначала перевытащите их (см. ниже).

## Как помочь с переводом

Переводится один файл — `translation/ru.json`:

```json
[
  { "key": "Buy buy buy!!", "en": "Buy buy buy!!", "ru": "" }
]
```

Заполняйте поле `ru`. Термины с пустым `ru` показываются на английском, поэтому
перевод можно ставить в игру на любой стадии готовности. После правок — пересобрать и установить.

Сводка по строкам лежит в `strings/`:

| Файл | Что внутри |
|---|---|
| `00_stats.json` | сводка по количествам |
| `01_i2_localization_full.json` | вся таблица I2: 2573 термина со всеми официальными переводами |
| `01_i2_translate_ru.csv` | то же в CSV, если удобнее таблицей |
| `02_game_data_strings.json` | текст из ScriptableObject'ов: карты, полки, товары, эффекты |
| `03_ui_text_static.json` | надписи, которых нет в таблице I2 |
| `04_i2_term_usage.json` | где в игре используется каждый термин — помогает с контекстом |
| `05_all_asset_strings.csv` | полный дамп: 68 887 строковых полей |
| `06_code_strings.json` | строки, зашитые в код (реплики покупателей и т.п.) |

## Перевытащить строки из игры

Нужно только если игра обновилась:

```bash
pip install UnityPy TypeTreeGeneratorAPI
```

```bash
python tools/extract_code.py "../Card Shop Simulator_Data/Managed" strings/raw
```

```bash
python tools/extract_all.py && python tools/build_outputs.py
```

`TypeTreeGeneratorAPI` требует установленного .NET 6+ runtime.

## Что не переводится

Реплики покупателей, зашитые прямо в `Assembly-CSharp.dll` (~554 строки, см.
`strings/06_code_strings.json`) — они идут мимо таблицы локализации и требуют правки кода.
Не входят в этот русификатор.

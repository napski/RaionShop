# RaionShop

Проект теперь состоит из **трех рабочих частей**:
1. `bot.py` — Telegram-бот (aiogram 3).
2. `web_panel.py` — HTTP backend API + Telegram Web App страница.
3. `web_panel.py` — также отдает веб-админ-панель (`/admin`).

## Что реализовано
- **Telegram bot**: каталог, покупка, профиль, Stars баланс, чеки, тикеты, админ-функции.
- **Web App** (`/webapp`):
  - просмотр профиля/истории,
  - каталог,
  - покупка,
  - пополнение,
  - создание и активация чеков.
- **Admin panel** (`/admin`):
  - просмотр пользователей,
  - просмотр заказов,
  - изменение баланса пользователя,
  - включение/выключение платежных систем.

## Быстрый запуск
1. Установить зависимости:
   ```bash
   pip install -r requirements.txt
   ```
2. Создать `.env` на основе `.env.example`.
3. Запустить бота:
   ```bash
   python bot.py
   ```
4. Запустить web backend + панели:
   ```bash
   uvicorn web_panel:app --host 0.0.0.0 --port 8000
   ```
5. Открыть:
   - Web App: `http://localhost:8000/webapp`
   - Admin panel: `http://localhost:8000/admin`

## Конфиг
- `BOT_TOKEN` — токен Telegram-бота.
- `ADMIN_IDS` — список ID админов через запятую.
- `DB_PATH` — путь до SQLite базы.

## Важно
- Для Telegram-бота все кнопки сделаны inline (`InlineKeyboardMarkup`).
- Веб-панели в текущей версии — рабочий MVP (демо/стартовая основа для продакшена).

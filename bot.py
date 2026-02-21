import asyncio
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Iterable

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "raionshop.db")
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

CATEGORIES = {
    "stars": "⭐ Telegram Stars",
    "nft": "🧩 Аренда NFT",
    "numbers": "📱 Виртуальные номера",
    "premium": "💎 Telegram Premium",
}

PAYMENT_SYSTEMS = ["Pally", "Platega", "CryptoBot", "FreeKassa"]

PRODUCTS = [
    ("stars_100", "stars", "100 Stars", 120, 90),
    ("stars_500", "stars", "500 Stars", 570, 470),
    ("nft_1d", "nft", "NFT аренда на 1 день", 250, 180),
    ("num_3d", "numbers", "Вирт. номер на 3 дня", 180, 130),
    ("premium_1m", "premium", "Premium на 1 месяц", 390, 320),
]


class InputState(StatesGroup):
    topup_amount = State()
    check_amount = State()
    activate_check = State()
    ticket_message = State()
    admin_user_id = State()
    admin_balance_value = State()
    admin_ticket_reply = State()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            stars_balance INTEGER NOT NULL DEFAULT 0,
            orders_count INTEGER NOT NULL DEFAULT 0,
            total_spent INTEGER NOT NULL DEFAULT 0,
            is_blocked INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            operation_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            cost INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_key TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            total INTEGER NOT NULL,
            status TEXT NOT NULL,
            payment_system TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            code TEXT PRIMARY KEY,
            creator_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            activated_by INTEGER,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            activated_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            sender_role TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_systems (
            name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    for item in PRODUCTS:
        cur.execute(
            """
            INSERT OR IGNORE INTO products (product_key, category, name, price, cost)
            VALUES (?, ?, ?, ?, ?)
            """,
            item,
        )
    for ps in PAYMENT_SYSTEMS:
        cur.execute(
            "INSERT OR IGNORE INTO payment_systems (name, enabled) VALUES (?, 1)",
            (ps,),
        )
    conn.commit()
    conn.close()


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def user_row(user_id: int, username: str | None = None) -> sqlite3.Row:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users(id, username) VALUES(?, ?)",
        (user_id, username or ""),
    )
    if username:
        cur.execute("UPDATE users SET username=? WHERE id=?", (username, user_id))
    conn.commit()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def add_transaction(user_id: int, op_type: str, amount: int, reason: str) -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO transactions(user_id, operation_type, amount, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, op_type, amount, reason, now()),
    )
    conn.commit()
    conn.close()


def kb(rows: Iterable[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def main_menu_keyboard(is_admin_user: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="menu:catalog")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="⭐ Баланс Stars", callback_data="menu:stars")],
        [InlineKeyboardButton(text="🎟 Чеки", callback_data="menu:checks")],
        [InlineKeyboardButton(text="🎫 Тикеты", callback_data="menu:tickets")],
    ]
    if is_admin_user:
        rows.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="menu:admin")])
    return kb(rows)


async def show_main_menu(target: Message | CallbackQuery) -> None:
    user = target.from_user
    if not user:
        return
    user_row(user.id, user.username)
    text = (
        "<b>RaionShop</b>\n"
        "Магазин цифровых услуг.\n"
        "Выберите раздел:"
    )
    markup = main_menu_keyboard(is_admin(user.id))
    if isinstance(target, Message):
        await target.answer(text, reply_markup=markup)
    else:
        await target.message.edit_text(text, reply_markup=markup)


def get_history(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


async def show_profile(cq: CallbackQuery) -> None:
    user = cq.from_user
    if not user:
        return
    row = user_row(user.id, user.username)
    history = get_history(user.id, 5)
    history_text = "\n".join(
        f"• {item['created_at']} | {item['operation_type']} | {item['amount']} | {item['reason']}"
        for item in history
    ) or "Нет операций"
    text = (
        "<b>Профиль</b>\n"
        f"ID: <code>{row['id']}</code>\n"
        f"Username: @{row['username'] or '-'}\n"
        f"Баланс Stars: <b>{row['stars_balance']}</b>\n"
        f"Заказы: {row['orders_count']}\n"
        f"Сумма покупок: {row['total_spent']}\n\n"
        f"<b>История:</b>\n{history_text}"
    )
    await cq.message.edit_text(
        text,
        reply_markup=kb([[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")]]),
    )


async def show_catalog(cq: CallbackQuery) -> None:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"catalog:{key}")]
        for key, name in CATEGORIES.items()
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")])
    await cq.message.edit_text("<b>Каталог</b>\nВыберите категорию:", reply_markup=kb(rows))


async def show_category(cq: CallbackQuery, category: str) -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM products WHERE category=? AND active=1 ORDER BY id",
        (category,),
    )
    products = cur.fetchall()
    conn.close()
    rows = [
        [
            InlineKeyboardButton(
                text=f"{prod['name']} — {prod['price']}⭐",
                callback_data=f"buy:{prod['product_key']}:1",
            )
        ]
        for prod in products
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Категории", callback_data="menu:catalog")])
    await cq.message.edit_text(
        f"<b>{CATEGORIES.get(category, category)}</b>\nВыберите товар:",
        reply_markup=kb(rows),
    )


async def choose_payment(cq: CallbackQuery, product_key: str, quantity: int) -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE product_key=?", (product_key,))
    product = cur.fetchone()
    cur.execute("SELECT * FROM payment_systems WHERE enabled=1 ORDER BY name")
    systems = cur.fetchall()
    conn.close()
    if not product:
        await cq.answer("Товар не найден", show_alert=True)
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"Оплатить через {ps['name']}",
                callback_data=f"pay:{product_key}:{quantity}:{ps['name']}",
            )
        ]
        for ps in systems
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:catalog")])
    text = (
        f"<b>{product['name']}</b>\n"
        f"Количество: {quantity}\n"
        f"Сумма: <b>{product['price'] * quantity}</b> Stars\n"
        "Выберите платежную систему:"
    )
    await cq.message.edit_text(text, reply_markup=kb(rows))


async def create_order(cq: CallbackQuery, product_key: str, quantity: int, payment: str) -> None:
    user = cq.from_user
    if not user:
        return
    usr = user_row(user.id, user.username)
    if usr["is_blocked"]:
        await cq.answer("Вы заблокированы", show_alert=True)
        return

    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE product_key=?", (product_key,))
    product = cur.fetchone()
    if not product:
        conn.close()
        await cq.answer("Товар недоступен", show_alert=True)
        return

    total = product["price"] * quantity
    if usr["stars_balance"] < total:
        conn.close()
        await cq.message.edit_text(
            "Недостаточно Stars. Пополните баланс.",
            reply_markup=kb(
                [
                    [InlineKeyboardButton(text="⭐ Баланс", callback_data="menu:stars")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")],
                ]
            ),
        )
        return

    cur.execute(
        "INSERT INTO orders(user_id, product_key, quantity, total, status, payment_system, created_at) VALUES (?, ?, ?, ?, 'paid', ?, ?)",
        (user.id, product_key, quantity, total, payment, now()),
    )
    cur.execute(
        "UPDATE users SET stars_balance=stars_balance-?, orders_count=orders_count+1, total_spent=total_spent+? WHERE id=?",
        (total, total, user.id),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()

    add_transaction(user.id, "purchase", -total, f"order:{order_id}")

    text = (
        f"✅ Заказ #{order_id} оплачен\n"
        f"Товар: {product['name']}\n"
        f"Количество: {quantity}\n"
        f"Сумма: {total} Stars\n"
        f"Оплата: {payment}\n\n"
        "Товар выдан автоматически (demo-mode)."
    )
    await cq.message.edit_text(
        text,
        reply_markup=kb([[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu:root")]]),
    )


async def show_stars(cq: CallbackQuery) -> None:
    user = cq.from_user
    if not user:
        return
    row = user_row(user.id, user.username)
    history = get_history(user.id, 8)
    topups = [h for h in history if h["operation_type"] == "topup"]
    topup_text = "\n".join(
        f"• {t['created_at']} +{t['amount']} ({t['reason']})" for t in topups
    ) or "Нет пополнений"
    await cq.message.edit_text(
        f"<b>Баланс Stars</b>\nТекущий баланс: <b>{row['stars_balance']}</b>\n\n<b>История пополнений:</b>\n{topup_text}",
        reply_markup=kb(
            [
                [InlineKeyboardButton(text="➕ Пополнить (demo)", callback_data="stars:topup")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")],
            ]
        ),
    )


async def show_checks(cq: CallbackQuery) -> None:
    await cq.message.edit_text(
        "<b>Система чеков</b>\nВыберите действие:",
        reply_markup=kb(
            [
                [InlineKeyboardButton(text="🧾 Создать чек", callback_data="checks:create")],
                [InlineKeyboardButton(text="✅ Активировать чек", callback_data="checks:activate")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")],
            ]
        ),
    )


async def show_tickets(cq: CallbackQuery) -> None:
    user = cq.from_user
    if not user:
        return
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 5", (user.id,))
    tickets = cur.fetchall()
    conn.close()
    body = "\n".join(
        f"• #{t['id']} | {t['status']} | {t['updated_at']}" for t in tickets
    ) or "Нет тикетов"
    await cq.message.edit_text(
        f"<b>Тикеты</b>\n{body}",
        reply_markup=kb(
            [
                [InlineKeyboardButton(text="✍️ Создать тикет", callback_data="tickets:create")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")],
            ]
        ),
    )


async def show_admin(cq: CallbackQuery) -> None:
    if not cq.from_user or not is_admin(cq.from_user.id):
        await cq.answer("Нет доступа", show_alert=True)
        return
    await cq.message.edit_text(
        "<b>Админ-панель</b>",
        reply_markup=kb(
            [
                [InlineKeyboardButton(text="👥 Пользователь по ID", callback_data="admin:user")],
                [InlineKeyboardButton(text="📦 Последние заказы", callback_data="admin:orders")],
                [InlineKeyboardButton(text="💳 Платежные системы", callback_data="admin:payments")],
                [InlineKeyboardButton(text="📊 Аналитика", callback_data="admin:analytics")],
                [InlineKeyboardButton(text="🎫 Тикеты", callback_data="admin:tickets")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")],
            ]
        ),
    )


def analytics_text() -> str:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(total),0) AS turnover FROM orders WHERE status='paid'")
    turnover = cur.fetchone()["turnover"]
    cur.execute("SELECT product_key, quantity, payment_system, total FROM orders WHERE status='paid'")
    orders = cur.fetchall()
    total_profit = 0
    by_pay: dict[str, int] = {}
    product_map: dict[str, tuple[int, int]] = {}
    cur.execute("SELECT product_key, price, cost FROM products")
    for p in cur.fetchall():
        product_map[p["product_key"]] = (p["price"], p["cost"])

    for order in orders:
        price, cost = product_map.get(order["product_key"], (0, 0))
        commission = int(order["total"] * 0.03)
        profit = (price - cost) * order["quantity"] - commission
        total_profit += profit
        by_pay[order["payment_system"]] = by_pay.get(order["payment_system"], 0) + profit

    cur.execute(
        "SELECT id, total_spent, orders_count FROM users ORDER BY total_spent DESC LIMIT 3"
    )
    top_users = cur.fetchall()
    conn.close()

    top_text = "\n".join(
        f"• <code>{u['id']}</code>: {u['total_spent']} Stars ({u['orders_count']} транз.)"
        for u in top_users
    ) or "Нет данных"
    by_pay_text = "\n".join(f"• {k}: {v}" for k, v in by_pay.items()) or "Нет данных"

    return (
        "<b>Аналитика</b>\n"
        f"Оборот: {turnover}\n"
        f"Общая прибыль: {total_profit}\n\n"
        f"<b>Прибыль по платежкам:</b>\n{by_pay_text}\n\n"
        f"<b>Топ пользователи:</b>\n{top_text}"
    )


def register_handlers(dp: Dispatcher) -> None:
    @dp.message(Command("start"))
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        await show_main_menu(message)

    @dp.callback_query(F.data == "menu:root")
    async def cb_root(cq: CallbackQuery, state: FSMContext):
        await state.clear()
        await show_main_menu(cq)
        await cq.answer()

    @dp.callback_query(F.data == "menu:profile")
    async def cb_profile(cq: CallbackQuery):
        await show_profile(cq)
        await cq.answer()

    @dp.callback_query(F.data == "menu:catalog")
    async def cb_catalog(cq: CallbackQuery):
        await show_catalog(cq)
        await cq.answer()

    @dp.callback_query(F.data.startswith("catalog:"))
    async def cb_category(cq: CallbackQuery):
        _, category = cq.data.split(":", 1)
        await show_category(cq, category)
        await cq.answer()

    @dp.callback_query(F.data.startswith("buy:"))
    async def cb_buy(cq: CallbackQuery):
        _, product_key, qty = cq.data.split(":")
        await choose_payment(cq, product_key, int(qty))
        await cq.answer()

    @dp.callback_query(F.data.startswith("pay:"))
    async def cb_pay(cq: CallbackQuery):
        _, product_key, qty, payment = cq.data.split(":")
        await create_order(cq, product_key, int(qty), payment)
        await cq.answer()

    @dp.callback_query(F.data == "menu:stars")
    async def cb_stars(cq: CallbackQuery):
        await show_stars(cq)
        await cq.answer()

    @dp.callback_query(F.data == "stars:topup")
    async def cb_topup(cq: CallbackQuery, state: FSMContext):
        await state.set_state(InputState.topup_amount)
        await cq.message.edit_text(
            "Введите сумму пополнения Stars (целое число):",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:stars")]]),
        )
        await cq.answer()

    @dp.message(InputState.topup_amount)
    async def st_topup(message: Message, state: FSMContext):
        if not message.from_user:
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("Введите корректную сумму.")
            return
        amount = int(text)
        conn = connect_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET stars_balance=stars_balance+? WHERE id=?",
            (amount, message.from_user.id),
        )
        conn.commit()
        conn.close()
        add_transaction(message.from_user.id, "topup", amount, "demo_topup")
        await state.clear()
        await message.answer(
            f"✅ Баланс пополнен на {amount} Stars.",
            reply_markup=main_menu_keyboard(is_admin(message.from_user.id)),
        )

    @dp.callback_query(F.data == "menu:checks")
    async def cb_checks(cq: CallbackQuery):
        await show_checks(cq)
        await cq.answer()

    @dp.callback_query(F.data == "checks:create")
    async def cb_check_create(cq: CallbackQuery, state: FSMContext):
        await state.set_state(InputState.check_amount)
        await cq.message.edit_text(
            "Введите сумму чека:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:checks")]]),
        )
        await cq.answer()

    @dp.message(InputState.check_amount)
    async def st_check_create(message: Message, state: FSMContext):
        if not message.from_user:
            return
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) <= 0:
            await message.answer("Введите положительное целое число.")
            return
        amount = int(text)
        row = user_row(message.from_user.id, message.from_user.username)
        if row["stars_balance"] < amount:
            await message.answer("Недостаточно Stars для создания чека.")
            return
        code = uuid.uuid4().hex[:10].upper()

        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET stars_balance=stars_balance-? WHERE id=?", (amount, message.from_user.id))
        cur.execute(
            "INSERT INTO checks(code, creator_id, amount, status, created_at) VALUES (?, ?, ?, 'new', ?)",
            (code, message.from_user.id, amount, now()),
        )
        conn.commit()
        conn.close()

        add_transaction(message.from_user.id, "check_create", -amount, f"check:{code}")
        await state.clear()
        await message.answer(
            f"✅ Чек создан\nКод: <code>{code}</code>\nСумма: {amount} Stars",
            reply_markup=main_menu_keyboard(is_admin(message.from_user.id)),
        )

    @dp.callback_query(F.data == "checks:activate")
    async def cb_check_activate(cq: CallbackQuery, state: FSMContext):
        await state.set_state(InputState.activate_check)
        await cq.message.edit_text(
            "Введите код чека для активации:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:checks")]]),
        )
        await cq.answer()

    @dp.message(InputState.activate_check)
    async def st_check_activate(message: Message, state: FSMContext):
        if not message.from_user:
            return
        code = (message.text or "").strip().upper()
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM checks WHERE code=?", (code,))
        chk = cur.fetchone()
        if not chk:
            conn.close()
            await message.answer("Чек не найден.")
            return
        if chk["status"] != "new":
            conn.close()
            await message.answer("Чек уже активирован.")
            return
        if chk["creator_id"] == message.from_user.id:
            conn.close()
            await message.answer("Нельзя активировать свой чек.")
            return

        cur.execute(
            "UPDATE checks SET status='activated', activated_by=?, activated_at=? WHERE code=?",
            (message.from_user.id, now(), code),
        )
        cur.execute(
            "UPDATE users SET stars_balance=stars_balance+? WHERE id=?",
            (chk["amount"], message.from_user.id),
        )
        conn.commit()
        conn.close()

        add_transaction(message.from_user.id, "check_activate", chk["amount"], f"check:{code}")
        await state.clear()
        await message.answer(
            f"✅ Чек {code} активирован на {chk['amount']} Stars.",
            reply_markup=main_menu_keyboard(is_admin(message.from_user.id)),
        )

    @dp.callback_query(F.data == "menu:tickets")
    async def cb_tickets(cq: CallbackQuery):
        await show_tickets(cq)
        await cq.answer()

    @dp.callback_query(F.data == "tickets:create")
    async def cb_ticket_create(cq: CallbackQuery, state: FSMContext):
        await state.set_state(InputState.ticket_message)
        await cq.message.edit_text(
            "Введите сообщение для тикета:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:tickets")]]),
        )
        await cq.answer()

    @dp.message(InputState.ticket_message)
    async def st_ticket_message(message: Message, state: FSMContext):
        if not message.from_user:
            return
        text = (message.text or "").strip()
        if len(text) < 5:
            await message.answer("Сообщение слишком короткое.")
            return
        conn = connect_db()
        cur = conn.cursor()
        created = now()
        cur.execute(
            "INSERT INTO tickets(user_id, status, created_at, updated_at) VALUES (?, 'open', ?, ?)",
            (message.from_user.id, created, created),
        )
        ticket_id = cur.lastrowid
        cur.execute(
            "INSERT INTO ticket_messages(ticket_id, sender_role, message, created_at) VALUES (?, 'user', ?, ?)",
            (ticket_id, text, created),
        )
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(
            f"✅ Тикет #{ticket_id} создан.",
            reply_markup=main_menu_keyboard(is_admin(message.from_user.id)),
        )

    @dp.callback_query(F.data == "menu:admin")
    async def cb_admin(cq: CallbackQuery):
        await show_admin(cq)
        await cq.answer()

    @dp.callback_query(F.data == "admin:user")
    async def cb_admin_user(cq: CallbackQuery, state: FSMContext):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        await state.set_state(InputState.admin_user_id)
        await cq.message.edit_text(
            "Введите ID пользователя:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin")]]),
        )
        await cq.answer()

    @dp.message(InputState.admin_user_id)
    async def st_admin_user(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id):
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("ID должен быть числом")
            return
        uid = int(text)
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
        conn.close()
        if not row:
            await message.answer("Пользователь не найден")
            return
        await state.clear()
        status = "🔒 Заблокирован" if row["is_blocked"] else "🟢 Активен"
        await message.answer(
            f"ID: {row['id']}\n@{row['username']}\nБаланс: {row['stars_balance']}\n{status}",
            reply_markup=kb(
                [
                    [InlineKeyboardButton(text="✏️ Изменить баланс", callback_data=f"admin:setbal:{uid}")],
                    [InlineKeyboardButton(text="🔁 Блок/разблок", callback_data=f"admin:toggle:{uid}")],
                    [InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")],
                ]
            ),
        )

    @dp.callback_query(F.data.startswith("admin:setbal:"))
    async def cb_admin_setbal(cq: CallbackQuery, state: FSMContext):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        uid = int(cq.data.split(":")[-1])
        await state.set_state(InputState.admin_balance_value)
        await state.update_data(target_user=uid)
        await cq.message.edit_text(
            "Введите новый баланс Stars:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:admin")]]),
        )
        await cq.answer()

    @dp.message(InputState.admin_balance_value)
    async def st_admin_setbal(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id):
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("Введите целое число")
            return
        balance = int(text)
        data = await state.get_data()
        uid = data.get("target_user")
        if not uid:
            await message.answer("Ошибка состояния")
            return
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET stars_balance=? WHERE id=?", (balance, uid))
        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(
            f"✅ Баланс пользователя {uid} установлен: {balance}",
            reply_markup=main_menu_keyboard(True),
        )

    @dp.callback_query(F.data.startswith("admin:toggle:"))
    async def cb_admin_toggle(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        uid = int(cq.data.split(":")[-1])
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_blocked=1-is_blocked WHERE id=?", (uid,))
        conn.commit()
        cur.execute("SELECT is_blocked FROM users WHERE id=?", (uid,))
        state = cur.fetchone()["is_blocked"]
        conn.close()
        await cq.answer("Обновлено")
        await cq.message.edit_text(
            f"Пользователь {uid} теперь {'заблокирован' if state else 'разблокирован'}.",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")]]),
        )

    @dp.callback_query(F.data == "admin:orders")
    async def cb_admin_orders(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()
        text = "\n".join(
            f"#{r['id']} | user:{r['user_id']} | {r['product_key']} | {r['total']} | {r['status']} | {r['payment_system']}"
            for r in rows
        ) or "Заказов нет"
        await cq.message.edit_text(
            f"<b>Последние заказы</b>\n{text}",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")]]),
        )
        await cq.answer()

    @dp.callback_query(F.data == "admin:payments")
    async def cb_admin_payments(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM payment_systems ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if r['enabled'] else '🔴'} {r['name']}",
                    callback_data=f"admin:paytoggle:{r['name']}",
                )
            ]
            for r in rows
        ]
        buttons.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")])
        await cq.message.edit_text("<b>Платежные системы</b>", reply_markup=kb(buttons))
        await cq.answer()

    @dp.callback_query(F.data.startswith("admin:paytoggle:"))
    async def cb_admin_paytoggle(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        name = cq.data.split(":", 2)[-1]
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE payment_systems SET enabled=1-enabled WHERE name=?", (name,))
        conn.commit()
        conn.close()
        await cb_admin_payments(cq)

    @dp.callback_query(F.data == "admin:analytics")
    async def cb_admin_analytics(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        await cq.message.edit_text(
            analytics_text(),
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")]]),
        )
        await cq.answer()

    @dp.callback_query(F.data == "admin:tickets")
    async def cb_admin_tickets(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT 10")
        tickets = cur.fetchall()
        conn.close()
        rows = [
            [
                InlineKeyboardButton(
                    text=f"#{t['id']} | user {t['user_id']} | {t['status']}",
                    callback_data=f"admin:ticket:{t['id']}",
                )
            ]
            for t in tickets
        ]
        rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="menu:admin")])
        await cq.message.edit_text("<b>Тикеты</b>", reply_markup=kb(rows))
        await cq.answer()

    @dp.callback_query(F.data.startswith("admin:ticket:"))
    async def cb_admin_ticket(cq: CallbackQuery, state: FSMContext):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        ticket_id = int(cq.data.split(":")[-1])
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id", (ticket_id,))
        msgs = cur.fetchall()
        cur.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,))
        ticket = cur.fetchone()
        conn.close()
        if not ticket:
            await cq.answer("Тикет не найден", show_alert=True)
            return
        body = "\n".join(f"[{m['sender_role']}] {m['message']}" for m in msgs) or "Сообщений нет"
        await state.update_data(ticket_id=ticket_id)
        await cq.message.edit_text(
            f"<b>Тикет #{ticket_id}</b> ({ticket['status']})\n{body}",
            reply_markup=kb(
                [
                    [InlineKeyboardButton(text="💬 Ответить", callback_data="admin:reply_ticket")],
                    [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"admin:close_ticket:{ticket_id}")],
                    [InlineKeyboardButton(text="⬅️ К тикетам", callback_data="admin:tickets")],
                ]
            ),
        )
        await cq.answer()

    @dp.callback_query(F.data == "admin:reply_ticket")
    async def cb_admin_reply_ticket(cq: CallbackQuery, state: FSMContext):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        await state.set_state(InputState.admin_ticket_reply)
        await cq.message.edit_text(
            "Введите ответ пользователю:",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin:tickets")]]),
        )
        await cq.answer()

    @dp.message(InputState.admin_ticket_reply)
    async def st_admin_reply_ticket(message: Message, state: FSMContext, bot: Bot):
        if not message.from_user or not is_admin(message.from_user.id):
            return
        text = (message.text or "").strip()
        if len(text) < 2:
            await message.answer("Слишком короткий ответ")
            return
        data = await state.get_data()
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            await message.answer("Тикет не выбран")
            return
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,))
        ticket = cur.fetchone()
        if not ticket:
            conn.close()
            await message.answer("Тикет не найден")
            return
        cur.execute(
            "INSERT INTO ticket_messages(ticket_id, sender_role, message, created_at) VALUES (?, 'admin', ?, ?)",
            (ticket_id, text, now()),
        )
        cur.execute("UPDATE tickets SET status='in_progress', updated_at=? WHERE id=?", (now(), ticket_id))
        conn.commit()
        conn.close()

        await bot.send_message(
            ticket["user_id"],
            f"📩 Ответ по тикету #{ticket_id}:\n{text}",
            reply_markup=main_menu_keyboard(is_admin(ticket["user_id"])),
        )
        await state.clear()
        await message.answer("Ответ отправлен.", reply_markup=main_menu_keyboard(True))

    @dp.callback_query(F.data.startswith("admin:close_ticket:"))
    async def cb_admin_close_ticket(cq: CallbackQuery):
        if not cq.from_user or not is_admin(cq.from_user.id):
            await cq.answer("Нет доступа", show_alert=True)
            return
        ticket_id = int(cq.data.split(":")[-1])
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE tickets SET status='closed', updated_at=? WHERE id=?", (now(), ticket_id))
        conn.commit()
        cur.execute("SELECT user_id FROM tickets WHERE id=?", (ticket_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            try:
                await cq.bot.send_message(
                    row["user_id"],
                    f"✅ Тикет #{ticket_id} закрыт администратором.",
                    reply_markup=main_menu_keyboard(is_admin(row["user_id"])),
                )
            except Exception:
                pass
        await cq.message.edit_text(
            f"Тикет #{ticket_id} закрыт.",
            reply_markup=kb([[InlineKeyboardButton(text="⬅️ К тикетам", callback_data="admin:tickets")]]),
        )
        await cq.answer()


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Set BOT_TOKEN in .env")
    init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

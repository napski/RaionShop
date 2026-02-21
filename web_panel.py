import os
import sqlite3
import uuid
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "raionshop.db")
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

PAYMENT_SYSTEMS = ["Pally", "Platega", "CryptoBot", "FreeKassa"]
PRODUCTS = [
    ("stars_100", "stars", "100 Stars", 120, 90),
    ("stars_500", "stars", "500 Stars", 570, 470),
    ("nft_1d", "nft", "NFT аренда на 1 день", 250, 180),
    ("num_3d", "numbers", "Вирт. номер на 3 дня", 180, 130),
    ("premium_1m", "premium", "Premium на 1 месяц", 390, 320),
]

app = FastAPI(title="RaionShop Web API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class TopupPayload(BaseModel):
    user_id: int
    amount: int


class BuyPayload(BaseModel):
    user_id: int
    product_key: str
    quantity: int = 1
    payment_system: str


class CheckCreatePayload(BaseModel):
    user_id: int
    amount: int


class CheckActivatePayload(BaseModel):
    user_id: int
    code: str


class AdminBalancePayload(BaseModel):
    user_id: int
    balance: int


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
        CREATE TABLE IF NOT EXISTS payment_systems (
            name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    for item in PRODUCTS:
        cur.execute(
            "INSERT OR IGNORE INTO products (product_key, category, name, price, cost) VALUES (?, ?, ?, ?, ?)",
            item,
        )
    for ps in PAYMENT_SYSTEMS:
        cur.execute("INSERT OR IGNORE INTO payment_systems (name, enabled) VALUES (?, 1)", (ps,))
    conn.commit()
    conn.close()


def ensure_user(user_id: int) -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(id, username) VALUES (?, '')", (user_id,))
    conn.commit()
    conn.close()


def add_tx(user_id: int, op_type: str, amount: int, reason: str) -> None:
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions(user_id, operation_type, amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, op_type, amount, reason, now()),
    )
    conn.commit()
    conn.close()


def admin_guard(admin_id: int | None) -> None:
    if not admin_id or admin_id not in ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/webapp", response_class=HTMLResponse)
def webapp_page(request: Request):
    return templates.TemplateResponse("webapp.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/api/catalog")
def api_catalog():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT product_key, category, name, price, active FROM products WHERE active=1 ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get("/api/user/{user_id}")
def api_user(user_id: int):
    ensure_user(user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
    user = dict(cur.fetchone())
    cur.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,))
    history = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"user": user, "history": history}


@app.post("/api/topup")
def api_topup(payload: TopupPayload):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    ensure_user(payload.user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET stars_balance=stars_balance+? WHERE id=?", (payload.amount, payload.user_id))
    conn.commit()
    conn.close()
    add_tx(payload.user_id, "topup", payload.amount, "webapp_topup")
    return {"ok": True}


@app.post("/api/buy")
def api_buy(payload: BuyPayload):
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be > 0")
    ensure_user(payload.user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT enabled FROM payment_systems WHERE name=?", (payload.payment_system,))
    ps = cur.fetchone()
    if not ps or not ps["enabled"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Payment system disabled")
    cur.execute("SELECT * FROM products WHERE product_key=? AND active=1", (payload.product_key,))
    product = cur.fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    cur.execute("SELECT * FROM users WHERE id=?", (payload.user_id,))
    user = cur.fetchone()
    if user["is_blocked"]:
        conn.close()
        raise HTTPException(status_code=403, detail="User blocked")

    total = product["price"] * payload.quantity
    if user["stars_balance"] < total:
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient Stars")

    cur.execute(
        "INSERT INTO orders(user_id, product_key, quantity, total, status, payment_system, created_at) VALUES (?, ?, ?, ?, 'paid', ?, ?)",
        (payload.user_id, payload.product_key, payload.quantity, total, payload.payment_system, now()),
    )
    order_id = cur.lastrowid
    cur.execute(
        "UPDATE users SET stars_balance=stars_balance-?, orders_count=orders_count+1, total_spent=total_spent+? WHERE id=?",
        (total, total, payload.user_id),
    )
    conn.commit()
    conn.close()
    add_tx(payload.user_id, "purchase", -total, f"order:{order_id}")
    return {"ok": True, "order_id": order_id, "total": total}


@app.post("/api/checks/create")
def api_check_create(payload: CheckCreatePayload):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    ensure_user(payload.user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT stars_balance FROM users WHERE id=?", (payload.user_id,))
    user = cur.fetchone()
    if user["stars_balance"] < payload.amount:
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient Stars")
    code = uuid.uuid4().hex[:10].upper()
    cur.execute("UPDATE users SET stars_balance=stars_balance-? WHERE id=?", (payload.amount, payload.user_id))
    cur.execute(
        "INSERT INTO checks(code, creator_id, amount, status, created_at) VALUES (?, ?, ?, 'new', ?)",
        (code, payload.user_id, payload.amount, now()),
    )
    conn.commit()
    conn.close()
    add_tx(payload.user_id, "check_create", -payload.amount, f"check:{code}")
    return {"ok": True, "code": code}


@app.post("/api/checks/activate")
def api_check_activate(payload: CheckActivatePayload):
    ensure_user(payload.user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM checks WHERE code=?", (payload.code.upper(),))
    check = cur.fetchone()
    if not check:
        conn.close()
        raise HTTPException(status_code=404, detail="Check not found")
    if check["status"] != "new":
        conn.close()
        raise HTTPException(status_code=400, detail="Check already activated")
    if check["creator_id"] == payload.user_id:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot activate own check")

    cur.execute(
        "UPDATE checks SET status='activated', activated_by=?, activated_at=? WHERE code=?",
        (payload.user_id, now(), payload.code.upper()),
    )
    cur.execute("UPDATE users SET stars_balance=stars_balance+? WHERE id=?", (check["amount"], payload.user_id))
    conn.commit()
    conn.close()
    add_tx(payload.user_id, "check_activate", check["amount"], f"check:{payload.code.upper()}")
    return {"ok": True, "amount": check["amount"]}


@app.get("/api/admin/orders")
def api_admin_orders(x_admin_id: int | None = Header(default=None)):
    admin_guard(x_admin_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get("/api/admin/users")
def api_admin_users(x_admin_id: int | None = Header(default=None)):
    admin_guard(x_admin_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY id DESC LIMIT 100")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/admin/user/balance")
def api_admin_balance(payload: AdminBalancePayload, x_admin_id: int | None = Header(default=None)):
    admin_guard(x_admin_id)
    ensure_user(payload.user_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET stars_balance=? WHERE id=?", (payload.balance, payload.user_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/admin/payment/{name}/toggle")
def api_admin_payment_toggle(name: str, x_admin_id: int | None = Header(default=None)):
    admin_guard(x_admin_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("UPDATE payment_systems SET enabled=1-enabled WHERE name=?", (name,))
    conn.commit()
    cur.execute("SELECT enabled FROM payment_systems WHERE name=?", (name,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Payment system not found")
    return {"ok": True, "enabled": bool(row["enabled"])}


@app.get("/api/admin/payment")
def api_admin_payment_list(x_admin_id: int | None = Header(default=None)):
    admin_guard(x_admin_id)
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM payment_systems ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

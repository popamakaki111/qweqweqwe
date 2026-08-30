import os
import sqlite3
import requests
import telebot

from telebot import types


# ============================================================
# CONFIG
# ============================================================

# НЕ ХРАНИ ТОКЕНЫ В КОДЕ.
# Windows PowerShell:
# $env:BOT_TOKEN="..."
# $env:CRYPTO_PAY_TOKEN="..."
#
# Linux:
# export BOT_TOKEN="..."
# export CRYPTO_PAY_TOKEN="..."

BOT_TOKEN = '8880021634:AAG1LMSMsax5XRFFHzgaeLIgJlXrMEoWc6s'
CRYPTO_PAY_TOKEN = '626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ'

if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. "
        "Добавь переменную окружения BOT_TOKEN."
    )

if not CRYPTO_PAY_TOKEN:
    raise RuntimeError(
        "Не задан CRYPTO_PAY_TOKEN. "
        "Добавь переменную окружения CRYPTO_PAY_TOKEN."
    )


ADMIN_IDS = {
    6043107587
}

SUPPORT_USERNAME = "nomerzad"

REFERRAL_PERCENT = 10.0
MIN_REFERRAL_WITHDRAWAL = 1.0

CRYPTO_API_URL = "https://pay.crypt.bot/api"


# ============================================================
# PATHS
# ============================================================

# Railway:
# Если подключить Railway Volume, укажи mount path /data.
# По умолчанию база будет храниться в /data/tabler.db.
# Путь можно изменить переменной окружения DATABASE_PATH.
DB_NAME = os.getenv("DATABASE_PATH", "/data/tabler.db")

# На случай локального запуска или отсутствия /data
# создаём каталог автоматически.
os.makedirs(os.path.dirname(DB_NAME), exist_ok=True)


# ============================================================
# BOT
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

# Состояния вывода.
# Для одного процесса этого достаточно.
withdrawal_states = set()


# ============================================================
# DATABASE
# ============================================================

def get_db():
    """
    Создаёт соединение с SQLite.
    База автоматически создаётся по пути DATABASE_PATH (по умолчанию /data/tabler.db)
    """
    conn = sqlite3.connect(
        DB_NAME,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    # Чуть лучше защищает от проблем при одновременной записи.
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db():

    os.makedirs(
        os.path.dirname(DB_NAME),
        exist_ok=True
    )

    conn = get_db()
    cur = conn.cursor()

    # ========================================================
    # USERS
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            balance REAL NOT NULL DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            referral_earnings REAL NOT NULL DEFAULT 0,
            referral_balance REAL NOT NULL DEFAULT 0
        )
    """)

    # ========================================================
    # MIGRATION USERS
    # ========================================================

    cur.execute("PRAGMA table_info(users)")

    columns = {
        row["name"]
        for row in cur.fetchall()
    }

    if "balance" not in columns:
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN balance REAL NOT NULL DEFAULT 0
        """)

    if "referrer_id" not in columns:
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN referrer_id INTEGER DEFAULT NULL
        """)

    if "referral_earnings" not in columns:
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN referral_earnings REAL NOT NULL DEFAULT 0
        """)

    if "referral_balance" not in columns:
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN referral_balance REAL NOT NULL DEFAULT 0
        """)

    # ========================================================
    # REFERRAL WITHDRAWALS
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referral_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            transfer_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # PAYMENTS
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # PRODUCTS
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # ========================================================
    # STOCK
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            sold INTEGER NOT NULL DEFAULT 0,
            buyer_id INTEGER
        )
    """)

    # ========================================================
    # PURCHASES
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            stock_id INTEGER NOT NULL,
            price REAL NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # BALANCE HISTORY
    # ========================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS balance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            admin_id INTEGER,
            amount REAL NOT NULL,
            operation TEXT NOT NULL,
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========================================================
    # INDEXES
    # ========================================================

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_stock_product_sold
        ON stock(product_id, sold)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchases_user
        ON purchases(user_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_referrer
        ON users(referrer_id)
    """)

    conn.commit()
    conn.close()

    print(f"SQLite database: {DB_NAME}")


# ============================================================
# HELPERS
# ============================================================

def money(value):
    return f"{float(value or 0):.2f} USDT"


def safe_text(value):
    """
    Экранирует пользовательский текст для Telegram HTML.
    """
    if value is None:
        return ""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def is_admin(user_id):
    return user_id in ADMIN_IDS


def add_user(user_id, name):

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT OR IGNORE INTO users
            (
                id,
                name,
                balance
            )
            VALUES (?, ?, 0)
        """, (
            user_id,
            name
        ))

        cur.execute("""
            UPDATE users
            SET name = ?
            WHERE id = ?
        """, (
            name,
            user_id
        ))

        conn.commit()

    finally:
        conn.close()


def get_balance(user_id):

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT balance
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        row = cur.fetchone()

        if row:
            return float(row["balance"] or 0)

        return 0.0

    finally:
        conn.close()


# ============================================================
# REFERRALS
# ============================================================

def set_referrer(user_id, referrer_id):

    if user_id == referrer_id:
        return False

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM users
            WHERE id = ?
        """, (
            referrer_id,
        ))

        if not cur.fetchone():
            return False

        cur.execute("""
            SELECT referrer_id
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        user = cur.fetchone()

        if not user:
            return False

        if user["referrer_id"] is not None:
            return False

        cur.execute("""
            UPDATE users
            SET referrer_id = ?
            WHERE id = ?
            AND referrer_id IS NULL
        """, (
            referrer_id,
            user_id
        ))

        success = cur.rowcount == 1

        conn.commit()

        return success

    finally:
        conn.close()


# ============================================================
# MAIN MENU
# ============================================================

def main_menu_markup():

    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton(
            "🛍 Товары",
            callback_data="products"
        ),
        types.InlineKeyboardButton(
            "💰 Баланс",
            callback_data="balance"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "➕ Пополнить",
            callback_data="popolnenie"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📦 Мои покупки",
            callback_data="my_purchases"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "⭐ Репутация",
            url="https://t.me/+6rE5mjK1_sZmZDky"
        ),
        types.InlineKeyboardButton(
            "🆘 Поддержка",
            url=f"https://t.me/{SUPPORT_USERNAME}"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "👪 Реферальная программа",
            callback_data="referral"
        )
    )

    return markup


def send_main_menu(chat_id):

    balance = get_balance(chat_id)

    bot.send_message(
        chat_id,
        (
            "🏪 <b>Добро пожаловать в магазин!</b>\n\n"
            f"🆔 Ваш ID: <code>{chat_id}</code>\n"
            f"💰 Баланс: <b>{money(balance)}</b>\n\n"
            "Выберите действие:"
        ),
        reply_markup=main_menu_markup()
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    user_id = message.from_user.id
    name = message.from_user.first_name or "Пользователь"

    add_user(
        user_id,
        name
    )

    args = message.text.split(
        maxsplit=1
    )

    if len(args) > 1:

        referral_code = args[1].strip()

        if referral_code.startswith("ref_"):

            try:
                referrer_id = int(
                    referral_code[4:]
                )

                if set_referrer(
                    user_id,
                    referrer_id
                ):

                    try:
                        bot.send_message(
                            referrer_id,
                            (
                                "🎉 <b>Новый реферал!</b>\n\n"
                                f"👤 Пользователь: <b>{safe_text(name)}</b>\n"
                                f"🆔 ID: <code>{user_id}</code>\n\n"
                                f"Теперь вы получаете "
                                f"<b>{REFERRAL_PERCENT:.0f}%</b> "
                                "с его покупок."
                            )
                        )

                    except Exception as e:
                        print(
                            "Ошибка уведомления реферера:",
                            e
                        )

            except ValueError:
                pass

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True
    )

    markup.add(
        types.KeyboardButton(
            "🚀 Начать"
        )
    )

    bot.send_message(
        message.chat.id,
        (
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Нажмите «🚀 Начать», "
            "чтобы открыть магазин."
        ),
        reply_markup=markup
    )


@bot.message_handler(
    func=lambda message:
        message.text == "🚀 Начать"
)
def start_button(message):

    add_user(
        message.from_user.id,
        message.from_user.first_name or "Пользователь"
    )

    bot.send_message(
        message.chat.id,
        "🏪 Открываю магазин...",
        reply_markup=types.ReplyKeyboardRemove()
    )

    send_main_menu(
        message.chat.id
    )


# ============================================================
# MAIN MENU CALLBACK
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "main_menu"
)
def main_menu_callback(call):

    bot.answer_callback_query(call.id)

    balance = get_balance(
        call.from_user.id
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "🏪 <b>Магазин</b>\n\n"
            f"🆔 Ваш ID: <code>{call.from_user.id}</code>\n"
            f"💰 Баланс: <b>{money(balance)}</b>\n\n"
            "Выберите действие:"
        ),
        reply_markup=main_menu_markup()
    )


# ============================================================
# BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "balance"
)
def balance_callback(call):

    bot.answer_callback_query(call.id)

    balance = get_balance(
        call.from_user.id
    )

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "➕ Пополнить",
            callback_data="popolnenie"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="main_menu"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "💰 <b>Ваш баланс</b>\n\n"
            f"🆔 ID: <code>{call.from_user.id}</code>\n"
            f"💵 Баланс: <b>{money(balance)}</b>"
        ),
        reply_markup=markup
    )


# ============================================================
# PRODUCTS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "products"
)
def products_callback(call):

    bot.answer_callback_query(call.id)

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.description,
                p.price,
                COUNT(s.id) AS stock_count
            FROM products p
            LEFT JOIN stock s
                ON s.product_id = p.id
                AND s.sold = 0
            WHERE p.active = 1
            GROUP BY p.id
            ORDER BY p.id DESC
        """)

        products = cur.fetchall()

    finally:
        conn.close()

    markup = types.InlineKeyboardMarkup(
        row_width=1
    )

    if not products:

        text = (
            "🛍 <b>Товары</b>\n\n"
            "Товаров пока нет."
        )

    else:

        text = (
            "🛍 <b>Каталог товаров</b>\n\n"
            "Выберите товар:"
        )

        for product in products:

            if product["stock_count"] > 0:

                button_text = (
                    f"🛒 {product['name']} — "
                    f"{float(product['price']):.2f} USDT "
                    f"[{product['stock_count']} шт.]"
                )

            else:

                button_text = (
                    f"❌ {product['name']} — "
                    "нет в наличии"
                )

            markup.add(
                types.InlineKeyboardButton(
                    button_text,
                    callback_data=f"product_{product['id']}"
                )
            )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="main_menu"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup
    )


# ============================================================
# PRODUCT PAGE
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("product_")
)
def product_page(call):

    bot.answer_callback_query(call.id)

    try:
        product_id = int(
            call.data.replace(
                "product_",
                "",
                1
            )
        )

    except ValueError:
        return

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.description,
                p.price,
                p.active,
                COUNT(s.id) AS stock_count
            FROM products p
            LEFT JOIN stock s
                ON s.product_id = p.id
                AND s.sold = 0
            WHERE p.id = ?
            GROUP BY p.id
        """, (
            product_id,
        ))

        product = cur.fetchone()

    finally:
        conn.close()

    if not product or not product["active"]:

        bot.answer_callback_query(
            call.id,
            "Товар недоступен.",
            show_alert=True
        )

        return

    description = (
        safe_text(product["description"])
        or "Описание отсутствует"
    )

    text = (
        f"🛍 <b>{safe_text(product['name'])}</b>\n\n"
        f"{description}\n\n"
        f"💵 Цена: <b>{float(product['price']):.2f} USDT</b>\n"
        f"📦 В наличии: <b>{product['stock_count']} шт.</b>"
    )

    markup = types.InlineKeyboardMarkup()

    if product["stock_count"] > 0:

        markup.add(
            types.InlineKeyboardButton(
                f"🛒 Купить — "
                f"{float(product['price']):.2f} USDT",
                callback_data=f"buy_{product_id}"
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ К товарам",
            callback_data="products"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup
    )


# ============================================================
# BUY
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("buy_")
)
def buy_product(call):

    user_id = call.from_user.id

    try:
        product_id = int(
            call.data.replace(
                "buy_",
                "",
                1
            )
        )

    except ValueError:
        bot.answer_callback_query(
            call.id,
            "Некорректный товар.",
            show_alert=True
        )
        return

    conn = get_db()

    referrer_id = None
    referral_reward = 0.0

    try:

        # BEGIN IMMEDIATE защищает от двух одновременных покупок.
        conn.execute("BEGIN IMMEDIATE")

        cur = conn.cursor()

        # ----------------------------------------------------
        # PRODUCT
        # ----------------------------------------------------

        cur.execute("""
            SELECT *
            FROM products
            WHERE id = ?
            AND active = 1
        """, (
            product_id,
        ))

        product = cur.fetchone()

        if not product:
            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Товар не найден.",
                show_alert=True
            )

            return

        price = round(
            float(product["price"]),
            2
        )

        # ----------------------------------------------------
        # USER
        # ----------------------------------------------------

        cur.execute("""
            SELECT
                balance,
                referrer_id
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        user = cur.fetchone()

        if not user:
            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Пользователь не найден.",
                show_alert=True
            )

            return

        balance = float(
            user["balance"] or 0
        )

        if balance < price:

            conn.rollback()

            bot.answer_callback_query(
                call.id,
                (
                    f"Недостаточно средств.\n"
                    f"Нужно: {price:.2f} USDT\n"
                    f"Баланс: {balance:.2f} USDT"
                ),
                show_alert=True
            )

            return

        # ----------------------------------------------------
        # STOCK
        # ----------------------------------------------------

        cur.execute("""
            SELECT *
            FROM stock
            WHERE product_id = ?
            AND sold = 0
            ORDER BY id ASC
            LIMIT 1
        """, (
            product_id,
        ))

        stock_item = cur.fetchone()

        if not stock_item:

            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Товар закончился.",
                show_alert=True
            )

            return

        stock_id = stock_item["id"]
        content = stock_item["content"]

        # ----------------------------------------------------
        # BALANCE
        # ----------------------------------------------------

        cur.execute("""
            UPDATE users
            SET balance = balance - ?
            WHERE id = ?
            AND balance >= ?
        """, (
            price,
            user_id,
            price
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Не удалось списать баланс.",
                show_alert=True
            )

            return

        # ----------------------------------------------------
        # STOCK SOLD
        # ----------------------------------------------------

        cur.execute("""
            UPDATE stock
            SET
                sold = 1,
                buyer_id = ?
            WHERE id = ?
            AND sold = 0
        """, (
            user_id,
            stock_id
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Не удалось выдать товар.",
                show_alert=True
            )

            return

        # ----------------------------------------------------
        # PURCHASE
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO purchases
            (
                user_id,
                product_id,
                stock_id,
                price,
                content
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            product_id,
            stock_id,
            price,
            content
        ))

        # ----------------------------------------------------
        # REFERRAL
        # ----------------------------------------------------

        if user["referrer_id"]:

            referrer_id = user["referrer_id"]

            referral_reward = round(
                price * REFERRAL_PERCENT / 100,
                2
            )

            if referral_reward > 0:

                cur.execute("""
                    UPDATE users
                    SET
                        referral_balance =
                            referral_balance + ?,
                        referral_earnings =
                            referral_earnings + ?
                    WHERE id = ?
                """, (
                    referral_reward,
                    referral_reward,
                    referrer_id
                ))

                cur.execute("""
                    INSERT INTO balance_history
                    (
                        user_id,
                        admin_id,
                        amount,
                        operation,
                        comment
                    )
                    VALUES (?, NULL, ?, 'referral', ?)
                """, (
                    referrer_id,
                    referral_reward,
                    (
                        f"Реферальное вознаграждение "
                        f"{REFERRAL_PERCENT:.0f}% "
                        f"с покупки пользователя {user_id}"
                    )
                ))

        # ----------------------------------------------------
        # BALANCE HISTORY
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO balance_history
            (
                user_id,
                admin_id,
                amount,
                operation,
                comment
            )
            VALUES (?, NULL, ?, 'purchase', ?)
        """, (
            user_id,
            -price,
            f"Покупка: {product['name']}"
        ))

        conn.commit()

        new_balance = round(
            balance - price,
            2
        )

    except Exception as e:

        try:
            conn.rollback()
        except Exception:
            pass

        print(
            "Ошибка покупки:",
            repr(e)
        )

        bot.answer_callback_query(
            call.id,
            "Произошла ошибка.",
            show_alert=True
        )

        return

    finally:
        conn.close()

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    bot.answer_callback_query(
        call.id,
        "Покупка совершена!",
        show_alert=True
    )

    bot.send_message(
        user_id,
        (
            "✅ <b>Покупка успешно совершена!</b>\n\n"
            f"🛍 Товар: <b>{safe_text(product['name'])}</b>\n"
            f"💵 Списано: <b>{price:.2f} USDT</b>\n"
            f"💰 Остаток: <b>{new_balance:.2f} USDT</b>\n\n"
            "📦 <b>Ваш товар:</b>\n\n"
            f"<code>{safe_text(content)}</code>"
        )
    )

    # --------------------------------------------------------
    # REFERRER NOTIFICATION
    # --------------------------------------------------------

    if referrer_id and referral_reward > 0:

        try:

            bot.send_message(
                referrer_id,
                (
                    "💎 <b>Реферальное вознаграждение!</b>\n\n"
                    "👤 Ваш реферал совершил покупку.\n"
                    f"🛍 Товар: <b>{safe_text(product['name'])}</b>\n"
                    f"💵 Сумма покупки: <b>{price:.2f} USDT</b>\n\n"
                    f"➕ Вам начислено: "
                    f"<b>{referral_reward:.2f} USDT</b>\n"
                    f"📊 Процент: "
                    f"<b>{REFERRAL_PERCENT:.0f}%</b>"
                )
            )

        except Exception as e:

            print(
                "Ошибка уведомления реферера:",
                e
            )


# ============================================================
# MY PURCHASES
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "my_purchases"
)
def my_purchases(call):

    bot.answer_callback_query(call.id)

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                purchases.id,
                products.name,
                purchases.price,
                purchases.created_at
            FROM purchases
            LEFT JOIN products
                ON products.id = purchases.product_id
            WHERE purchases.user_id = ?
            ORDER BY purchases.id DESC
            LIMIT 20
        """, (
            call.from_user.id,
        ))

        purchases = cur.fetchall()

    finally:
        conn.close()

    markup = types.InlineKeyboardMarkup()

    if not purchases:

        text = (
            "📦 <b>Мои покупки</b>\n\n"
            "Покупок пока нет."
        )

    else:

        text = "📦 <b>Мои покупки</b>\n\n"

        for purchase in purchases:

            name = (
                purchase["name"]
                or "Удалённый товар"
            )

            text += (
                f"#{purchase['id']} — "
                f"<b>{safe_text(name)}</b>\n"
                f"💵 {money(purchase['price'])}\n"
                f"🕐 {purchase['created_at']}\n\n"
            )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="main_menu"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup
    )


# ============================================================
# REFERRAL PROGRAM
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "referral"
)
def referral_callback(call):

    bot.answer_callback_query(call.id)

    user_id = call.from_user.id

    try:
        bot_username = bot.get_me().username

    except Exception as e:

        print(
            "Ошибка получения username:",
            e
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Не удалось создать реферальную ссылку."
        )

        return

    referral_link = (
        f"https://t.me/{bot_username}"
        f"?start=ref_{user_id}"
    )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM users
            WHERE referrer_id = ?
        """, (
            user_id,
        ))

        referrals_count = cur.fetchone()["count"]

        cur.execute("""
            SELECT
                referral_earnings,
                balance,
                referral_balance
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        row = cur.fetchone()

    finally:
        conn.close()

    referral_earnings = (
        float(row["referral_earnings"] or 0)
        if row else 0.0
    )

    balance = (
        float(row["balance"] or 0)
        if row else 0.0
    )

    referral_balance = (
        float(row["referral_balance"] or 0)
        if row else 0.0
    )

    markup = types.InlineKeyboardMarkup(
        row_width=1
    )

    markup.add(
        types.InlineKeyboardButton(
            "📤 Пригласить друга",
            url=(
                "https://t.me/share/url"
                f"?url={referral_link}"
                "&text=Присоединяйся к магазину!"
            )
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "💸 Вывести реферальные",
            callback_data="referral_withdraw"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="main_menu"
        )
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "👪 <b>Реферальная программа</b>\n\n"
            f"💎 Процент: <b>{REFERRAL_PERCENT:.0f}%</b>\n"
            f"👥 Приглашено: <b>{referrals_count}</b>\n"
            f"💰 Заработано всего: "
            f"<b>{referral_earnings:.2f} USDT</b>\n"
            f"💸 Доступно для вывода: "
            f"<b>{referral_balance:.2f} USDT</b>\n\n"
            "🔗 <b>Ваша реферальная ссылка:</b>\n"
            f"<code>{referral_link}</code>\n\n"
            "📌 Реферал закрепляется за вами "
            "один раз и навсегда.\n"
            "💵 Выводятся только деньги, "
            "заработанные по реферальной программе."
        ),
        reply_markup=markup
    )


# ============================================================
# REFERRAL WITHDRAW
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "referral_withdraw"
)
def referral_withdraw_callback(call):

    user_id = call.from_user.id

    conn = get_db()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT referral_balance
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        row = cur.fetchone()

    finally:
        conn.close()

    available = (
        float(row["referral_balance"] or 0)
        if row else 0.0
    )

    if available < MIN_REFERRAL_WITHDRAWAL:

        bot.answer_callback_query(
            call.id,
            (
                f"❌ Минимум: "
                f"{MIN_REFERRAL_WITHDRAWAL:.2f} USDT"
            ),
            show_alert=True
        )

        return

    withdrawal_states.add(user_id)

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        call.message.chat.id,
        (
            "💸 <b>Вывод реферальных денег</b>\n\n"
            f"Доступно: <b>{available:.2f} USDT</b>\n"
            f"Минимум: "
            f"<b>{MIN_REFERRAL_WITHDRAWAL:.2f} USDT</b>\n\n"
            "Введите сумму, например:\n"
            "<code>5.50</code>\n\n"
            "Для отмены напишите:\n"
            "<b>отмена</b>"
        )
    )


@bot.message_handler(
    func=lambda message:
        message.from_user.id in withdrawal_states
)
def referral_withdraw_amount(message):

    user_id = message.from_user.id

    value = (
        message.text or ""
    ).strip()

    if value.lower() in (
        "отмена",
        "cancel",
        "/cancel"
    ):

        withdrawal_states.discard(
            user_id
        )

        bot.send_message(
            message.chat.id,
            "❌ Вывод отменён."
        )

        return

    try:

        amount = round(
            float(
                value.replace(",", ".")
            ),
            2
        )

        if amount <= 0:
            raise ValueError

    except ValueError:

        bot.send_message(
            message.chat.id,
            (
                "❌ Введите корректную сумму, "
                "например: <code>5.50</code>"
            )
        )

        return

    if amount < MIN_REFERRAL_WITHDRAWAL:

        bot.send_message(
            message.chat.id,
            (
                f"❌ Минимальная сумма: "
                f"{MIN_REFERRAL_WITHDRAWAL:.2f} USDT"
            )
        )

        return

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = conn.cursor()

        cur.execute("""
            SELECT referral_balance
            FROM users
            WHERE id = ?
        """, (
            user_id,
        ))

        row = cur.fetchone()

        if not row:

            conn.rollback()

            withdrawal_states.discard(
                user_id
            )

            bot.send_message(
                message.chat.id,
                "❌ Пользователь не найден."
            )

            return

        available = float(
            row["referral_balance"] or 0
        )

        if amount > available:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                (
                    f"❌ Недостаточно.\n"
                    f"Доступно: "
                    f"<b>{available:.2f} USDT</b>"
                )
            )

            return

        cur.execute("""
            UPDATE users
            SET referral_balance =
                referral_balance - ?
            WHERE id = ?
            AND referral_balance >= ?
        """, (
            amount,
            user_id,
            amount
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                "❌ Не удалось зарезервировать сумму."
            )

            return

        cur.execute("""
            INSERT INTO referral_withdrawals
            (
                user_id,
                amount,
                status
            )
            VALUES (?, ?, 'pending')
        """, (
            user_id,
            amount
        ))

        withdrawal_id = cur.lastrowid

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "Ошибка создания вывода:",
            repr(e)
        )

        withdrawal_states.discard(
            user_id
        )

        bot.send_message(
            message.chat.id,
            "❌ Ошибка при создании заявки."
        )

        return

    finally:
        conn.close()

    withdrawal_states.discard(
        user_id
    )

    # ========================================================
    # CRYPTO PAY TRANSFER
    # ========================================================

    if not CRYPTO_PAY_TOKEN:
        print("Ошибка вывода: CRYPTO_PAY_TOKEN не задан")
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE users
                SET referral_balance = referral_balance + ?
                WHERE id = ?
            """, (amount, user_id))
            cur.execute("""
                UPDATE referral_withdrawals
                SET status = 'failed'
                WHERE id = ?
            """, (withdrawal_id,))
            conn.commit()
        finally:
            conn.close()
        bot.send_message(
            message.chat.id,
            "❌ Вывод недоступен: не задан CRYPTO_PAY_TOKEN. Деньги возвращены на реферальный баланс."
        )
        return

    headers = {
        "Crypto-Pay-API-Token":
            '626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ'
    }

    transfer_data = {
        "user_id": user_id,
        "asset": "USDT",
        "amount": f"{amount:.2f}",
        "spend_id": f"ref_withdraw_{withdrawal_id}",
        "comment": "Реферальный вывод"
    }

    try:

        response = requests.post(
            CRYPTO_API_URL + "/transfer",
            headers=headers,
            json=transfer_data,
            timeout=20
        )

        response.raise_for_status()

        result = response.json()

        print(
            "Crypto Pay transfer:",
            result
        )

        if result.get("ok"):

            transfer = (
                result.get("result")
                or {}
            )

            transfer_id = transfer.get(
                "transfer_id"
            )

            conn = get_db()

            try:

                cur = conn.cursor()

                cur.execute("""
                    UPDATE referral_withdrawals
                    SET
                        status = 'success',
                        transfer_id = ?
                    WHERE id = ?
                """, (
                    transfer_id,
                    withdrawal_id
                ))

                conn.commit()

            finally:
                conn.close()

            bot.send_message(
                message.chat.id,
                (
                    "✅ <b>Вывод выполнен!</b>\n\n"
                    f"💸 Сумма: "
                    f"<b>{amount:.2f} USDT</b>\n"
                    f"🧾 Заявка: "
                    f"<code>#{withdrawal_id}</code>"
                )
            )

        else:

            error = result.get(
                "error",
                {}
            )

            if isinstance(error, dict):
                error_name = error.get(
                    "name",
                    "Ошибка Crypto Pay"
                )
            else:
                error_name = str(error)

            conn = get_db()

            try:

                cur = conn.cursor()

                cur.execute("""
                    UPDATE users
                    SET referral_balance =
                        referral_balance + ?
                    WHERE id = ?
                """, (
                    amount,
                    user_id
                ))

                cur.execute("""
                    UPDATE referral_withdrawals
                    SET status = 'failed'
                    WHERE id = ?
                """, (
                    withdrawal_id,
                ))

                conn.commit()

            finally:
                conn.close()

            bot.send_message(
                message.chat.id,
                (
                    "❌ <b>Вывод не выполнен.</b>\n\n"
                    f"Причина: <code>"
                    f"{safe_text(error_name)}</code>\n\n"
                    "💰 Деньги возвращены "
                    "на реферальный баланс."
                )
            )

    except Exception as e:

        print(
            "Ошибка Crypto Pay transfer:",
            repr(e)
        )

        conn = get_db()

        try:

            cur = conn.cursor()

            cur.execute("""
                UPDATE users
                SET referral_balance =
                    referral_balance + ?
                WHERE id = ?
            """, (
                amount,
                user_id
            ))

            cur.execute("""
                UPDATE referral_withdrawals
                SET status = 'failed'
                WHERE id = ?
            """, (
                withdrawal_id,
            ))

            conn.commit()

        finally:
            conn.close()

        bot.send_message(
            message.chat.id,
            (
                "❌ Не удалось выполнить вывод.\n\n"
                "💰 Деньги возвращены "
                "на реферальный баланс."
            )
        )


# ============================================================
# CRYPTO PAY
# ============================================================

def create_invoice(amount):

    headers = {
        "Crypto-Pay-API-Token":
            '626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ'
    }

    data = {
        "currency_type": "crypto",
        "asset": "USDT",
        "amount": f"{amount:.2f}",
        "description": "Пополнение баланса"
    }

    try:

        response = requests.post(
            CRYPTO_API_URL + "/createInvoice",
            headers=headers,
            json=data,
            timeout=15
        )

        response.raise_for_status()

        result = response.json()

        print(
            "Crypto Pay:",
            result
        )

        if not result.get("ok"):

            print(
                "Ошибка Crypto Pay:",
                result
            )

            return None

        return result.get("result")

    except requests.RequestException as e:

        print(
            "Ошибка HTTP Crypto Pay:",
            repr(e)
        )

        return None

    except (ValueError, KeyError) as e:

        print(
            "Ошибка ответа Crypto Pay:",
            repr(e)
        )

        return None


# ============================================================
# PAYMENT START
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "popolnenie"
)
def payment_start(call):

    bot.answer_callback_query(
        call.id
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "💳 <b>Пополнение баланса</b>\n\n"
            "Введите сумму в USDT.\n\n"
            "Например:\n"
            "<code>10</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_amount
    )


def process_amount(message):

    try:

        raw = (
            message.text or ""
        ).strip()

        amount = round(
            float(
                raw.replace(",", ".")
            ),
            2
        )

        if amount <= 0:
            raise ValueError

    except (ValueError, AttributeError):

        msg = bot.send_message(
            message.chat.id,
            (
                "❌ Некорректная сумма.\n\n"
                "Введите положительное число."
            )
        )

        bot.register_next_step_handler(
            msg,
            process_amount
        )

        return

    invoice = create_invoice(
        amount
    )

    if not invoice:

        bot.send_message(
            message.chat.id,
            (
                "❌ Не удалось создать счёт.\n\n"
                "Попробуйте ещё раз позже."
            )
        )

        return

    invoice_id = invoice.get(
        "invoice_id"
    )

    pay_url = invoice.get(
        "pay_url"
    )

    if not invoice_id or not pay_url:

        print(
            "Некорректный invoice:",
            invoice
        )

        bot.send_message(
            message.chat.id,
            "❌ Crypto Pay вернул некорректный счёт."
        )

        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            INSERT INTO payments
            (
                invoice_id,
                user_id,
                amount,
                status
            )
            VALUES (?, ?, ?, 'active')
        """, (
            invoice_id,
            message.from_user.id,
            amount
        ))

        conn.commit()

    finally:
        conn.close()

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            f"💳 Оплатить {amount:.2f} USDT",
            url=pay_url
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🔄 Проверить оплату",
            callback_data=f"check_{invoice_id}"
        )
    )

    bot.send_message(
        message.chat.id,
        (
            "💰 <b>Счёт создан!</b>\n\n"
            f"Сумма: <b>{amount:.2f} USDT</b>\n\n"
            "Оплатите счёт и нажмите "
            "«Проверить оплату»."
        ),
        reply_markup=markup
    )


# ============================================================
# CHECK PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("check_")
)
def check_payment(call):

    try:

        invoice_id = int(
            call.data.replace(
                "check_",
                "",
                1
            )
        )

    except ValueError:

        bot.answer_callback_query(
            call.id,
            "Некорректный счёт.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # Сначала проверяем владельца invoice в БД.
    # Это важно: другой пользователь не должен иметь
    # возможность инициировать зачисление чужого счёта.
    # --------------------------------------------------------

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                amount,
                status
            FROM payments
            WHERE invoice_id = ?
        """, (
            invoice_id,
        ))

        payment = cur.fetchone()

    finally:
        conn.close()

    if not payment:

        bot.answer_callback_query(
            call.id,
            "Платёж не найден.",
            show_alert=True
        )

        return

    if payment["user_id"] != call.from_user.id:

        bot.answer_callback_query(
            call.id,
            "❌ Это не ваш платёж.",
            show_alert=True
        )

        return

    if payment["status"] == "paid":

        bot.answer_callback_query(
            call.id,
            "Этот платёж уже зачислен.",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        call.id
    )

    headers = {
        "Crypto-Pay-API-Token":
            CRYPTO_PAY_TOKEN
    }

    try:

        response = requests.get(
            CRYPTO_API_URL + "/getInvoices",
            headers=headers,
            params={
                "invoice_ids": invoice_id
            },
            timeout=15
        )

        response.raise_for_status()

        result = response.json()

        print(
            "Crypto Pay:",
            result
        )

    except Exception as e:

        print(
            "Ошибка проверки платежа:",
            repr(e)
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Не удалось проверить платёж."
        )

        return

    if not result.get("ok"):

        bot.send_message(
            call.message.chat.id,
            "❌ Ошибка Crypto Pay."
        )

        return

    result_data = (
        result.get("result")
        or {}
    )

    invoices = (
        result_data.get("items")
        or []
    )

    if not invoices:

        bot.send_message(
            call.message.chat.id,
            "❌ Счёт не найден в Crypto Pay."
        )

        return

    invoice = invoices[0]

    if invoice.get("status") != "paid":

        bot.send_message(
            call.message.chat.id,
            "⏳ Оплата ещё не поступила."
        )

        return

    # --------------------------------------------------------
    # ЗАЧИСЛЕНИЕ
    # --------------------------------------------------------

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                amount,
                status
            FROM payments
            WHERE invoice_id = ?
        """, (
            invoice_id,
        ))

        payment = cur.fetchone()

        if not payment:

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "❌ Платёж не найден."
            )

            return

        if payment["user_id"] != call.from_user.id:

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "❌ Это не ваш платёж."
            )

            return

        if payment["status"] == "paid":

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "ℹ️ Этот платёж уже был зачислен."
            )

            return

        user_id = payment["user_id"]
        amount = float(
            payment["amount"]
        )

        cur.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE id = ?
        """, (
            amount,
            user_id
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "❌ Пользователь не найден."
            )

            return

        cur.execute("""
            UPDATE payments
            SET status = 'paid'
            WHERE invoice_id = ?
            AND status != 'paid'
        """, (
            invoice_id,
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "ℹ️ Платёж уже обрабатывается."
            )

            return

        cur.execute("""
            INSERT INTO balance_history
            (
                user_id,
                admin_id,
                amount,
                operation,
                comment
            )
            VALUES (
                ?,
                NULL,
                ?,
                'deposit',
                'Crypto Pay'
            )
        """, (
            user_id,
            amount
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "Ошибка зачисления:",
            repr(e)
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Ошибка при зачислении."
        )

        return

    finally:
        conn.close()

    new_balance = get_balance(
        user_id
    )

    bot.send_message(
        call.message.chat.id,
        (
            "✅ <b>Оплата получена!</b>\n\n"
            f"➕ Зачислено: "
            f"<b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: "
            f"<b>{new_balance:.2f} USDT</b>"
        )
    )


# ============================================================
# ADMIN MENU
# ============================================================

def admin_menu(chat_id):

    markup = types.InlineKeyboardMarkup(
        row_width=1
    )

    markup.add(
        types.InlineKeyboardButton(
            "➕ Создать товар",
            callback_data="admin_add_product"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📦 Управление складом",
            callback_data="admin_stock"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🛍 Управление товарами",
            callback_data="admin_products"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "➕ Начислить баланс",
            callback_data="admin_add_balance"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "➖ Списать баланс",
            callback_data="admin_remove_balance"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📊 Статистика",
            callback_data="admin_stats"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "👪 Рефералы",
            callback_data="admin_referrals"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📢 Рассылка",
            callback_data="admin_broadcast"
        )
    )

    bot.send_message(
        chat_id,
        "👑 <b>Админ-панель</b>",
        reply_markup=markup
    )


@bot.message_handler(
    commands=["admin"]
)
def admin_command(message):

    if not is_admin(
        message.from_user.id
    ):

        bot.send_message(
            message.chat.id,
            "❌ Доступ запрещён."
        )

        return

    admin_menu(
        message.chat.id
    )


# ============================================================
# ADMIN BROADCAST
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_broadcast"
)
def admin_broadcast(call):

    if not is_admin(
        call.from_user.id
    ):

        bot.answer_callback_query(
            call.id,
            "❌ Доступ запрещён.",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        call.id
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "📢 <b>Рассылка</b>\n\n"
            "Введите ID пользователя или "
            "<code>ALL</code>.\n\n"
            "Пример:\n"
            "<code>123456789</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_broadcast_recipient
    )


def process_broadcast_recipient(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    recipient = (
        message.text or ""
    ).strip()

    if not recipient:

        msg = bot.send_message(
            message.chat.id,
            "❌ Введите ID или ALL."
        )

        bot.register_next_step_handler(
            msg,
            process_broadcast_recipient
        )

        return

    if recipient.upper() == "ALL":

        target = "all"

    else:

        try:
            target = int(
                recipient
            )

        except ValueError:

            msg = bot.send_message(
                message.chat.id,
                "❌ ID должен быть числом."
            )

            bot.register_next_step_handler(
                msg,
                process_broadcast_recipient
            )

            return

    msg = bot.send_message(
        message.chat.id,
        (
            "✉️ <b>Введите сообщение</b>\n\n"
            "Будет отправлен обычный текст."
        )
    )

    bot.register_next_step_handler(
        msg,
        process_broadcast_message,
        target
    )


def process_broadcast_message(
    message,
    target
):

    if not is_admin(
        message.from_user.id
    ):
        return

    broadcast_text = (
        message.text or ""
    ).strip()

    if not broadcast_text:

        bot.send_message(
            message.chat.id,
            "❌ Сообщение не может быть пустым."
        )

        return

    # --------------------------------------------------------
    # ONE USER
    # --------------------------------------------------------

    if target != "all":

        conn = get_db()

        try:

            cur = conn.cursor()

            cur.execute(
                "SELECT id FROM users WHERE id = ?",
                (target,)
            )

            user = cur.fetchone()

        finally:
            conn.close()

        if not user:

            bot.send_message(
                message.chat.id,
                (
                    "❌ Пользователь "
                    f"<code>{target}</code> "
                    "не найден."
                )
            )

            return

        try:

            bot.send_message(
                target,
                broadcast_text
            )

            bot.send_message(
                message.chat.id,
                (
                    "✅ <b>Сообщение отправлено</b>\n\n"
                    f"🆔 ID: <code>{target}</code>"
                )
            )

        except Exception as e:

            print(
                "Ошибка рассылки:",
                repr(e)
            )

            bot.send_message(
                message.chat.id,
                "❌ Не удалось отправить сообщение."
            )

        return

    # --------------------------------------------------------
    # ALL
    # --------------------------------------------------------

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM users ORDER BY id ASC"
        )

        users = cur.fetchall()

    finally:
        conn.close()

    if not users:

        bot.send_message(
            message.chat.id,
            "❌ Пользователей нет."
        )

        return

    success = 0
    failed = 0

    for user in users:

        try:

            bot.send_message(
                user["id"],
                broadcast_text
            )

            success += 1

        except Exception as e:

            failed += 1

            print(
                f"Ошибка отправки {user['id']}:",
                repr(e)
            )

    bot.send_message(
        message.chat.id,
        (
            "📢 <b>Рассылка завершена!</b>\n\n"
            f"👥 Всего: <b>{len(users)}</b>\n"
            f"✅ Успешно: <b>{success}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>"
        )
    )


# ============================================================
# ADD PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_add_product"
)
def admin_add_product(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➕ <b>Создание товара</b>\n\n"
            "Введите:\n"
            "<code>Название | Цена | Описание</code>\n\n"
            "Например:\n"
            "<code>Netflix | 5 | "
            "Аккаунт на 30 дней</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_add_product
    )


def process_add_product(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    try:

        parts = (
            message.text or ""
        ).split(
            "|",
            2
        )

        if len(parts) != 3:
            raise ValueError

        name = parts[0].strip()

        price = round(
            float(
                parts[1]
                .strip()
                .replace(",", ".")
            ),
            2
        )

        description = parts[2].strip()

        if not name or price <= 0:
            raise ValueError

    except (
        ValueError,
        AttributeError
    ):

        bot.send_message(
            message.chat.id,
            (
                "❌ Неверный формат.\n\n"
                "<code>Название | Цена | Описание</code>"
            )
        )

        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            INSERT INTO products
            (
                name,
                description,
                price,
                active
            )
            VALUES (?, ?, ?, 1)
        """, (
            name,
            description,
            price
        ))

        product_id = cur.lastrowid

        conn.commit()

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Товар создан!</b>\n\n"
            f"🆔 ID: <code>{product_id}</code>\n"
            f"🛍 {safe_text(name)}\n"
            f"💵 {price:.2f} USDT"
        )
    )


# ============================================================
# ADMIN PRODUCTS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_products"
)
def admin_products(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT
                p.id,
                p.name,
                p.price,
                p.active,
                COUNT(s.id) AS stock_count
            FROM products p
            LEFT JOIN stock s
                ON s.product_id = p.id
                AND s.sold = 0
            GROUP BY p.id
            ORDER BY p.id DESC
        """)

        products = cur.fetchall()

    finally:
        conn.close()

    if not products:

        bot.send_message(
            call.message.chat.id,
            "🛍 Товаров пока нет."
        )

        return

    for product in products:

        status = (
            "🟢 Активен"
            if product["active"]
            else
            "🔴 Скрыт"
        )

        markup = types.InlineKeyboardMarkup(
            row_width=2
        )

        markup.add(
            types.InlineKeyboardButton(
                "✏️ Изменить",
                callback_data=(
                    f"edit_product_{product['id']}"
                )
            ),
            types.InlineKeyboardButton(
                "📦 Склад",
                callback_data=(
                    f"stock_product_{product['id']}"
                )
            )
        )

        markup.add(
            types.InlineKeyboardButton(
                "🔴 Скрыть"
                if product["active"]
                else
                "🟢 Включить",
                callback_data=(
                    f"toggle_product_{product['id']}"
                )
            )
        )

        bot.send_message(
            call.message.chat.id,
            (
                f"{status}\n\n"
                f"🆔 ID: <code>{product['id']}</code>\n"
                f"🛍 <b>{safe_text(product['name'])}</b>\n"
                f"💵 <b>{float(product['price']):.2f} USDT</b>\n"
                f"📦 На складе: "
                f"<b>{product['stock_count']}</b>"
            ),
            reply_markup=markup
        )


# ============================================================
# EDIT PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("edit_product_")
)
def edit_product(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    try:

        product_id = int(
            call.data.replace(
                "edit_product_",
                "",
                1
            )
        )

    except ValueError:
        return

    msg = bot.send_message(
        call.message.chat.id,
        (
            "✏️ Введите новые данные:\n\n"
            "<code>Название | Цена | Описание</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_edit_product,
        product_id
    )


def process_edit_product(
    message,
    product_id
):

    if not is_admin(
        message.from_user.id
    ):
        return

    try:

        parts = (
            message.text or ""
        ).split(
            "|",
            2
        )

        if len(parts) != 3:
            raise ValueError

        name = parts[0].strip()

        price = round(
            float(
                parts[1]
                .strip()
                .replace(",", ".")
            ),
            2
        )

        description = parts[2].strip()

        if not name or price <= 0:
            raise ValueError

    except (
        ValueError,
        AttributeError
    ):

        bot.send_message(
            message.chat.id,
            "❌ Неверный формат."
        )

        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            UPDATE products
            SET
                name = ?,
                price = ?,
                description = ?
            WHERE id = ?
        """, (
            name,
            price,
            description,
            product_id
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                "❌ Товар не найден."
            )

            return

        conn.commit()

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        "✅ Товар изменён."
    )


# ============================================================
# TOGGLE PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("toggle_product_")
)
def toggle_product(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    try:

        product_id = int(
            call.data.replace(
                "toggle_product_",
                "",
                1
            )
        )

    except ValueError:
        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT active
            FROM products
            WHERE id = ?
        """, (
            product_id,
        ))

        product = cur.fetchone()

        if not product:

            bot.send_message(
                call.message.chat.id,
                "❌ Товар не найден."
            )

            return

        new_status = (
            0
            if product["active"]
            else
            1
        )

        cur.execute("""
            UPDATE products
            SET active = ?
            WHERE id = ?
        """, (
            new_status,
            product_id
        ))

        conn.commit()

    finally:
        conn.close()

    bot.send_message(
        call.message.chat.id,
        "✅ Статус товара изменён."
    )


# ============================================================
# STOCK
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_stock"
)
def admin_stock(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT
                p.id,
                p.name,
                COUNT(s.id) AS stock_count
            FROM products p
            LEFT JOIN stock s
                ON s.product_id = p.id
                AND s.sold = 0
            GROUP BY p.id
            ORDER BY p.id DESC
        """)

        products = cur.fetchall()

    finally:
        conn.close()

    markup = types.InlineKeyboardMarkup(
        row_width=1
    )

    for product in products:

        markup.add(
            types.InlineKeyboardButton(
                (
                    f"📦 {product['name']} "
                    f"({product['stock_count']} шт.)"
                ),
                callback_data=(
                    f"stock_product_{product['id']}"
                )
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="admin_back"
        )
    )

    bot.send_message(
        call.message.chat.id,
        "📦 <b>Выберите товар:</b>",
        reply_markup=markup
    )


# ============================================================
# ADD STOCK
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith("stock_product_")
)
def stock_product(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    try:

        product_id = int(
            call.data.replace(
                "stock_product_",
                "",
                1
            )
        )

    except ValueError:
        return

    msg = bot.send_message(
        call.message.chat.id,
        (
            "📦 Отправьте одну единицу товара.\n\n"
            "Например:\n"
            "<code>login:password</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_add_stock,
        product_id
    )


def process_add_stock(
    message,
    product_id
):

    if not is_admin(
        message.from_user.id
    ):
        return

    content = (
        message.text or ""
    ).strip()

    if not content:

        bot.send_message(
            message.chat.id,
            "❌ Товар не может быть пустым."
        )

        return

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM products WHERE id = ?",
            (product_id,)
        )

        product = cur.fetchone()

        if not product:

            bot.send_message(
                message.chat.id,
                "❌ Товар не найден."
            )

            return

        cur.execute("""
            INSERT INTO stock
            (
                product_id,
                content,
                sold
            )
            VALUES (?, ?, 0)
        """, (
            product_id,
            content
        ))

        stock_id = cur.lastrowid

        conn.commit()

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Единица товара добавлена!</b>\n\n"
            f"ID склада: <code>{stock_id}</code>"
        )
    )


# ============================================================
# ADMIN ADD BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_add_balance"
)
def admin_add_balance(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➕ <b>Начисление баланса</b>\n\n"
            "Введите:\n"
            "<code>ID сумма</code>\n\n"
            "Например:\n"
            "<code>123456789 50</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_admin_add_balance
    )


def process_admin_add_balance(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    try:

        parts = (
            message.text or ""
        ).strip().split()

        if len(parts) != 2:
            raise ValueError

        user_id = int(
            parts[0]
        )

        amount = round(
            float(
                parts[1].replace(
                    ",",
                    "."
                )
            ),
            2
        )

        if amount <= 0:
            raise ValueError

    except (
        ValueError,
        AttributeError
    ):

        bot.send_message(
            message.chat.id,
            "❌ Формат: <code>ID сумма</code>"
        )

        return

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = conn.cursor()

        cur.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user_id,)
        )

        user = cur.fetchone()

        if not user:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                "❌ Пользователь не найден."
            )

            return

        cur.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE id = ?
        """, (
            amount,
            user_id
        ))

        cur.execute("""
            INSERT INTO balance_history
            (
                user_id,
                admin_id,
                amount,
                operation,
                comment
            )
            VALUES (?, ?, ?, 'admin_add', ?)
        """, (
            user_id,
            message.from_user.id,
            amount,
            "Начисление администратором"
        ))

        cur.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user_id,)
        )

        new_balance = float(
            cur.fetchone()["balance"]
        )

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "Ошибка admin add balance:",
            repr(e)
        )

        bot.send_message(
            message.chat.id,
            "❌ Ошибка при начислении."
        )

        return

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Баланс начислен</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"➕ Сумма: <b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: <b>{new_balance:.2f} USDT</b>"
        )
    )

    try:

        bot.send_message(
            user_id,
            (
                "💰 <b>Баланс пополнен</b>\n\n"
                f"➕ Зачислено: "
                f"<b>{amount:.2f} USDT</b>\n"
                f"💵 Баланс: "
                f"<b>{new_balance:.2f} USDT</b>"
            )
        )

    except Exception as e:

        print(
            "Ошибка уведомления:",
            repr(e)
        )


# ============================================================
# ADMIN REMOVE BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_remove_balance"
)
def admin_remove_balance(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➖ <b>Списание баланса</b>\n\n"
            "Введите:\n"
            "<code>ID сумма</code>"
        )
    )

    bot.register_next_step_handler(
        msg,
        process_admin_remove_balance
    )


def process_admin_remove_balance(message):

    if not is_admin(
        message.from_user.id
    ):
        return

    try:

        parts = (
            message.text or ""
        ).strip().split()

        if len(parts) != 2:
            raise ValueError

        user_id = int(
            parts[0]
        )

        amount = round(
            float(
                parts[1].replace(
                    ",",
                    "."
                )
            ),
            2
        )

        if amount <= 0:
            raise ValueError

    except (
        ValueError,
        AttributeError
    ):

        bot.send_message(
            message.chat.id,
            "❌ Формат: <code>ID сумма</code>"
        )

        return

    conn = get_db()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = conn.cursor()

        cur.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user_id,)
        )

        user = cur.fetchone()

        if not user:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                "❌ Пользователь не найден."
            )

            return

        current_balance = float(
            user["balance"]
        )

        if current_balance < amount:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                (
                    "❌ <b>Недостаточно средств.</b>\n\n"
                    f"Баланс: "
                    f"<b>{current_balance:.2f} USDT</b>\n"
                    f"Списание: "
                    f"<b>{amount:.2f} USDT</b>"
                )
            )

            return

        cur.execute("""
            UPDATE users
            SET balance = balance - ?
            WHERE id = ?
            AND balance >= ?
        """, (
            amount,
            user_id,
            amount
        ))

        if cur.rowcount != 1:

            conn.rollback()

            bot.send_message(
                message.chat.id,
                "❌ Не удалось списать баланс."
            )

            return

        cur.execute("""
            INSERT INTO balance_history
            (
                user_id,
                admin_id,
                amount,
                operation,
                comment
            )
            VALUES (?, ?, ?, 'admin_remove', ?)
        """, (
            user_id,
            message.from_user.id,
            -amount,
            "Списание администратором"
        ))

        cur.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user_id,)
        )

        new_balance = float(
            cur.fetchone()["balance"]
        )

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "Ошибка admin remove balance:",
            repr(e)
        )

        bot.send_message(
            message.chat.id,
            "❌ Ошибка при списании."
        )

        return

    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Баланс списан</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"➖ Списано: "
            f"<b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: "
            f"<b>{new_balance:.2f} USDT</b>"
        )
    )

    try:

        bot.send_message(
            user_id,
            (
                "⚠️ <b>С вашего баланса "
                "списаны средства</b>\n\n"
                f"➖ Списано: "
                f"<b>{amount:.2f} USDT</b>\n"
                f"💵 Баланс: "
                f"<b>{new_balance:.2f} USDT</b>"
            )
        )

    except Exception as e:

        print(
            "Ошибка уведомления:",
            repr(e)
        )


# ============================================================
# ADMIN REFERRALS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_referrals"
)
def admin_referrals(call):

    if not is_admin(
        call.from_user.id
    ):

        bot.answer_callback_query(
            call.id,
            "❌ Доступ запрещён.",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        call.id
    )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM users
            WHERE referrer_id IS NOT NULL
        """)

        total_referrals = cur.fetchone()["count"]

        cur.execute("""
            SELECT
                COALESCE(
                    SUM(referral_earnings),
                    0
                ) AS total
            FROM users
        """)

        total_earnings = float(
            cur.fetchone()["total"] or 0
        )

        cur.execute("""
            SELECT
                u.id,
                u.name,
                u.referral_earnings,
                COUNT(r.id) AS referral_count
            FROM users u
            LEFT JOIN users r
                ON r.referrer_id = u.id
            GROUP BY u.id
            HAVING
                referral_count > 0
                OR u.referral_earnings > 0
            ORDER BY
                referral_count DESC,
                u.referral_earnings DESC
        """)

        referrers = cur.fetchall()

        cur.execute("""
            SELECT
                invited.id AS invited_id,
                invited.name AS invited_name,
                inviter.id AS inviter_id,
                inviter.name AS inviter_name
            FROM users invited
            JOIN users inviter
                ON inviter.id = invited.referrer_id
            ORDER BY
                inviter.id ASC,
                invited.id ASC
        """)

        pairs = cur.fetchall()

    finally:
        conn.close()

    text = (
        "👪 <b>РЕФЕРАЛЬНАЯ СТАТИСТИКА</b>\n\n"
        f"👥 Всего приглашено: "
        f"<b>{total_referrals}</b>\n"
        f"💰 Всего заработано: "
        f"<b>{total_earnings:.2f} USDT</b>\n"
        f"📈 Процент: "
        f"<b>{REFERRAL_PERCENT:.0f}%</b>\n"
    )

    if referrers:

        text += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "👑 <b>РЕФЕРЕРЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        for i, user in enumerate(
            referrers,
            1
        ):

            text += (
                f"\n<b>{i}. "
                f"{safe_text(user['name'] or 'Без имени')}</b>\n"
                f"🆔 ID: <code>{user['id']}</code>\n"
                f"👥 Пригласил: "
                f"<b>{user['referral_count']}</b>\n"
                f"💵 Заработал: "
                f"<b>{float(user['referral_earnings'] or 0):.2f} USDT</b>\n"
            )

    else:

        text += (
            "\n📭 <b>Рефералов пока нет.</b>"
        )

    if pairs:

        text += (
            "\n\n━━━━━━━━━━━━━━━━━━\n"
            "📋 <b>КТО КОГО ПРИГЛАСИЛ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        for pair in pairs:

            text += (
                f"\n👤 <b>"
                f"{safe_text(pair['inviter_name'] or 'Без имени')}"
                f"</b> "
                f"(<code>{pair['inviter_id']}</code>)"
                f"\n   ↳ "
                f"{safe_text(pair['invited_name'] or 'Без имени')}"
                f" (<code>{pair['invited_id']}</code>)\n"
            )

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "◀️ Назад",
            callback_data="admin_back"
        )
    )

    # Telegram ограничивает длину сообщения.
    chunks = []

    while len(text) > 3800:

        cut = text.rfind(
            "\n",
            0,
            3800
        )

        if cut < 100:
            cut = 3800

        chunks.append(
            text[:cut]
        )

        text = text[cut:]

    chunks.append(
        text
    )

    for index, chunk in enumerate(chunks):

        bot.send_message(
            call.message.chat.id,
            chunk,
            reply_markup=(
                markup
                if index == len(chunks) - 1
                else None
            )
        )


# ============================================================
# ADMIN BACK
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_back"
)
def admin_back(call):

    if not is_admin(
        call.from_user.id
    ):
        return

    bot.answer_callback_query(
        call.id
    )

    admin_menu(
        call.message.chat.id
    )


# ============================================================
# ADMIN STATISTICS
# ============================================================

def create_database_report():

    conn = get_db()
    cur = conn.cursor()

    def report_money(value):
        return f"{float(value or 0):.2f} USDT"

    def report_name(value):
        return (
            str(value or "Без имени")
            .replace("\n", " ")
            .strip()
        )

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            id,
            name,
            balance,
            referrer_id,
            referral_earnings,
            referral_balance
        FROM users
        ORDER BY id ASC
    """)

    users = cur.fetchall()

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    cur.execute(
        "SELECT COUNT(*) AS count FROM users"
    )
    total_users = cur.fetchone()["count"]

    cur.execute("""
        SELECT COUNT(*)
        AS count
        FROM users
        WHERE referrer_id IS NOT NULL
    """)
    total_referrals = cur.fetchone()["count"]

    cur.execute("""
        SELECT COALESCE(
            SUM(referral_earnings),
            0
        ) AS total
        FROM users
    """)
    total_referral_earnings = float(
        cur.fetchone()["total"] or 0
    )

    cur.execute("""
        SELECT COALESCE(
            SUM(referral_balance),
            0
        ) AS total
        FROM users
    """)
    total_referral_balance = float(
        cur.fetchone()["total"] or 0
    )

    cur.execute("""
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
    """)
    total_balances = float(
        cur.fetchone()["total"] or 0
    )

    cur.execute(
        "SELECT COUNT(*) AS count FROM purchases"
    )
    total_purchases = cur.fetchone()["count"]

    cur.execute("""
        SELECT COALESCE(
            SUM(price),
            0
        ) AS total
        FROM purchases
    """)
    total_sales = float(
        cur.fetchone()["total"] or 0
    )

    cur.execute("""
        SELECT COUNT(*)
        AS count
        FROM products
        WHERE active = 1
    """)
    active_products = cur.fetchone()["count"]

    cur.execute("""
        SELECT COUNT(*)
        AS count
        FROM stock
        WHERE sold = 0
    """)
    stock_left = cur.fetchone()["count"]

    # --------------------------------------------------------
    # WITHDRAWALS
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            rw.id,
            rw.user_id,
            rw.amount,
            rw.status,
            rw.transfer_id,
            rw.created_at,
            u.name AS user_name
        FROM referral_withdrawals rw
        LEFT JOIN users u
            ON u.id = rw.user_id
        ORDER BY rw.id DESC
    """)

    withdrawals = cur.fetchall()

    successful_withdrawn = 0.0
    pending_withdrawn = 0.0
    failed_withdrawn = 0.0

    for row in withdrawals:

        amount = float(
            row["amount"] or 0
        )

        status = (
            str(
                row["status"] or ""
            ).lower()
        )

        if status == "success":
            successful_withdrawn += amount

        elif status == "pending":
            pending_withdrawn += amount

        else:
            failed_withdrawn += amount

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    report = []

    report.extend([
        "=" * 70,
        "ОТЧЁТ ПО TELEGRAM-МАГАЗИНУ",
        "=" * 70,
        "",
        "СВОДКА",
        "-" * 70,
        f"Пользователей                 : {total_users}",
        f"Активных товаров              : {active_products}",
        f"Товаров на складе             : {stock_left}",
        f"Всего покупок                 : {total_purchases}",
        f"Оборот                         : {report_money(total_sales)}",
        f"Балансы пользователей         : {report_money(total_balances)}",
        "",
        "РЕФЕРАЛЬНАЯ ПРОГРАММА",
        "-" * 70,
        f"Всего приглашённых            : {total_referrals}",
        f"Начислено реферерам           : {report_money(total_referral_earnings)}",
        f"Доступно к выводу             : {report_money(total_referral_balance)}",
        f"Процент                       : {REFERRAL_PERCENT:.0f}%",
        "",
        "ВЫВОДЫ",
        "-" * 70,
        f"Успешно выведено              : {report_money(successful_withdrawn)}",
        f"В обработке                   : {report_money(pending_withdrawn)}",
        f"Неуспешно                     : {report_money(failed_withdrawn)}",
        f"Всего заявок                  : {len(withdrawals)}",
        "",
        "РЕФЕРЕРЫ",
        "-" * 70,
    ])

    cur.execute("""
        SELECT
            u.id,
            u.name,
            u.referral_earnings,
            u.referral_balance,
            COUNT(r.id) AS referral_count
        FROM users u
        LEFT JOIN users r
            ON r.referrer_id = u.id
        GROUP BY u.id
        HAVING
            referral_count > 0
            OR u.referral_earnings > 0
        ORDER BY
            referral_count DESC,
            u.referral_earnings DESC
    """)

    referrers = cur.fetchall()

    if not referrers:

        report.append(
            "Рефералов пока нет."
        )

    else:

        for place, user in enumerate(
            referrers,
            1
        ):

            report.extend([
                "",
                f"#{place} {report_name(user['name'])}",
                f"ID              : {user['id']}",
                f"Приглашено      : {user['referral_count']}",
                f"Заработано      : {report_money(user['referral_earnings'])}",
                f"Доступно        : {report_money(user['referral_balance'])}",
            ])

    # --------------------------------------------------------
    # REFERRAL LINKS
    # --------------------------------------------------------

    report.extend([
        "",
        "",
        "КТО КОГО ПРИГЛАСИЛ",
        "-" * 70,
    ])

    cur.execute("""
        SELECT
            invited.id AS invited_id,
            invited.name AS invited_name,
            inviter.id AS inviter_id,
            inviter.name AS inviter_name
        FROM users invited
        JOIN users inviter
            ON inviter.id = invited.referrer_id
        ORDER BY inviter.id, invited.id
    """)

    pairs = cur.fetchall()

    if not pairs:

        report.append(
            "Реферальных связей пока нет."
        )

    else:

        for pair in pairs:

            report.append(
                f"{report_name(pair['inviter_name'])} "
                f"(ID {pair['inviter_id']}) "
                f"-> "
                f"{report_name(pair['invited_name'])} "
                f"(ID {pair['invited_id']})"
            )

    # --------------------------------------------------------
    # WITHDRAWALS
    # --------------------------------------------------------

    report.extend([
        "",
        "",
        "ИСТОРИЯ ВЫВОДОВ",
        "-" * 70,
    ])

    if not withdrawals:

        report.append(
            "Выводов пока не было."
        )

    else:

        for withdrawal in withdrawals:

            report.extend([
                "",
                f"Заявка #{withdrawal['id']}",
                f"Пользователь : "
                f"{report_name(withdrawal['user_name'])} "
                f"(ID {withdrawal['user_id']})",
                f"Сумма        : "
                f"{report_money(withdrawal['amount'])}",
                f"Статус       : "
                f"{withdrawal['status']}",
                f"Transfer ID   : "
                f"{withdrawal['transfer_id'] or '-'}",
                f"Дата         : "
                f"{withdrawal['created_at']}",
            ])

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    report.extend([
        "",
        "",
        "ПОЛЬЗОВАТЕЛИ",
        "-" * 70,
    ])

    for user in users:

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM users
            WHERE referrer_id = ?
        """, (
            user["id"],
        ))

        invited_count = cur.fetchone()["count"]

        report.extend([
            "",
            f"Пользователь: {report_name(user['name'])}",
            f"ID                 : {user['id']}",
            f"Баланс             : {report_money(user['balance'])}",
            f"Реферальный баланс : {report_money(user['referral_balance'])}",
            f"Реферальный доход  : {report_money(user['referral_earnings'])}",
            f"Приглашено         : {invited_count}",
            f"Реферер            : {user['referrer_id'] or '-'}",
        ])

    # --------------------------------------------------------
    # PURCHASES
    # --------------------------------------------------------

    report.extend([
        "",
        "",
        "ПОКУПКИ",
        "-" * 70,
    ])

    cur.execute("""
        SELECT
            purchases.id,
            purchases.user_id,
            purchases.price,
            purchases.created_at,
            products.name AS product_name
        FROM purchases
        LEFT JOIN products
            ON products.id = purchases.product_id
        ORDER BY purchases.id DESC
    """)

    purchases = cur.fetchall()

    if not purchases:

        report.append(
            "Покупок пока нет."
        )

    else:

        for purchase in purchases:

            cur.execute(
                "SELECT name FROM users WHERE id = ?",
                (purchase["user_id"],)
            )

            buyer = cur.fetchone()

            buyer_name = (
                report_name(
                    buyer["name"]
                )
                if buyer
                else
                "Неизвестный пользователь"
            )

            report.extend([
                "",
                f"Покупка #{purchase['id']}",
                f"Покупатель : "
                f"{buyer_name} "
                f"(ID {purchase['user_id']})",
                f"Товар     : "
                f"{report_name(purchase['product_name'])}",
                f"Цена      : "
                f"{report_money(purchase['price'])}",
                f"Дата      : "
                f"{purchase['created_at']}",
            ])

    report.extend([
        "",
        "",
        "=" * 70,
        "КОНЕЦ ОТЧЁТА",
        "=" * 70,
    ])

    conn.close()

    return "\n".join(report)


@bot.callback_query_handler(
    func=lambda call:
        call.data == "admin_stats"
)
def admin_stats(call):

    if not is_admin(
        call.from_user.id
    ):

        bot.answer_callback_query(
            call.id,
            "❌ Доступ запрещён.",
            show_alert=True
        )

        return

    bot.answer_callback_query(
        call.id
    )

    conn = get_db()

    try:

        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) AS count FROM users"
        )

        users_count = cur.fetchone()["count"]

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM products
            WHERE active = 1
        """)

        products_count = cur.fetchone()["count"]

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM stock
            WHERE sold = 0
        """)

        stock_count = cur.fetchone()["count"]

        cur.execute(
            "SELECT COUNT(*) AS count FROM purchases"
        )

        purchases_count = cur.fetchone()["count"]

        cur.execute("""
            SELECT COALESCE(
                SUM(price),
                0
            ) AS total
            FROM purchases
        """)

        sales = float(
            cur.fetchone()["total"]
        )

        cur.execute("""
            SELECT COALESCE(
                SUM(balance),
                0
            ) AS total
            FROM users
        """)

        balances = float(
            cur.fetchone()["total"]
        )

    finally:
        conn.close()

    bot.send_message(
        call.message.chat.id,
        (
            "📊 <b>Статистика магазина</b>\n\n"
            f"👥 Пользователей: "
            f"<b>{users_count}</b>\n"
            f"🛍 Активных товаров: "
            f"<b>{products_count}</b>\n"
            f"📦 На складе: "
            f"<b>{stock_count}</b>\n"
            f"🛒 Покупок: "
            f"<b>{purchases_count}</b>\n"
            f"💵 Продаж: "
            f"<b>{sales:.2f} USDT</b>\n"
            f"💰 Балансы: "
            f"<b>{balances:.2f} USDT</b>"
        )
    )

    # --------------------------------------------------------
    # TXT REPORT
    # --------------------------------------------------------

    try:

        report = create_database_report()

        report_dir = os.path.dirname(DB_NAME) or "."
        os.makedirs(report_dir, exist_ok=True)

        file_path = os.path.join(
            report_dir,
            "database_report.txt"
        )

        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                report
            )

        with open(
            file_path,
            "rb"
        ) as file:

            bot.send_document(
                call.message.chat.id,
                file,
                caption=(
                    "📄 <b>Отчёт по базе данных</b>\n\n"
                    "Пользователи, покупки, балансы, "
                    "рефералы и выводы."
                )
            )

    except Exception as e:

        print(
            "Ошибка создания отчёта:",
            repr(e)
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Не удалось создать отчёт."
        )


# ============================================================
# BALANCE COMMAND
# ============================================================

@bot.message_handler(
    commands=["balance"]
)
def balance_command(message):

    add_user(
        message.from_user.id,
        message.from_user.first_name or "Пользователь"
    )

    balance = get_balance(
        message.from_user.id
    )

    bot.send_message(
        message.chat.id,
        (
            f"🆔 ID: "
            f"<code>{message.from_user.id}</code>\n"
            f"💰 Баланс: "
            f"<b>{balance:.2f} USDT</b>"
        )
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(
    commands=["help"]
)
def help_command(message):

    bot.send_message(
        message.chat.id,
        (
            "/start — магазин\n"
            "/balance — баланс\n"
            "/admin — админ-панель\n"
            "/help — помощь"
        )
    )


# ============================================================
# UNSUPPORTED FILES
# ============================================================

@bot.message_handler(
    content_types=[
        "photo",
        "video",
        "audio",
        "voice",
        "document",
        "sticker",
        "animation",
        "video_note",
        "location",
        "contact"
    ]
)
def unsupported(message):

    bot.send_message(
        message.chat.id,
        "❌ Этот формат сообщения не поддерживается."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    print("=" * 40)
    print("SHOP BOT")
    print("=" * 40)

    try:

        init_db()

        print(
            f"Database: {DB_NAME}"
        )

        bot.remove_webhook()

        print(
            "Bot started..."
        )

        bot.infinity_polling(
            skip_pending=True,
            timeout=30,
            long_polling_timeout=30
        )

    except KeyboardInterrupt:

        print(
            "\nBot stopped."
        )

    except Exception as e:

        print(
            "FATAL ERROR:",
            repr(e)
        )

        raise

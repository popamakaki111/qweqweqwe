import sqlite3
import requests
import telebot

from telebot import types


# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = "8880021634:AAG1LMSMsax5XRFFHzgaeLIgJlXrMEoWc6s"
CRYPTO_PAY_TOKEN = "626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ"

ADMIN_IDS = {
    6043107587
}

SUPPORT_USERNAME = "nomerzad"

DB_NAME = "/app/data/tabler.db"

CRYPTO_API_URL = "https://pay.crypt.bot/api"

bot = telebot.TeleBot(BOT_TOKEN)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect('tabler.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            balance REAL DEFAULT 0
        )
    """)

    # Если база была создана старой версией
    cur.execute("PRAGMA table_info(users)")
    columns = [row["name"] for row in cur.fetchall()]

    if "balance" not in columns:
        cur.execute("""
            ALTER TABLE users
            ADD COLUMN balance REAL DEFAULT 0
        """)

    # PAYMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            invoice_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)

    # PRODUCTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price REAL NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    # STOCK
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            sold INTEGER DEFAULT 0,
            buyer_id INTEGER
        )
    """)

    # PURCHASES
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

    # BALANCE HISTORY
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

    conn.commit()
    conn.close()


# ============================================================
# USERS
# ============================================================

def add_user(user_id, name):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users
        (id, name, balance)
        VALUES (?, ?, 0)
    """, (user_id, name))

    cur.execute("""
        UPDATE users
        SET name = ?
        WHERE id = ?
    """, (name, user_id))

    conn.commit()
    conn.close()


def get_balance(user_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT balance
        FROM users
        WHERE id = ?
    """, (user_id,))

    result = cur.fetchone()

    conn.close()

    if result:
        return float(result["balance"])

    return 0.0


def is_admin(user_id):
    return user_id in ADMIN_IDS


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
            "🆘 Поддержка",
            url=f"https://t.me/{SUPPORT_USERNAME}"
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
            f"💰 Баланс: <b>{balance:.2f} USDT</b>\n\n"
            "Выберите действие:"
        ),
        parse_mode="HTML",
        reply_markup=main_menu_markup()
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    add_user(
        message.from_user.id,
        message.from_user.first_name
    )

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True
    )

    markup.add(
        types.KeyboardButton("🚀 Начать")
    )

    bot.send_message(
        message.chat.id,
        (
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Нажмите «🚀 Начать», чтобы открыть магазин."
        ),
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(
    func=lambda message: message.text == "🚀 Начать"
)
def start_button(message):

    add_user(
        message.from_user.id,
        message.from_user.first_name
    )

    bot.send_message(
        message.chat.id,
        "🏪 Открываю магазин...",
        reply_markup=types.ReplyKeyboardRemove()
    )

    send_main_menu(message.chat.id)


# ============================================================
# MAIN MENU
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "main_menu"
)
def main_menu_callback(call):

    bot.answer_callback_query(call.id)

    balance = get_balance(call.from_user.id)

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=(
            "🏪 <b>Магазин</b>\n\n"
            f"🆔 Ваш ID: <code>{call.from_user.id}</code>\n"
            f"💰 Баланс: <b>{balance:.2f} USDT</b>\n\n"
            "Выберите действие:"
        ),
        parse_mode="HTML",
        reply_markup=main_menu_markup()
    )


# ============================================================
# BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "balance"
)
def balance_callback(call):

    bot.answer_callback_query(call.id)

    balance = get_balance(call.from_user.id)

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
            f"💵 Баланс: <b>{balance:.2f} USDT</b>"
        ),
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# PRODUCTS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "products"
)
def products_callback(call):

    bot.answer_callback_query(call.id)

    conn = get_db()
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

    conn.close()

    markup = types.InlineKeyboardMarkup(row_width=1)

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
                    f"{product['price']:.2f} USDT "
                    f"[{product['stock_count']} шт.]"
                )

            else:

                button_text = (
                    f"❌ {product['name']} — нет в наличии"
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
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# PRODUCT PAGE
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("product_")
)
def product_page(call):

    bot.answer_callback_query(call.id)

    try:
        product_id = int(
            call.data.replace("product_", "")
        )
    except ValueError:
        return

    conn = get_db()
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
    """, (product_id,))

    product = cur.fetchone()

    conn.close()

    if not product or not product["active"]:

        bot.answer_callback_query(
            call.id,
            "Товар недоступен.",
            show_alert=True
        )

        return

    text = (
        f"🛍 <b>{product['name']}</b>\n\n"
        f"{product['description'] or 'Описание отсутствует'}\n\n"
        f"💵 Цена: <b>{product['price']:.2f} USDT</b>\n"
        f"📦 В наличии: <b>{product['stock_count']} шт.</b>"
    )

    markup = types.InlineKeyboardMarkup()

    if product["stock_count"] > 0:

        markup.add(
            types.InlineKeyboardButton(
                f"🛒 Купить — {product['price']:.2f} USDT",
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
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# BUY
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("buy_")
)
def buy_product(call):

    user_id = call.from_user.id

    try:
        product_id = int(
            call.data.replace("buy_", "")
        )
    except ValueError:
        return

    conn = get_db()

    try:

        conn.execute("BEGIN IMMEDIATE")

        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM products
            WHERE id = ?
            AND active = 1
        """, (product_id,))

        product = cur.fetchone()

        if not product:
            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Товар не найден.",
                show_alert=True
            )

            return

        price = float(product["price"])

        cur.execute("""
            SELECT balance
            FROM users
            WHERE id = ?
        """, (user_id,))

        user = cur.fetchone()

        if not user:
            conn.rollback()

            bot.answer_callback_query(
                call.id,
                "Пользователь не найден.",
                show_alert=True
            )

            return

        balance = float(user["balance"])

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

        # Берём первую свободную единицу
        cur.execute("""
            SELECT *
            FROM stock
            WHERE product_id = ?
            AND sold = 0
            ORDER BY id ASC
            LIMIT 1
        """, (product_id,))

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

        # Списание
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

        # Помечаем товар проданным
        cur.execute("""
            UPDATE stock
            SET sold = 1,
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

        # Сохраняем покупку
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

        # История баланса
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

        new_balance = balance - price

    except Exception as e:

        conn.rollback()

        print("Ошибка покупки:", e)

        bot.answer_callback_query(
            call.id,
            "Произошла ошибка.",
            show_alert=True
        )

        return

    finally:
        conn.close()

    bot.answer_callback_query(
        call.id,
        "Покупка совершена!",
        show_alert=True
    )

    # АВТОВЫДАЧА
    bot.send_message(
        user_id,
        (
            "✅ <b>Покупка успешно совершена!</b>\n\n"
            f"🛍 Товар: <b>{product['name']}</b>\n"
            f"💵 Списано: <b>{price:.2f} USDT</b>\n"
            f"💰 Остаток: <b>{new_balance:.2f} USDT</b>\n\n"
            "📦 <b>Ваш товар:</b>\n\n"
            f"<code>{content}</code>"
        ),
        parse_mode="HTML"
    )


# ============================================================
# MY PURCHASES
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "my_purchases"
)
def my_purchases(call):

    bot.answer_callback_query(call.id)

    conn = get_db()
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
    """, (call.from_user.id,))

    purchases = cur.fetchall()

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
                f"<b>{name}</b>\n"
                f"💵 {float(purchase['price']):.2f} USDT\n"
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
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# CRYPTO PAY
# ============================================================

def create_invoice(amount):

    headers = {
        "Crypto-Pay-API-Token": '626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ'
    }

    data = {
        "currency_type": "crypto",
        "asset": "USDT",
        "amount": str(amount),
        "description": "Пополнение баланса"
    }

    try:

        response = requests.post(
            CRYPTO_API_URL + "/createInvoice",
            headers=headers,
            json=data,
            timeout=15
        )

        result = response.json()

        print("Crypto Pay:", result)

        if not result.get("ok"):

            print(
                "Ошибка Crypto Pay:",
                result
            )

            return None

        return result["result"]

    except Exception as e:

        print(
            "Ошибка запроса Crypto Pay:",
            e
        )

        return None


# ============================================================
# POPOLNENIE
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "popolnenie"
)
def payment_start(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        call.message.chat.id,
        (
            "💳 <b>Пополнение баланса</b>\n\n"
            "Введите сумму в USDT.\n\n"
            "Например:\n"
            "<code>10</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_amount
    )


def process_amount(message):

    try:

        amount = float(
            message.text.replace(",", ".")
        )

        if amount <= 0:
            raise ValueError

        amount = round(amount, 2)

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

    invoice = create_invoice(amount)

    if invoice is None:

        bot.send_message(
            message.chat.id,
            (
                "❌ Не удалось создать счёт.\n\n"
                "Попробуйте ещё раз позже."
            )
        )

        return

    invoice_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    conn = get_db()
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
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# CHECK PAYMENT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("check_")
)
def check_payment(call):

    bot.answer_callback_query(call.id)

    try:

        invoice_id = int(
            call.data.replace("check_", "")
        )

    except ValueError:
        return

    headers = {
        "Crypto-Pay-API-Token": '626975:AAHcB3lBYupqGUO5duUonVBLuDzzb5oITAJ'
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

        result = response.json()

        print("Crypto Pay:", result)

    except Exception as e:

        print(
            "Ошибка проверки платежа:",
            e
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Не удалось проверить платёж."
        )

        return

    if not result.get("ok"):

        print(
            "Crypto Pay:",
            result
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Ошибка Crypto Pay."
        )

        return

    invoices = result["result"]["items"]

    if not invoices:

        bot.send_message(
            call.message.chat.id,
            "❌ Счёт не найден."
        )

        return

    invoice = invoices[0]

    if invoice["status"] != "paid":

        bot.send_message(
            call.message.chat.id,
            "⏳ Оплата ещё не поступила."
        )

        return

    conn = get_db()

    try:

        conn.execute("BEGIN IMMEDIATE")

        cur = conn.cursor()

        cur.execute("""
            SELECT
                user_id,
                amount,
                status
            FROM payments
            WHERE invoice_id = ?
        """, (invoice_id,))

        payment = cur.fetchone()

        if not payment:

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "❌ Платёж не найден."
            )

            return

        # Защита от повторного зачисления
        if payment["status"] == "paid":

            conn.rollback()

            bot.send_message(
                call.message.chat.id,
                "ℹ️ Этот платёж уже был зачислен."
            )

            return

        user_id = payment["user_id"]
        amount = float(payment["amount"])

        cur.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE id = ?
        """, (
            amount,
            user_id
        ))

        cur.execute("""
            UPDATE payments
            SET status = 'paid'
            WHERE invoice_id = ?
        """, (invoice_id,))

        cur.execute("""
            INSERT INTO balance_history
            (
                user_id,
                admin_id,
                amount,
                operation,
                comment
            )
            VALUES (?, NULL, ?, 'deposit', 'Crypto Pay')
        """, (
            user_id,
            amount
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()

        print(
            "Ошибка зачисления:",
            e
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Ошибка при зачислении."
        )

        return

    finally:

        conn.close()

    new_balance = get_balance(user_id)

    bot.send_message(
        call.message.chat.id,
        (
            "✅ <b>Оплата получена!</b>\n\n"
            f"➕ Зачислено: <b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: <b>{new_balance:.2f} USDT</b>"
        ),
        parse_mode="HTML"
    )


# ============================================================
# ADMIN
# ============================================================

@bot.message_handler(commands=["admin"])
def admin(message):

    if not is_admin(message.from_user.id):

        bot.send_message(
            message.chat.id,
            "❌ Доступ запрещён."
        )

        return

    admin_menu(message.chat.id)


def admin_menu(chat_id):

    markup = types.InlineKeyboardMarkup(row_width=1)

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

    bot.send_message(
        chat_id,
        "👑 <b>Админ-панель</b>",
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# ADD PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_add_product"
)
def admin_add_product(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➕ <b>Создание товара</b>\n\n"
            "Введите:\n"
            "<code>Название | Цена | Описание</code>\n\n"
            "Например:\n"
            "<code>Netflix | 5 | "
            "Аккаунт Netflix на 30 дней</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_add_product
    )


def process_add_product(message):

    if not is_admin(message.from_user.id):
        return

    try:

        parts = message.text.split("|", 2)

        if len(parts) != 3:
            raise ValueError

        name = parts[0].strip()

        price = float(
            parts[1].strip().replace(",", ".")
        )

        description = parts[2].strip()

        if not name or price <= 0:
            raise ValueError

    except (ValueError, AttributeError):

        bot.send_message(
            message.chat.id,
            (
                "❌ Неверный формат.\n\n"
                "<code>Название | Цена | Описание</code>"
            ),
            parse_mode="HTML"
        )

        return

    conn = get_db()
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
    conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Товар создан!</b>\n\n"
            f"🆔 ID: <code>{product_id}</code>\n"
            f"🛍 {name}\n"
            f"💵 {price:.2f} USDT"
        ),
        parse_mode="HTML"
    )


# ============================================================
# ADMIN PRODUCTS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_products"
)
def admin_products(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    conn = get_db()
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

        markup = types.InlineKeyboardMarkup(row_width=2)

        markup.add(
            types.InlineKeyboardButton(
                "✏️ Изменить",
                callback_data=f"edit_product_{product['id']}"
            ),
            types.InlineKeyboardButton(
                "📦 Склад",
                callback_data=f"stock_product_{product['id']}"
            )
        )

        markup.add(
            types.InlineKeyboardButton(
                "🔴 Скрыть"
                if product["active"]
                else
                "🟢 Включить",
                callback_data=f"toggle_product_{product['id']}"
            )
        )

        bot.send_message(
            call.message.chat.id,
            (
                f"{status}\n\n"
                f"🆔 ID: <code>{product['id']}</code>\n"
                f"🛍 <b>{product['name']}</b>\n"
                f"💵 <b>{float(product['price']):.2f} USDT</b>\n"
                f"📦 На складе: <b>{product['stock_count']}</b>"
            ),
            parse_mode="HTML",
            reply_markup=markup
        )


# ============================================================
# EDIT PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("edit_product_")
)
def edit_product(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    product_id = int(
        call.data.replace("edit_product_", "")
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "✏️ Введите новые данные:\n\n"
            "<code>Название | Цена | Описание</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_edit_product,
        product_id
    )


def process_edit_product(message, product_id):

    if not is_admin(message.from_user.id):
        return

    try:

        parts = message.text.split("|", 2)

        if len(parts) != 3:
            raise ValueError

        name = parts[0].strip()

        price = float(
            parts[1].strip().replace(",", ".")
        )

        description = parts[2].strip()

        if not name or price <= 0:
            raise ValueError

    except (ValueError, AttributeError):

        bot.send_message(
            message.chat.id,
            "❌ Неверный формат."
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE products
        SET name = ?,
            price = ?,
            description = ?
        WHERE id = ?
    """, (
        name,
        price,
        description,
        product_id
    ))

    conn.commit()
    conn.close()

    bot.send_message(
        message.chat.id,
        "✅ Товар изменён."
    )


# ============================================================
# TOGGLE PRODUCT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("toggle_product_")
)
def toggle_product(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    product_id = int(
        call.data.replace("toggle_product_", "")
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT active FROM products WHERE id = ?",
        (product_id,)
    )

    product = cur.fetchone()

    if not product:

        conn.close()

        bot.send_message(
            call.message.chat.id,
            "❌ Товар не найден."
        )

        return

    new_status = 0 if product["active"] else 1

    cur.execute("""
        UPDATE products
        SET active = ?
        WHERE id = ?
    """, (
        new_status,
        product_id
    ))

    conn.commit()
    conn.close()

    bot.send_message(
        call.message.chat.id,
        "✅ Статус товара изменён."
    )


# ============================================================
# STOCK
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_stock"
)
def admin_stock(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    conn = get_db()
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

    conn.close()

    markup = types.InlineKeyboardMarkup(row_width=1)

    for product in products:

        markup.add(
            types.InlineKeyboardButton(
                f"📦 {product['name']} "
                f"({product['stock_count']} шт.)",
                callback_data=f"stock_product_{product['id']}"
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
        parse_mode="HTML",
        reply_markup=markup
    )


# ============================================================
# ADD STOCK
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("stock_product_")
)
def stock_product(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    product_id = int(
        call.data.replace("stock_product_", "")
    )

    msg = bot.send_message(
        call.message.chat.id,
        (
            "📦 Отправьте одну единицу товара.\n\n"
            "Например:\n"
            "<code>login:password</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_add_stock,
        product_id
    )


def process_add_stock(message, product_id):

    if not is_admin(message.from_user.id):
        return

    if not message.text:

        bot.send_message(
            message.chat.id,
            "❌ Товар не может быть пустым."
        )

        return

    content = message.text.strip()

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM products WHERE id = ?",
        (product_id,)
    )

    product = cur.fetchone()

    if not product:

        conn.close()

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
    conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Единица товара добавлена!</b>\n\n"
            f"ID склада: <code>{stock_id}</code>"
        ),
        parse_mode="HTML"
    )


# ============================================================
# ADMIN ADD BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_add_balance"
)
def admin_add_balance(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➕ <b>Начисление баланса</b>\n\n"
            "Введите:\n"
            "<code>ID сумма</code>\n\n"
            "Например:\n"
            "<code>123456789 50</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_admin_add_balance
    )


def process_admin_add_balance(message):

    if not is_admin(message.from_user.id):
        return

    try:

        parts = message.text.strip().split()

        if len(parts) != 2:
            raise ValueError

        user_id = int(parts[0])

        amount = float(
            parts[1].replace(",", ".")
        )

        if amount <= 0:
            raise ValueError

    except (ValueError, AttributeError):

        bot.send_message(
            message.chat.id,
            "❌ Формат: <code>ID сумма</code>",
            parse_mode="HTML"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE id = ?",
        (user_id,)
    )

    user = cur.fetchone()

    if not user:

        conn.close()

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
        VALUES (?, ?, ?, 'admin_add', 'Начисление администратором')
    """, (
        user_id,
        message.from_user.id,
        amount
    ))

    conn.commit()

    cur.execute(
        "SELECT balance FROM users WHERE id = ?",
        (user_id,)
    )

    new_balance = float(
        cur.fetchone()["balance"]
    )

    conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Баланс начислен</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"➕ Сумма: <b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: <b>{new_balance:.2f} USDT</b>"
        ),
        parse_mode="HTML"
    )

    try:

        bot.send_message(
            user_id,
            (
                "💰 <b>Баланс пополнен</b>\n\n"
                f"➕ Зачислено: <b>{amount:.2f} USDT</b>\n"
                f"💵 Баланс: <b>{new_balance:.2f} USDT</b>"
            ),
            parse_mode="HTML"
        )

    except Exception as e:

        print("Ошибка уведомления:", e)


# ============================================================
# ADMIN REMOVE BALANCE
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_remove_balance"
)
def admin_remove_balance(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        call.message.chat.id,
        (
            "➖ <b>Списание баланса</b>\n\n"
            "Введите:\n"
            "<code>ID сумма</code>\n\n"
            "Например:\n"
            "<code>123456789 20</code>"
        ),
        parse_mode="HTML"
    )

    bot.register_next_step_handler(
        msg,
        process_admin_remove_balance
    )


def process_admin_remove_balance(message):

    if not is_admin(message.from_user.id):
        return

    try:

        parts = message.text.strip().split()

        if len(parts) != 2:
            raise ValueError

        user_id = int(parts[0])

        amount = float(
            parts[1].replace(",", ".")
        )

        if amount <= 0:
            raise ValueError

    except (ValueError, AttributeError):

        bot.send_message(
            message.chat.id,
            "❌ Формат: <code>ID сумма</code>",
            parse_mode="HTML"
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE id = ?",
        (user_id,)
    )

    user = cur.fetchone()

    if not user:

        conn.close()

        bot.send_message(
            message.chat.id,
            "❌ Пользователь не найден."
        )

        return

    current_balance = float(
        user["balance"]
    )

    if current_balance < amount:

        conn.close()

        bot.send_message(
            message.chat.id,
            (
                "❌ <b>Недостаточно средств.</b>\n\n"
                f"Баланс: <b>{current_balance:.2f} USDT</b>\n"
                f"Списание: <b>{amount:.2f} USDT</b>"
            ),
            parse_mode="HTML"
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
        conn.close()

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
        VALUES (?, ?, ?, 'admin_remove', 'Списание администратором')
    """, (
        user_id,
        message.from_user.id,
        -amount
    ))

    conn.commit()

    cur.execute(
        "SELECT balance FROM users WHERE id = ?",
        (user_id,)
    )

    new_balance = float(
        cur.fetchone()["balance"]
    )

    conn.close()

    bot.send_message(
        message.chat.id,
        (
            "✅ <b>Баланс списан</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"➖ Списано: <b>{amount:.2f} USDT</b>\n"
            f"💰 Баланс: <b>{new_balance:.2f} USDT</b>"
        ),
        parse_mode="HTML"
    )

    try:

        bot.send_message(
            user_id,
            (
                "⚠️ <b>С вашего баланса списаны средства</b>\n\n"
                f"➖ Списано: <b>{amount:.2f} USDT</b>\n"
                f"💵 Баланс: <b>{new_balance:.2f} USDT</b>"
            ),
            parse_mode="HTML"
        )

    except Exception as e:

        print("Ошибка уведомления:", e)


# ============================================================
# DATABASE REPORT
# ============================================================

def create_database_report():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, balance
        FROM users
        ORDER BY id ASC
    """)

    users = cur.fetchall()

    report = []

    report.append("=" * 60)
    report.append("ОТЧЁТ ПО БАЗЕ ДАННЫХ МАГАЗИНА")
    report.append("=" * 60)
    report.append("")

    report.append(
        f"Всего пользователей: {len(users)}"
    )

    report.append("")

    for user in users:

        user_id = user["id"]
        name = user["name"] or "Без имени"
        balance = float(user["balance"] or 0)

        report.append("-" * 60)
        report.append(f"ID: {user_id}")
        report.append(f"Имя: {name}")
        report.append(f"Баланс: {balance:.2f} USDT")
        report.append("")

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
        """, (user_id,))

        purchases = cur.fetchall()

        if not purchases:

            report.append("Покупки: нет")

        else:

            report.append(
                f"Покупок: {len(purchases)}"
            )

            report.append("")

            for purchase in purchases:

                product_name = (
                    purchase["name"]
                    or "Удалённый товар"
                )

                report.append(
                    f"Покупка #{purchase['id']}"
                )

                report.append(
                    f"Товар: {product_name}"
                )

                report.append(
                    f"Цена: "
                    f"{float(purchase['price']):.2f} USDT"
                )

                report.append(
                    f"Дата: {purchase['created_at']}"
                )

                report.append("")

        report.append("")

    conn.close()

    return "\n".join(report)


# ============================================================
# ADMIN STATISTICS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_stats"
)
def admin_stats(call):

    if not is_admin(call.from_user.id):

        bot.answer_callback_query(
            call.id,
            "❌ Доступ запрещён.",
            show_alert=True
        )

        return

    bot.answer_callback_query(call.id)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) AS count FROM users"
    )

    users_count = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count "
        "FROM products WHERE active = 1"
    )

    products_count = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count "
        "FROM stock WHERE sold = 0"
    )

    stock_count = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count "
        "FROM purchases"
    )

    purchases_count = cur.fetchone()["count"]

    cur.execute(
        "SELECT COALESCE(SUM(price), 0) AS total "
        "FROM purchases"
    )

    sales = float(
        cur.fetchone()["total"]
    )

    cur.execute(
        "SELECT COALESCE(SUM(balance), 0) AS total "
        "FROM users"
    )

    balances = float(
        cur.fetchone()["total"]
    )

    conn.close()

    # Статистика
    bot.send_message(
        call.message.chat.id,
        (
            "📊 <b>Статистика магазина</b>\n\n"
            f"👥 Пользователей: <b>{users_count}</b>\n"
            f"🛍 Активных товаров: <b>{products_count}</b>\n"
            f"📦 На складе: <b>{stock_count}</b>\n"
            f"🛒 Покупок: <b>{purchases_count}</b>\n"
            f"💵 Продаж: <b>{sales:.2f} USDT</b>\n"
            f"💰 Балансы: <b>{balances:.2f} USDT</b>"
        ),
        parse_mode="HTML"
    )

    # Создаём TXT
    try:

        report = create_database_report()

        file_name = "database_report.txt"

        with open(
            file_name,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(report)

        with open(
            file_name,
            "rb"
        ) as file:

            bot.send_document(
                call.message.chat.id,
                file,
                caption=(
                    "📄 <b>Отчёт по базе данных</b>\n\n"
                    "Файл содержит ID пользователей, "
                    "имена, балансы и историю покупок."
                ),
                parse_mode="HTML"
            )

    except Exception as e:

        print(
            "Ошибка создания отчёта:",
            e
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Не удалось создать отчёт."
        )


# ============================================================
# ADMIN BACK
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "admin_back"
)
def admin_back(call):

    if not is_admin(call.from_user.id):
        return

    bot.answer_callback_query(call.id)

    admin_menu(
        call.message.chat.id
    )


# ============================================================
# BALANCE COMMAND
# ============================================================

@bot.message_handler(commands=["balance"])
def balance_command(message):

    add_user(
        message.from_user.id,
        message.from_user.first_name
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
        ),
        parse_mode="HTML"
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(commands=["help"])
def help_command(message):

    bot.send_message(
        message.chat.id,
        (
            "/start — магазин\n"
            "/balance — баланс\n"
            "/admin — админ-панель"
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
        "document"
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

    init_db()

    print("==============================")
    print("       SHOP BOT STARTED")
    print("==============================")

    bot.remove_webhook()
    bot.infinity_polling()
from flask import Flask, render_template, request, jsonify, redirect, url_for
import requests
import sqlite3
import functools
import time

app = Flask(__name__)
DB_FILE = "watchlist.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coin TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'usd')""")
    c.execute("""CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coin TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'usd')""")
    conn.commit()
    conn.close()

init_db()

CACHE = {}
CACHE_TTL = 60

def cached(ttl=CACHE_TTL):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            hashable_args = tuple(tuple(a) if isinstance(a, list) else a for a in args)
            key = (func.__name__, hashable_args, frozenset(kwargs.items()))
            if key in CACHE:
                value, timestamp = CACHE[key]
                if time.time() - timestamp < ttl:
                    return value
            result = func(*args, **kwargs)
            CACHE[key] = (result, time.time())
            return result
        return wrapper
    return decorator

@cached()
def fetch_prices(cryptos, currency="usd"):
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(cryptos), "vs_currencies": currency}
    return requests.get(url, params=params).json()

@cached()
def fetch_history(coin, currency="usd", days=7):
    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
    params = {"vs_currency": currency, "days": days}
    response = requests.get(url, params=params).json()
    return response.get("prices", [])

@cached()
def fetch_trending():
    url = "https://api.coingecko.com/api/v3/search/trending"
    return requests.get(url).json().get("coins", [])

@cached()
def fetch_market():
    url = "https://api.coingecko.com/api/v3/global"
    return requests.get(url).json().get("data", {})

SYMBOL_TO_ID = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "doge": "dogecoin",
    "dodgecoin": "dogecoin" 
}

@app.route("/", methods=["GET", "POST"])
def index():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT coin, currency FROM watchlist")
    rows = c.fetchall()
    conn.close()

    cryptos = [r[0] for r in rows] if rows else ["bitcoin", "ethereum", "dogecoin"]
    currency = rows[0][1] if rows else "usd"

    if request.method == "POST":
        cryptos_input = request.form.get("cryptos", "")
        currency = request.form.get("currency", "usd").lower()
        cryptos = []
        for c in cryptos_input.split(","):
            key = c.strip().lower()
            cryptos.append(SYMBOL_TO_ID.get(key, key)) 

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM watchlist")
        for coin in cryptos:
            c.execute("INSERT INTO watchlist (coin, currency) VALUES (?, ?)", (coin, currency))
        conn.commit()
        conn.close()

    prices = fetch_prices(cryptos, currency)
    for coin in cryptos:
        if coin not in prices:
            prices[coin] = {currency: 0}

    trending = fetch_trending()
    market = fetch_market()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT coin, amount, currency FROM holdings")
    holdings = c.fetchall()
    conn.close()

    portfolio_value = 0
    portfolio_details = []
    if holdings:
        all_coins = [h[0] for h in holdings]
        price_data = fetch_prices(all_coins, currency)
        for coin, amount, curr in holdings:
            coin_price = price_data.get(coin, {}).get(curr, 0)
            value = amount * coin_price
            portfolio_value += value
            portfolio_details.append({"coin": coin, "amount": amount, "price": coin_price, "value": value})

    color_palette = ['#00c853', '#2979ff', '#ff9100', '#d500f9', '#ff1744', '#00b0ff', '#ffd600']
    for idx, t in enumerate(trending):
        t['color_class'] = f'color{idx % len(color_palette)}'

    return render_template("index.html",
                           prices=prices,
                           currency=currency,
                           cryptos=cryptos,
                           trending=trending,
                           market=market,
                           portfolio=portfolio_details,
                           total_value=portfolio_value,
                           color_palette=color_palette)

@app.route("/prices")
def prices_api():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT coin, currency FROM watchlist")
    rows = c.fetchall()
    conn.close()

    cryptos = [r[0] for r in rows] if rows else ["bitcoin", "ethereum", "dogecoin"]
    currency = rows[0][1] if rows else "usd"
    return jsonify(fetch_prices(cryptos, currency))

@app.route("/history/<coin>")
def history(coin):
    currency = request.args.get("currency", "usd")
    data = fetch_history(coin, currency)
    if not data:
        return jsonify([[int(time.time()*1000), 0]])
    return jsonify(data)

@app.route("/add_holding", methods=["POST"])
def add_holding():
    coin = request.form.get("coin").lower()
    amount = float(request.form.get("amount"))
    currency = request.form.get("currency", "usd").lower()

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO holdings (coin, amount, currency) VALUES (?, ?, ?)", (coin, amount, currency))
    conn.commit()
    conn.close()

    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)

import os
import hmac
import ccxt
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'), override=True)

app = Flask(__name__)

# ===== КОНФИГУРАЦИЯ =====
GATE_API_KEY = os.getenv("GATE_API_KEY")
GATE_API_SECRET = os.getenv("GATE_API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "moy_secret_123")
MARKET_TYPE = os.getenv("GATE_MARKET_TYPE", "spot")  # spot или swap
DRY_RUN = str(os.getenv("DRY_RUN", "false")).lower() in ("1","true","yes")

if DRY_RUN:
    print("🧪 DRY_RUN включен - реальные ордера НЕ отправляются")

if not GATE_API_KEY or not GATE_API_SECRET:
    print("❌ ВНИМАНИЕ: Не заданы GATE_API_KEY / GATE_API_SECRET в .env файле!")

# Подключение к Gate через ccxt
exchange = ccxt.gate({
    'apiKey': GATE_API_KEY,
    'secret': GATE_API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': MARKET_TYPE  # spot для спота, swap для фьючерсов
    }
})

# Для фьючерсов Gate требует settle
if MARKET_TYPE == 'swap':
    exchange.options['defaultSettle'] = 'usdt'

# Если ключи Testnet - включаем тестовую сеть Gate
# Для реальных ключей поставь GATE_USE_TESTNET=false в .env
USE_TESTNET = str(os.getenv('GATE_USE_TESTNET', 'true')).lower() in ('1','true','yes')
if USE_TESTNET:
    try:
        exchange.set_sandbox_mode(True)
        print("🧪 Включен TESTNET режим Gate (api-test.gateio.ws)")
    except Exception as e:
        print(f"⚠️ Не удалось включить testnet: {e}")
        # fallback - ручная подмена URL
        exchange.urls['api'] = 'https://api-test.gateio.ws'

print(f"✅ Бот настроен на рынок: {MARKET_TYPE} | testnet={USE_TESTNET}")

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "market_type": MARKET_TYPE,
        "time": datetime.now().isoformat(),
        "endpoints": {
            "webhook": "/webhook - POST сюда шлет TradingView",
            "test": "/test - проверка ключей"
        }
    })

@app.route('/test')
def test_connection():
    """Проверка что ключи рабочие"""
    try:
        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        return jsonify({"ok": True, "USDT_free": usdt, "market_type": MARKET_TYPE})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # 1. Проверка секрета (защита от чужих запросов)
        # TradingView будет слать ?secret=твой_пароль или в JSON поле secret
        secret_from_url = request.args.get('secret')
        data = request.get_json(force=True, silent=True)
        if data is None:
            # иногда TradingView шлет текст
            data = {}
            try:
                import json
                data = json.loads(request.data.decode('utf-8'))
            except:
                pass

        secret_from_json = data.get('secret') if isinstance(data, dict) else None
        
        # Если задан WEBHOOK_SECRET - проверяем
        if WEBHOOK_SECRET and WEBHOOK_SECRET != "moy_secret_123":
            if secret_from_url != WEBHOOK_SECRET and secret_from_json != WEBHOOK_SECRET:
                print(f"❌ Неверный секрет! url={secret_from_url} json={secret_from_json}")
                return jsonify({"error": "invalid secret"}), 403

        print(f"\n{'='*50}")
        print(f"📩 Входящий вебхук: {datetime.now()}")
        print(f"Данные: {data}")

        # 2. Парсим сигнал
        # Поддерживаем разные форматы:
        # {"action":"buy", "symbol":"SOL/USDT", "amount":"10"} 
        # {"action":"buy", "price": 65000} - от TradingView
        action = str(data.get('action', '')).lower().strip()
        symbol = data.get('symbol', 'SOL/USDT')  # по умолчанию BTC/USDT
        amount_type = data.get('amount_type', 'usdt') # usdt или coin
        amount_value = data.get('amount', 10) # 10 USDT по умолчанию
        price = data.get('price')

        # Нормализуем symbol: TradingView шлет BTCUSDT или BINANCE:BTCUSDT
        symbol = symbol.replace('BINANCE:', '').replace('GATEIO:', '').replace('GATE:', '')
        if '/' not in symbol and 'USDT' in symbol:
            # BTCUSDT -> BTC/USDT, BTCUSDT.P -> BTC/USDT
            symbol = symbol.replace('.P','').replace('.p','')
            symbol = symbol.replace('USDT', '/USDT')
        
        # Для фьючерсов формат CCXT: BTC/USDT:USDT
        if MARKET_TYPE == 'swap' and ':USDT' not in symbol:
            symbol = symbol + ':USDT'

        print(f"➡️ Команда: {action} | Пара: {symbol} | Сумма: {amount_value} {amount_type} | Цена: {price}")

        if action not in ['buy', 'sell', 'long', 'short', 'close', 'close_long', 'close_short']:
            return jsonify({"error": f"unknown action '{action}'. Use buy/sell"}), 400

        # Холостой режим - сразу отвечаем без обращения к бирже (чтобы не падать на minimum amount)
        if DRY_RUN:
            print(f"🧪 DRY_RUN: БЫ {'КУПИЛ' if action in ['buy','long'] else 'ПРОДАЛ'} {symbol} amount={amount_value} {amount_type} action={action} - реальный ордер НЕ отправлен")
            return jsonify({"ok": True, "dry_run": True, "action": action, "symbol": symbol, "amount": amount_value, "amount_type": amount_type}), 200

        # 3. Конвертируем сумму
        # Если amount_type == usdt, то покупаем на N USDT
        # Если coin - то N монет
        amount = float(amount_value)
        
        if amount_type == 'usdt' and action in ['buy', 'long']:
            # Нужно узнать цену чтобы посчитать кол-во монет
            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            print(f"Цена {symbol}: {last_price}")
            # Gate имеет минималки, считаем кол-во с учетом комиссии
            amount = amount / last_price
            # Округляем под лот биржи
            amount = exchange.amount_to_precision(symbol, amount)
            amount = float(amount)
            print(f"Пересчитано в монеты: {amount} {symbol}")

        # Для продажи - если usdt, то продаем на N USDT (только для спота, для фьючей закрываем всю позицию)
        if MARKET_TYPE == 'spot' and amount_type == 'usdt' and action in ['sell', 'short', 'close']:
            # Для sell если указан usdt - просто продаем эквивалент
            # Но для спота нужно проверить баланс
            if action == 'sell':
                ticker = exchange.fetch_ticker(symbol)
                last_price = ticker['last']
                amount = amount / last_price
                amount = float(exchange.amount_to_precision(symbol, amount))

        # 4. Исполняем ордер
        order = None

        if MARKET_TYPE == 'spot':
            if action in ['buy', 'long']:
                print(f"🟢 ПОКУПКА {amount} {symbol} по рынку...")
                order = exchange.create_market_buy_order(symbol, amount)
            elif action in ['sell', 'short', 'close', 'close_long', 'close_short']:
                # Для спота short = sell
                # Проверяем баланс чтобы не продать больше чем есть
                balance = exchange.fetch_balance()
                coin = symbol.split('/')[0].split(':')[0]
                free = balance.get(coin, {}).get('free', 0)
                print(f"Баланс {coin}: {free}")
                if free < amount:
                    print(f"⚠️ На балансе меньше чем нужно, продаем все что есть: {free}")
                    amount = free
                    amount = float(exchange.amount_to_precision(symbol, amount))
                if amount == 0:
                    return jsonify({"error": f"no balance {coin}"}), 400
                print(f"🔴 ПРОДАЖА {amount} {symbol} по рынку...")
                order = exchange.create_market_sell_order(symbol, amount)

        else: # swap - фьючерсы (buy=открыть лонг, sell/short=закрыть лонг)
            if action in ['buy', 'long']:
                # ставим плечо 10x перед открытием
                try:
                    lev = int(os.getenv('GATE_LEVERAGE', '10'))
                    exchange.set_leverage(lev, symbol)
                    print(f"⚙️ Плечо установлено: {lev}x для {symbol}")
                except Exception as e:
                    print(f"⚠️ Не удалось поставить плечо: {e}")
                print(f"🟢 ЛОНГ {amount} {symbol}...")
                order = exchange.create_market_buy_order(symbol, amount)
            elif action in ['sell', 'short', 'close', 'close_long', 'close_short']:
                # Закрыть позицию - берем размер позиции и закрываем обратным ордером
                # Для юзера short = закрыть buy, а не открыть шорт
                try:
                    positions = exchange.fetch_positions([symbol])
                except:
                    positions = exchange.fetch_positions()
                size = 0
                side = None
                for p in positions:
                    # Gate отдает symbol как BTC/USDT:USDT
                    if symbol in p['symbol'] or p['symbol'] in symbol:
                        contracts = float(p.get('contracts') or p.get('size') or 0)
                        if contracts != 0:
                            size = contracts
                            side = p.get('side') or ('long' if float(p.get('size',0))>0 else 'short')
                            break
                print(f"Позиция: {side} {size}")
                if size == 0:
                    return jsonify({"error": "no open position to close"}), 400
                # Закрываем
                if side == 'long':
                    order = exchange.create_market_sell_order(symbol, abs(size))
                    print(f"🔴 ЗАКРЫВАЮ ЛОНГ {abs(size)} {symbol}...")
                else:
                    order = exchange.create_market_buy_order(symbol, abs(size))
                    print(f"🟢 ЗАКРЫВАЮ ШОРТ {abs(size)} {symbol}...")

        print(f"✅ ОРДЕР ИСПОЛНЕН: {order['id']} | {order['symbol']} | {order['side']} {order['amount']}")
        print(f"{'='*50}\n")

        return jsonify({
            "ok": True, 
            "order_id": order['id'],
            "symbol": order['symbol'],
            "side": order['side'],
            "amount": order['amount'],
            "price": order.get('price') or price
        })

    except ccxt.InsufficientFunds as e:
        print(f"❌ Недостаточно средств: {e}")
        return jsonify({"ok": False, "error": "InsufficientFunds", "details": str(e)}), 400
    except ccxt.NetworkError as e:
        print(f"❌ Ошибка сети Gate: {e}")
        return jsonify({"ok": False, "error": "NetworkError", "details": str(e)}), 500
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    print(f"""
╔════════════════════════════════════════╗
║   Gate Trading Bot запущен!            ║
║   Порт: {port}                              ║
║   Webhook: http://localhost:{port}/webhook?secret={WEBHOOK_SECRET} ║
║   Проверка: http://localhost:{port}/test   ║
╚════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=port, debug=False)

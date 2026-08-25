# Gate Trading Bot - TradingView -> Gate.io

## Что делает
Принимает сигнал BUY/SELL из TradingView и автоматически открывает сделку на Gate.io

## Быстрый старт (5 минут)

### 1. Установи Python зависимости
```
pip install -r requirements.txt
```

### 2. Создай API ключи на Gate.io
1. Зайди на https://www.gate.io/myaccount/api_key_manage
2. Нажми "Create API Key" -> "Classic Account"
3. Права: ✅ Read, ✅ Spot Trade (и Futures Trade если нужны фьючи)
4. IP не ограничивай пока тестируешь
5. Скопируй Key и Secret

### 3. Настрой бота
1. Скопируй `.env.example` в `.env`
2. Вставь свои ключи в `.env`
3. Выбери рынок: `spot` или `swap` (swap = фьючерсы)

### 4. Запусти
```
python app.py
```
Открой http://localhost:5000/test - должен показать баланс USDT

### 5. Сделай бота доступным из интернета (для TradingView нужен https)
Вариант А - через ngrok (для теста):
```
ngrok http 5000
```
Скопируй https://xxxx.ngrok-free.app/webhook?secret=moy_secret_123

Вариант Б - залить на Render/Railway (чтобы работал 24/7 бесплатно)

### 6. Настрой TradingView
1. Открой график, выбери стратегию/индикатор
2. Создай Алерт (часы с +)
3. Условие: твоя стратегия -> Long / Buy
4. Включи галочку `Webhook URL` -> вставь свой https url
5. В поле Сообщение вставь:

Для СПОТА покупка на 10 USDT:
```json
{
  "action": "buy",
  "symbol": "BTC/USDT",
  "amount": 10,
  "amount_type": "usdt",
  "secret": "moy_secret_123"
}
```

Для продажи:
```json
{
  "action": "sell",
  "symbol": "BTC/USDT",
  "amount": 10,
  "amount_type": "usdt",
  "secret": "moy_secret_123"
}
```

Для ФЬЮЧЕРСОВ лонг 20 USDT:
```json
{
  "action": "long",
  "symbol": "BTC/USDT",
  "amount": 20,
  "secret": "moy_secret_123"
}
```

Готово! Теперь при сигнале BUY бот купит.

## Проверка без TradingView
Можно тестить прямо из браузера/PowerShell:
```
curl -X POST "http://localhost:5000/webhook?secret=moy_secret_123" -H "Content-Type: application/json" -d "{\"action\":\"buy\",\"symbol\":\"BTC/USDT\",\"amount\":5}"
```

@echo off
echo Starting tunnel for TradingView...
echo Keep this window open!
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -R 80:localhost:5000 nokey@localhost.run
pause

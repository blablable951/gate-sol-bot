@echo off
echo Установка зависимостей...
pip install -r requirements.txt
echo.
echo Запуск бота...
python app.py
pause

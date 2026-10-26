@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==========================================
echo        Job Scout AI - הפעלה ב-Windows
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo שגיאה: Python Launcher לא נמצא.
    echo התקיני Python 3.10 ומעלה מ- https://www.python.org/downloads/windows/
    echo במהלך ההתקנה סמני Add Python to PATH.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo יוצר סביבת Python מקומית...
    py -m venv .venv
    if errorlevel 1 goto error
)

echo מתקין או בודק ספריות נדרשות...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto error

echo.
echo פותח את Job Scout AI בדפדפן...
echo אם הדפדפן לא נפתח, העתיקי את הכתובת שמופיעה בטרמינל.
echo לסיום לחצי Ctrl+C בחלון הזה.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 goto error
exit /b 0

:error
echo.
echo ההפעלה נכשלה. בדקי חיבור לאינטרנט ושהותקנה גרסת Python 3.10 ומעלה.
echo מפתח Groq מזינים בתוך האפליקציה, לא בתוך קובץ ה-BAT.
pause
exit /b 1

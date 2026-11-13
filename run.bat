@echo off
chcp 65001 >nul
REM ============================================================
REM  祁煜桌面伙伴 · 直接运行（不打包 EXE，需已装 Python+PySide6）
REM  用法：双击 run.bat 即可
REM ============================================================
cd /d "%~dp0"
python -m pip install -r requirements.txt
python main.py
pause

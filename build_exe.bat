@echo off
chcp 65001 >nul
REM ============================================================
REM  祁煜桌面伙伴 · 一键打包 EXE（需在 Windows 上运行）
REM  双击本脚本即可生成 qiyu.exe，点开即用。
REM ============================================================
cd /d "%~dp0"

echo [1/4] 检查 Python ...
where python >nul 2>nul
if errorlevel 1 (
    echo 未检测到 Python，请先安装 Python 3.9+（勾选 Add to PATH）：https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [2/4] 安装依赖（PySide6 / pyinstaller）...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo [3/4] 打包中，请稍候 ...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name qiyu ^
    --add-data "qiyu_pet\sprites;qiyu_pet\sprites" ^
    main.py

echo [4/4] 完成！
echo.
echo 生成位置： %~dp0dist\qiyu.exe
echo 把 qiyu.exe 拷到任意目录，双击即可运行。
pause

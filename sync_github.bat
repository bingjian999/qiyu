@echo off
chcp 65001 >nul
REM ============================================================
REM  祁煜桌面伙伴 · 一键同步到 GitHub
REM  前提：本机已能 push 到 GitHub（已登录 git 凭证 / 装了 Git Credential Manager）
REM ============================================================
cd /d "%~dp0"

echo 请先在 GitHub 上新建一个空仓库（不要勾选 README/.gitignore/license），复制它的 HTTPS 地址。
set /p REPO="粘贴仓库地址 (https://github.com/用户名/仓库名.git): "

REM 确保 .gitignore 存在
if not exist .gitignore (
echo __pycache__/>.gitignore
echo *.py[cod]>>.gitignore
echo .pytest_cache\>>.gitignore
echo build\>>.gitignore
echo dist\>>.gitignore
echo *.spec>>.gitignore
)

git init
git add -A
git commit -m "祁煜桌面伙伴：人物化桌面伙伴（《恋与深空》祁煜）"
git branch -M main
git remote remove origin 2>nul
git remote add origin "%REPO%"
echo 正在推送到 GitHub ...
git push -u origin main

echo.
if errorlevel 1 (echo 推送失败：请检查仓库地址 / GitHub 登录状态。) else (echo 推送成功！打开 %REPO% 查看。)
pause

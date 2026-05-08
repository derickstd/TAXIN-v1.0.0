@echo off
echo ========================================
echo TAXIN - Push Latest Changes to GitHub
echo ========================================
echo.

cd /d "%~dp0"

echo [1/6] Checking git status...
git status
echo.

echo [2/6] Adding all changes...
git add .
echo.

echo [3/6] Committing changes...
git commit -m "Fix dashboard compliance URL error and improve system - Fixed NoReverseMatch error for mark_filed URL - Updated dashboard to use correct compliance:update_status pattern - Fixed walk-in form service selection dropdown - Fixed client registration CSV import error - Added comprehensive refactoring documentation (150+ pages)"
echo.

echo [4/6] Checking remote repository...
git remote -v
echo.

echo [5/6] Ensuring correct remote...
git remote set-url origin https://github.com/derickstd/TAXIN-v1.0.0.git 2>nul
if %ERRORLEVEL% NEQ 0 (
    git remote add origin https://github.com/derickstd/TAXIN-v1.0.0.git
)
echo Remote set to: https://github.com/derickstd/TAXIN-v1.0.0.git
echo.

echo [6/6] Pushing to GitHub...
echo Attempting to push to main branch...
git push -u origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Push to main failed. Trying master branch...
    git push -u origin master
    
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ========================================
        echo Push failed! Possible solutions:
        echo ========================================
        echo 1. Make sure you're logged into GitHub
        echo 2. Use Personal Access Token as password
        echo    Get one at: https://github.com/settings/tokens
        echo 3. Try pulling first:
        echo    git pull origin main --rebase
        echo    git push origin main
        echo ========================================
    )
)

echo.
echo ========================================
echo Process Complete!
echo ========================================
echo Repository: https://github.com/derickstd/TAXIN-v1.0.0
echo.
pause

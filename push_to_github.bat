@echo off
echo ========================================
echo TAXIN - Push to GitHub
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
git commit -m "Fix walk-in form service selection and add comprehensive refactoring documentation - Walk-in purpose now uses service catalogue dropdown - Client registration CSV error fixed - Added 150+ pages of refactoring documentation - Added visual workflow diagrams and implementation guides"
echo.

echo [4/6] Checking remote repository...
git remote -v
echo.

echo [5/6] Setting remote repository...
git remote remove origin 2>nul
git remote add origin https://github.com/derickstd/TAXIN-v1.0.0.git
echo.

echo [6/6] Pushing to GitHub...
git push -u origin main
echo.

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo Push failed! Trying with master branch...
    echo ========================================
    git push -u origin master
)

echo.
echo ========================================
echo Done! Check the output above for any errors.
echo ========================================
echo.
pause

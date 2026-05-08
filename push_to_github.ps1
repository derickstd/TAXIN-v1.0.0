# TAXIN - Push to GitHub (PowerShell)
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "TAXIN - Push to GitHub" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Navigate to script directory
Set-Location $PSScriptRoot

Write-Host "[1/7] Checking git installation..." -ForegroundColor Yellow
try {
    $gitVersion = git --version
    Write-Host "✓ Git found: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Git not found! Please install Git from https://git-scm.com/download/win" -ForegroundColor Red
    pause
    exit
}
Write-Host ""

Write-Host "[2/7] Checking git status..." -ForegroundColor Yellow
git status
Write-Host ""

Write-Host "[3/7] Adding all changes..." -ForegroundColor Yellow
git add .
Write-Host "✓ All changes staged" -ForegroundColor Green
Write-Host ""

Write-Host "[4/7] Committing changes..." -ForegroundColor Yellow
$commitMessage = @"
Fix walk-in form service selection and add comprehensive refactoring documentation

- Walk-in purpose now uses service catalogue dropdown
- Client registration CSV error fixed
- Added 150+ pages of refactoring documentation
- Added visual workflow diagrams and implementation guides
- Added quick start guide for immediate improvements
"@

git commit -m $commitMessage
Write-Host "✓ Changes committed" -ForegroundColor Green
Write-Host ""

Write-Host "[5/7] Checking remote repository..." -ForegroundColor Yellow
$remotes = git remote -v
if ($remotes) {
    Write-Host "Current remotes:" -ForegroundColor Cyan
    Write-Host $remotes
} else {
    Write-Host "No remotes configured" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "[6/7] Setting remote repository..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin https://github.com/derickstd/TAXIN-v1.0.0.git
Write-Host "✓ Remote set to: https://github.com/derickstd/TAXIN-v1.0.0.git" -ForegroundColor Green
Write-Host ""

Write-Host "[7/7] Pushing to GitHub..." -ForegroundColor Yellow
Write-Host "Attempting to push to 'main' branch..." -ForegroundColor Cyan

$pushResult = git push -u origin main 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Successfully pushed to main branch!" -ForegroundColor Green
} else {
    Write-Host "Push to 'main' failed. Trying 'master' branch..." -ForegroundColor Yellow
    $pushResult = git push -u origin master 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Successfully pushed to master branch!" -ForegroundColor Green
    } else {
        Write-Host "✗ Push failed!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Error details:" -ForegroundColor Red
        Write-Host $pushResult -ForegroundColor Red
        Write-Host ""
        Write-Host "Common solutions:" -ForegroundColor Yellow
        Write-Host "1. Make sure you're logged into GitHub (derickstd account)" -ForegroundColor White
        Write-Host "2. You may need a Personal Access Token instead of password" -ForegroundColor White
        Write-Host "   Get one at: https://github.com/settings/tokens" -ForegroundColor White
        Write-Host "3. Try pulling first: git pull origin main --rebase" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Process Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Repository: https://github.com/derickstd/TAXIN-v1.0.0" -ForegroundColor Cyan
Write-Host ""

pause

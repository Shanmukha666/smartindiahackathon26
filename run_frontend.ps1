# Script to run frontend development server
Write-Host "Starting Vite frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\frontend"
npm run dev

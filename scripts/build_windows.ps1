# Local Windows recruiter zip (run from the repo root in PowerShell)
# Output: dist\Pathwise\Pathwise.exe plus pathwise.env.example and RECRUITER.md
# Then zip that folder. Never commit dist\ or a built exe.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm Pathwise.spec
Copy-Item -Force pathwise.env.example dist\Pathwise\pathwise.env.example
Copy-Item -Force docs\RECRUITER.md dist\Pathwise\RECRUITER.md
if (Test-Path Pathwise-recruiter.zip) { Remove-Item Pathwise-recruiter.zip }
Compress-Archive -Path dist\Pathwise -DestinationPath Pathwise-recruiter.zip
Write-Host "Wrote Pathwise-recruiter.zip. Put pathwise.env next to Pathwise.exe, not inside _internal."

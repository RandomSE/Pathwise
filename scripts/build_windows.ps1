# Local Windows recruiter zip (run from the repo root in PowerShell)
# Requires -EnvFile pointing at your gitignored pathwise.env.
# Output: Pathwise-recruiter.zip. Recruiter: unzip and double-click Pathwise.exe.
# Never commit dist\, pathwise.env, pathwise\_generated\, or a built exe.

param(
    [Parameter(Mandatory = $true)]
    [string]$EnvFile
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m pathwise.pack --env $EnvFile

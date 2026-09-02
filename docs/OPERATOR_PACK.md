# Operator pack (recruiter zip)

Recruiters unzip and double-click. They must not create `pathwise.env`, install Python, or copy keys. You pack secrets into the zip on your machine.

## Local keys

Keep a gitignored `pathwise.env` (copy `pathwise.env.example`) with Turso URL/token and optional SMTP keys. Never commit `pathwise.env`. Never commit `pathwise/_generated/`.

## Pack command

From the repo root, after `pip install -r requirements.txt pyinstaller`:

```
python -m pathwise.pack --env pathwise.env
```

Windows PowerShell equivalent:

```
powershell -File scripts/build_windows.ps1 -EnvFile pathwise.env
```

`--env` is required. Pack refuses to write a recruiter zip without it so you do not ship an empty-secrets exe as the recruiter product.

Output: `Pathwise-recruiter.zip` (onedir + this recruiter one-pager). Email or send that zip. Do not put plaintext `pathwise.env` in the zip; pack strips those filenames if they appear under `dist/Pathwise`.

## What pack does

1. Reads `--env`.
2. Writes an obfuscated blob under `pathwise/_generated/` (gitignored).
3. Runs PyInstaller `Pathwise.spec` so the frozen exe bundles that blob.
4. Stages a short unzip-and-run page. No example env files.

At runtime the exe loads the blob first (`setdefault` into `os.environ`) before recruiter login. A sidecar `pathwise.env` next to the exe may still override blob keys if you are debugging a local build. Recruiters do not need that file.

## This is obfuscation, not a vault

A determined person can reverse PyInstaller and recover the packed env. Do not treat the zip as a secret store. Do not paste real tokens into git, tests, CI logs, or spec comments. Rotate Turso/SMTP credentials if a zip leaks.

## GitHub Actions zip

The Recruiter Windows zip workflow may pack with `tests/fixtures/recruiter_pack.env` (fake URL/token) so COLLECT still runs. That artifact is a CI smoke build, not the recruiter handoff. The handoff zip is the local pack with your real env.

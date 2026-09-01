# Recruiter one-pager

Unzip `Pathwise-recruiter.zip`. Put `pathwise.env` in the SAME FOLDER as `Pathwise.exe` (the folder that contains the exe, not `_internal`). Double-click `Pathwise.exe`.

1. On the play screen, choose Recruiter login (candidates stay on this screen and play with no secrets).
2. Log in or Create account.
3. Set rounds and difficulty.
4. Generate seed.
5. Copy the code and send it to the candidate. They paste it on the play screen.

If SMTP keys are set in `pathwise.env`, a dashboard zip is emailed when a candidate finishes that seed. If those keys are missing, email stays off; after a local recruiter session the app shows the full path to `logs_dashboard.html` and can open it.

Never email `TURSO_AUTH_TOKEN`. It is full database access. Do not put secrets inside `_internal`.

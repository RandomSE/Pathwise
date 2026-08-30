How to run Pathwise
Pathwise is built with Python and Arcade. To get started, set up a clean environment and install dependencies.

1. Create a Virtual Environment 
It's best practice to isolate dependencies in a virtual environment.
Windows: (command prompt / terminal) python -m venv venv
MacOS/Linux: (bash/zsh) python3 -m venv venv

2. Activate the Virtual Environment
Windows: Open a new command prompt at the project's root directory. Then, run venv\Scripts\activate
MacOS/Linux: Open a new bash/zsh at the project's root directory. Then,  run source venv/bin/activate
If successful, your terminal prompt will show (venv) before the path.

3. Install Dependencies
From the project root with the venv activated: `pip install -r requirements.txt`

- **Python 3.14:** may need `pip install "Pillow>=11.3.0"` before installing Arcade.
- **Python 3.12-3.13:** `pip install -r requirements.txt` is usually sufficient.

Use Python 3.9+ (3.12 is the primary tested target).

4. Run Pathwise
In the same OS-specific terminal opened in step 2, run `python main.py` (or `python pathwise_window.py`).

**Candidate (default):** the app opens on the play screen. Paste or type an optional recruiter seed, then **Play set seed** or **Play random seed** (empty field). **Ctrl+V** pastes into the seed field. **Configure seed** opens recruiter options.

**Recruiter:** set rounds (1-5) and difficulty, then **Generate seed** to create a 10-digit code that encodes the map seed, rounds, and preset. **Start session** runs the full configuration locally; **Back to play area** copies the generated seed to the candidate screen for candidates to use.

Cross roads without hitting cars; reach the goal before time runs out. With **more than one round**, each round uses a derived map from the same session seed and gets harder (faster traffic, denser spawns, tighter lights).

**Recruiter fairness (env pin):** `set PATHWISE_SEED=12345` (Windows) still pins map generation for scripted runs and is recorded in `logs.json` (`session_seed`, `seed_source`, `pathwise_seed_env`). Candidate quick play with an empty seed does **not** use `PATHWISE_SEED`; it rolls random instead. **Adaptive maps:** when neither a typed/generated seed nor `PATHWISE_SEED` fixes a seed, map layout tunes from the prior session in `logs.json`.

5. View Recruiter Analytics
After each run, Pathwise writes `logs.json` (decision sequence, hesitation events, heatmap samples) and auto-generates `logs_dashboard.html`.
**Car motion diagnostics:** abnormal traffic events (backward movement, 10s+ stalls) append to `car_diagnostics.jsonl`: share this file when reporting car AI bugs.
Open the HTML file in a browser to see a **game-derived session profile** (independent in-game trait bars, role **target similarity**, and a cosmetic session-flavor badge) plus a **frame-by-frame replay** (roads, cars, traffic lights, player) with a scrubber and jump-to-decision markers.

Scoring is three-layer and face-valid only: (1) continuous in-game trait dimensions, (2) cosmetic archetype labels for the game UI, (3) weighted distance to a versioned in-repo role catalog (`ROLE_CATALOG_VERSION`). Catalog targets are design priors, not criterion-fitted. Role similarity is omitted when measured catalog weight is below 0.50 coverage. Decision tempo uses one function (`tempo_from_commit_s`); logs tag `commit_time_s` vs `quick_slow_fallback`. These numbers describe Pathwise session behavior. They are not construct-valid or criterion-valid, and they do not predict on-the-job performance. Hiring views must read `traits` and `role_fits`, not `primary_archetype`.

To rebuild the dashboard from an existing log: `python -m analytics.dashboard logs.json`

6. Run Tests and Coverage
Install dev dependencies: `pip install -r requirements-dev.txt`
Run tests: `python -m pytest tests/ -q`
Coverage gate (≥95% line coverage on `pathwise/`, `map_generation/`, `analytics/`, `main.py`): `python -m pytest tests/ --cov=pathwise --cov=map_generation --cov=analytics --cov=main --cov-report=term-missing --cov-config=.coveragerc`
Measured baseline (2026-08-26): **95.0%** with `pathwise/car.py` and spectate/traffic-audit CLI modules omitted in `.coveragerc`.

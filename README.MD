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
- **Python 3.12–3.13:** `pip install -r requirements.txt` is usually sufficient.

Use Python 3.9+ (3.12 is the primary tested target).

4. Run Pathwise
In the same OS-specific terminal opened in step 2, run `python main.py` (or `python pathwise_window.py`).
A **pre-game menu** lets you pick difficulty (Easy / Normal / Hard), the number of rounds (default **1**, up to 5), and an optional map seed. Cross roads without hitting cars; reach the goal before time runs out. With **more than one round**, each round uses a derived map from the same session seed and gets harder (faster traffic, denser spawns, tighter lights).

**Recruiter fairness:** run the same map for every candidate with a fixed seed:
`set PATHWISE_SEED=12345` (Windows) then `python main.py` — the seed is prefilled on the menu and recorded in `logs.json` (`session_seed`, `seed_source`, `pathwise_seed_env`). You can still override it in the menu. **Adaptive maps:** when neither the menu nor `PATHWISE_SEED` fixes a seed, map layout tunes from the prior session in `logs.json` (traffic/light difficulty still follows your menu preset).

5. View Recruiter Analytics
After each run, Pathwise writes `logs.json` (decision sequence, hesitation events, heatmap samples) and auto-generates `logs_dashboard.html`.
**Car motion diagnostics:** abnormal traffic events (backward movement, 10s+ stalls) append to `car_diagnostics.jsonl` — share this file when reporting car AI bugs.
Open the HTML file in a browser to see role-tailored archetype scores and a **frame-by-frame replay** (roads, cars, traffic lights, player) with a scrubber and jump-to-decision markers.
To rebuild the dashboard from an existing log: `python -m analytics.dashboard logs.json`

6. Run Tests and Coverage
Install dev dependencies: `pip install -r requirements-dev.txt`
Run tests: `python -m pytest tests/ -q`
Coverage gate (≥95% line coverage on `pathwise/`, `map_generation/`, `analytics/`, `main.py`): `python -m pytest tests/ --cov=pathwise --cov=map_generation --cov=analytics --cov=main --cov-report=term-missing --cov-config=.coveragerc`
Measured baseline (2026-06-11): **91.7%** — the gate fails until `main.py` Car logic is extracted and more unit tests can target `pathwise.car` (see Follow-Up Queue).

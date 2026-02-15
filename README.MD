How to run Pathwise
Pathwise is built with Python and pygame. To get started, set up a clean environment and install dependencies.

1. Create a Virtual Environment 
It’s best practice to isolate dependencies in a virtual environment.
Windows: (command prompt / terminal) python -m venv venv
MacOS/Linux: (bash/zsh) python3 -m venv venv

2. Activate the Virtual Environment
Windows: Open a new command prompt at the project's root directory. Then, run venv\Scripts\activate
MacOS/Linux: Open a new bash/zsh at the project's root directory. Then,  run source venv/bin/activate
If successful, your terminal prompt will show (venv) before the path.

3. Install Dependencies
Ensure pygame is installed. run pip install pygame (if on Linux / Mac, use pip3 instead)
*** Make sure you’re using Python 3.9+ (pygame requires modern Python).

4. Run Pathwise
in the same OS specific terminal opened in step 2, run python main.py
It should then launch, and place you in a random map. To participate, cross the roads without making contact with incoming traffic. The round ends upon reaching either the goal location (win) or making contact with a car (fail)
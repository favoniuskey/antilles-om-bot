import subprocess
import os
import sys

REPO_URL = "https://github.com/favoniuskey/antilles-om-bot.git"
WORKDIR = "/home/container"

if os.path.isdir(os.path.join(WORKDIR, ".git")):
    print("[start.py] Git repo détecté, pull en cours...")
    subprocess.run(["git", "pull"], cwd=WORKDIR)
else:
    print("[start.py] Initialisation du repo git...")
    subprocess.run(["git", "init"], cwd=WORKDIR)
    subprocess.run(["git", "remote", "add", "origin", REPO_URL], cwd=WORKDIR)
    subprocess.run(["git", "fetch", "origin"], cwd=WORKDIR)
    subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=WORKDIR)
    print("[start.py] Repo initialisé !")

os.execv(sys.executable, [sys.executable, "/home/container/main.py"])

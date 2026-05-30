#!/bin/sh
cd /home/container
if [ -d .git ]; then
    git fetch origin
    git checkout -B main origin/main
else
    git clone https://github.com/favoniuskey/antilles-om-bot.git .
fi
pip install --prefer-binary -r requirements.txt
python main.py

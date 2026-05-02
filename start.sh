#!/bin/sh
cd /home/container
if [ -d .git ]; then
    git pull
else
    git clone https://github.com/favoniuskey/antilles-om-bot.git .
fi
pip install --prefer-binary -r requirements.txt
python main.py
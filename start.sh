#!/bin/sh
cd /home/container
if [ -d .git ]; then
    git pull
else
    git clone ${GIT_REPO} .
fi
pip install --prefer-binary -r requirements.txt
python ${BOT_PY}
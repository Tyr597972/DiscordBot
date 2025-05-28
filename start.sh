#!/bin/bash
pip install -r requirements.txt --no-cache-dir
apt-get update && apt-get install -y ffmpeg
python3 Bot.py
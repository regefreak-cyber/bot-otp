#!/bin/bash
echo "Installing requirements..."
pip3 install -r requirements.txt

echo "Starting Forwarder Bot in background..."
nohup python3 -u forward.py > output.log 2>&1 &
echo "Bot started! Check output.log for logs."

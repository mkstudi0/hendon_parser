#!/bin/bash

echo "Installing Playwright browsers..."
python -m playwright install --with-deps

echo "Starting Flask server..."
python main.py

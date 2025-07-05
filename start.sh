#!/bin/bash

echo "Installing Playwright browsers..."
python -m playwright install --with-deps

echo "Starting server..."
python main.py

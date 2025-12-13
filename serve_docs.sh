#!/bin/bash
# Simple script to serve HTML documentation locally
# This enables search functionality which doesn't work with file:// protocol

PORT=${1:-8000}

echo "========================================="
echo "EA-IDL Documentation Server"
echo "========================================="
echo ""
echo "Starting HTTP server on port $PORT..."
echo "Open in browser: http://localhost:$PORT"
echo ""
echo "Press Ctrl+C to stop"
echo "========================================="
echo ""

cd docs && python3 -m http.server $PORT

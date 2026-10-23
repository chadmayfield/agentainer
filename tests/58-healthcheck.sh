#!/bin/sh
# Test the image's health command and automatic engine health transitions.
exec python3 "$(dirname "$0")/host/test-healthcheck.py"

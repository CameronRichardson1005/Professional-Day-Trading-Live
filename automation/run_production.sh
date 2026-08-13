#!/bin/zsh

cd /Users/cameronrichardson/PycharmProjects/Professional-Day-Trading-Live || exit 1

export PYTHONUNBUFFERED=1

exec /Users/cameronrichardson/PycharmProjects/PythonProjects/bin/python \
    main.py production

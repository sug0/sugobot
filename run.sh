#!/bin/bash

trap '' INT

rm -f bot.log
python bot.py bot.log

#!/bin/bash
trap "echo; echo 'script end'; exit" SIGINT
echo "if want end ,Ctrl + C"

while true
do
    python manage.py scheduled
    echo update
    sleep 30s
done
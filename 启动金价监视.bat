@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 金价监视
set PYTHONIOENCODING=utf-8
"D:\App\Anaconda\anaconda3\envs\aurum\python.exe" watch_gold.py
pause

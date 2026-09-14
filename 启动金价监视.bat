@echo off
rem Double-click launcher: pythonw starts the watch window with no console.
rem To see errors in a terminal, run: python.exe -m aurumwatch
cd /d "%~dp0"
start "" "D:\App\Anaconda\anaconda3\envs\aurum\pythonw.exe" -m aurumwatch

@echo off
REM DisciplineFuel Instagram Pipeline — 3 posts per run
REM Scheduled 3x daily: 06:00 / 13:00 / 20:00 via Windows Task Scheduler
REM Total: 9 posts/day (within Instagram's 25/day API limit)

cd /d "%~dp0"
echo [%date% %time%] Starting DisciplineFuel pipeline... >> .tmp\disciplinefuel\pipeline.log

python tools\run_discipline_pipeline.py --account disciplinefuel --count 3

echo [%date% %time%] Pipeline run complete. >> .tmp\disciplinefuel\pipeline.log

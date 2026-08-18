@echo off
REM ============================================================
REM  M05 - Question Intelligence, on its own.
REM
REM  This module's services only (PORTS.txt: API 8105).
REM  No sibling repos, so concepts come from the committed
REM  ontology snapshot and /v1/deps names the modules it would
REM  have used - which is the fastest way to check that the
REM  clone-and-run promise still holds.
REM
REM  Usage:  start_questions.bat          launch M05
REM          start_questions.bat -Check   verify prerequisites only
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Only m05 -Title "M05 - Question Intelligence" %*

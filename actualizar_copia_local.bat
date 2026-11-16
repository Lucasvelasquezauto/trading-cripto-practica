@echo off
chcp 65001 >nul
rem Trae a esta carpeta lo último que guardó el bot diario en GitHub (estado de los libros, informes e informe.html).
rem No toca el bot intradía, la investigación ni los respaldos: esos archivos no están en GitHub.
rem Si alguien cambió a mano archivos del bot en esta carpeta, se guardan aparte (git stash) antes de actualizar.
cd /d "%~dp0"
git diff --quiet HEAD
if errorlevel 1 (
  echo Hay cambios locales en archivos del bot: se guardan aparte antes de actualizar.
  git stash push -m "copia local antes de actualizar"
)
git pull --ff-only
if errorlevel 1 (
  echo.
  echo No se pudo actualizar. Abre Claude en esta carpeta y escribe: revisa el trading
) else (
  echo.
  echo Listo: la copia local quedó igual a la de GitHub.
)
pause

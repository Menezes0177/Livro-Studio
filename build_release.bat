@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo LivroStudio V3.5 - BUILD FINAL ONLINE
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERRO: Python nao encontrado no PATH.
    pause
    exit /b 1
)

set "LOCAL_CONFIG=%LOCALAPPDATA%\LivroStudio\online_config.json"
if not exist "%LOCAL_CONFIG%" (
    echo ERRO: configuracao online nao encontrada:
    echo %LOCAL_CONFIG%
    echo.
    echo Abra o LivroStudio, configure o Supabase e conecte uma vez.
    pause
    exit /b 1
)

copy /Y "%LOCAL_CONFIG%" "supabase_config.json" >nul
if errorlevel 1 (
    echo ERRO: nao foi possivel copiar a configuracao do Supabase.
    pause
    exit /b 1
)

echo Configuracao Supabase encontrada e preparada para o build.
echo.

echo [1/3] Instalando/atualizando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [2/3] Gerando executavel com PyInstaller...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --clean --noconfirm LivroStudio.spec
if errorlevel 1 goto :fail
if not exist "dist\LivroStudio\LivroStudio.exe" goto :fail

echo.
echo [3/3] Gerando instalador Inno Setup...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo AVISO: Inno Setup 6 nao encontrado.
    echo O executavel foi criado em dist\LivroStudio\LivroStudio.exe
    echo Instale o Inno Setup 6 e execute este arquivo novamente.
    pause
    exit /b 0
)

if exist installer rmdir /s /q installer
mkdir installer
"%ISCC%" LivroStudio.iss
if errorlevel 1 goto :fail

if exist installer\LivroStudio_Setup_3.5.0.exe (
    echo.
    echo ============================================================
    echo BUILD CONCLUIDO COM SUCESSO!
    echo Instalador: installer\LivroStudio_Setup_3.5.0.exe
    echo ============================================================
    pause
    exit /b 0
)

goto :fail

:fail
echo.
echo ============================================================
echo ERRO DURANTE O BUILD.
echo ============================================================
pause
exit /b 1

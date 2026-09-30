@ECHO off
REM Copyright 2014 The Flutter Authors. All rights reserved.
REM Use of this source code is governed by a BSD-style license that can be
REM found in the LICENSE file.

REM Bootstrap the engine SDK packages needed to compile the Flutter tool.

IF DEFINED powershell_executable (
  %powershell_executable% -ExecutionPolicy Bypass -NoProfile -File "%FLUTTER_ROOT%\bin\internal\bootstrap.ps1"
  EXIT /B %ERRORLEVEL%
)

WHERE /Q pwsh
IF "%ERRORLEVEL%" EQU "0" (
  pwsh -NoProfile -File "%FLUTTER_ROOT%\bin\internal\bootstrap.ps1"
  EXIT /B %ERRORLEVEL%
)

PowerShell.exe -ExecutionPolicy Bypass -NoProfile -File "%FLUTTER_ROOT%\bin\internal\bootstrap.ps1"
EXIT /B %ERRORLEVEL%

# Copyright 2014 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# A fresh checkout cannot resolve Flutter's Pub workspace until the engine SDK
# packages exist. Bootstrap only those packages before shared.bat builds the
# Flutter tool; the tool's normal cache logic handles every other artifact.
$ErrorActionPreference = 'Stop'

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$flutterRoot = (Get-Item $scriptDirectory).Parent.Parent.FullName
$packageRoot = Join-Path $flutterRoot 'bin\cache\pkg'
$requiredPackages = @('sky_engine', 'flutter_gpu')

$packagesPresent = $true
foreach ($packageName in $requiredPackages) {
  if (!(Test-Path -LiteralPath (Join-Path $packageRoot "$packageName\pubspec.yaml"))) {
    $packagesPresent = $false
  }
}
if ($packagesPresent) {
  return
}

$storageBaseUrl = $env:FLUTTER_STORAGE_BASE_URL
$configuredStorageFile = Join-Path $flutterRoot 'bin\internal\flutter_storage_base_url'
if ([string]::IsNullOrWhiteSpace($storageBaseUrl) -and (Test-Path -LiteralPath $configuredStorageFile)) {
  $storageBaseUrl = (Get-Content -LiteralPath $configuredStorageFile -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($storageBaseUrl)) {
  throw 'FLUTTER_STORAGE_BASE_URL is required to bootstrap this Flutter fork.'
}
$storageBaseUrl = $storageBaseUrl.TrimEnd('/')

$engineVersion = (Get-Content -LiteralPath (Join-Path $flutterRoot 'bin\internal\engine.version') -Raw).Trim()
New-Item -Path $packageRoot -ItemType Directory -Force | Out-Null

foreach ($packageName in $requiredPackages) {
  $packageDirectory = Join-Path $packageRoot $packageName
  if (Test-Path -LiteralPath (Join-Path $packageDirectory 'pubspec.yaml')) {
    continue
  }

  $archiveUrl = "$storageBaseUrl/flutter_infra_release/flutter/$engineVersion/$packageName.zip"
  $archivePath = Join-Path $flutterRoot "bin\cache\$packageName.bootstrap.$PID.zip"
  Write-Host "Bootstrapping Flutter SDK package $packageName..."
  Remove-Item -LiteralPath $packageDirectory -Recurse -Force -ErrorAction SilentlyContinue
  try {
    $previousProgressPreference = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
    $ProgressPreference = $previousProgressPreference
    Expand-Archive -LiteralPath $archivePath -DestinationPath $packageRoot -Force
  } finally {
    $ProgressPreference = $previousProgressPreference
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
  }

  if (!(Test-Path -LiteralPath (Join-Path $packageDirectory 'pubspec.yaml'))) {
    throw "Bootstrapped archive did not contain $packageName/pubspec.yaml."
  }
}

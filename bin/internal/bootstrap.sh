#!/usr/bin/env bash
# Copyright 2014 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# A fresh checkout cannot resolve Flutter's Pub workspace until the engine SDK
# packages exist. Bootstrap only those packages before shared.sh builds the
# Flutter tool; the tool's normal cache logic handles every other artifact.
function _wsc_bootstrap_engine_packages() {
  local package_root="$FLUTTER_ROOT/bin/cache/pkg"
  if [[ -f "$package_root/sky_engine/pubspec.yaml" && -f "$package_root/flutter_gpu/pubspec.yaml" ]]; then
    return
  fi

  local storage_base_url="${FLUTTER_STORAGE_BASE_URL:-}"
  if [[ -z "$storage_base_url" && -f "$FLUTTER_ROOT/bin/internal/flutter_storage_base_url" ]]; then
    IFS= read -r storage_base_url < "$FLUTTER_ROOT/bin/internal/flutter_storage_base_url"
  fi
  if [[ -z "$storage_base_url" ]]; then
    >&2 echo 'FLUTTER_STORAGE_BASE_URL is required to bootstrap this Flutter fork.'
    return 1
  fi
  storage_base_url="${storage_base_url%/}"

  local engine_version
  IFS= read -r engine_version < "$FLUTTER_ROOT/bin/internal/engine.version"
  mkdir -p "$package_root"

  local package_name package_dir archive_url archive_path
  for package_name in sky_engine flutter_gpu; do
    package_dir="$package_root/$package_name"
    if [[ -f "$package_dir/pubspec.yaml" ]]; then
      continue
    fi
    archive_url="$storage_base_url/flutter_infra_release/flutter/$engine_version/$package_name.zip"
    archive_path="$FLUTTER_ROOT/bin/cache/$package_name.bootstrap.$$.zip"
    >&2 echo "Bootstrapping Flutter SDK package $package_name..."
    rm -rf "$package_dir"
    if ! curl --fail --location --retry 3 --silent --show-error --output "$archive_path" "$archive_url"; then
      rm -f "$archive_path"
      return 1
    fi
    if ! unzip -oq "$archive_path" -d "$package_root"; then
      rm -f "$archive_path"
      return 1
    fi
    rm -f "$archive_path"
    if [[ ! -f "$package_dir/pubspec.yaml" ]]; then
      >&2 echo "Bootstrapped archive did not contain $package_name/pubspec.yaml."
      return 1
    fi
  done
}

_wsc_bootstrap_engine_packages
unset -f _wsc_bootstrap_engine_packages

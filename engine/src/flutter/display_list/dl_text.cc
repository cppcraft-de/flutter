// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "flutter/display_list/dl_text.h"

#include <memory>

#include "flutter/fml/status.h"

namespace flutter {

fml::StatusOr<DlPath> DlText::GetPath() const {
  return fml::Status(fml::StatusCode::kCancelled, "No path available.");
}

bool DlText::operator==(const DlText& other) const {
  return GetTextBlob() == other.GetTextBlob() &&
         GetTextFrame() == other.GetTextFrame();
}

}  // namespace flutter

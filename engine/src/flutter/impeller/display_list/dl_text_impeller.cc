// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "flutter/impeller/display_list/dl_text_impeller.h"

#include "flutter/impeller/typographer/backends/skia/text_frame_skia.h"

namespace flutter {

std::shared_ptr<DlTextImpeller> DlTextImpeller::Make(
    const std::shared_ptr<impeller::TextFrame>& frame) {
  return std::make_shared<DlTextImpeller>(frame);
}

std::shared_ptr<DlTextImpeller> DlTextImpeller::MakeFromBlob(
    const sk_sp<SkTextBlob>& blob) {
  return std::make_shared<DlTextImpeller>(
      impeller::MakeTextFrameFromTextBlobSkia(blob), blob);
}

DlTextImpeller::DlTextImpeller(
    const std::shared_ptr<impeller::TextFrame>& frame,
    sk_sp<SkTextBlob> blob)
    : frame_(frame), blob_(std::move(blob)) {}

fml::StatusOr<DlPath> DlTextImpeller::GetPath() const {
  return frame_->GetPath();
}

}  // namespace flutter

// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef FLUTTER_TXT_SRC_TXT_FREETYPE_FONT_MANAGER_H_
#define FLUTTER_TXT_SRC_TXT_FREETYPE_FONT_MANAGER_H_

#include "third_party/skia/include/core/SkFontMgr.h"
#include "third_party/skia/include/core/SkRefCnt.h"
#include "third_party/skia/include/core/SkTypeface.h"

namespace txt {

sk_sp<SkFontMgr> MakeFreeTypeCanonicalFontManager(
    sk_sp<SkFontMgr> font_manager);

sk_sp<SkTypeface> MakeFreeTypeCanonicalTypeface(sk_sp<SkTypeface> typeface);

bool IsFreeTypeCanonicalTypefaceForTesting(const SkTypeface* typeface);

}  // namespace txt

#endif  // FLUTTER_TXT_SRC_TXT_FREETYPE_FONT_MANAGER_H_

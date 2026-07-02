// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "txt/platform.h"
#include "txt/freetype_font_manager.h"

#if defined(SK_FONTMGR_FREETYPE_EMPTY_AVAILABLE)
#include "third_party/skia/include/ports/SkFontMgr_empty.h"
#endif

namespace txt {

std::vector<std::string> GetDefaultFontFamilies() {
  return {"Arial"};
}

sk_sp<SkFontMgr> GetDefaultFontManager(uint32_t font_initialization_data) {
#if defined(SK_FONTMGR_FREETYPE_EMPTY_AVAILABLE)
  static sk_sp<SkFontMgr> mgr =
      MakeFreeTypeCanonicalFontManager(SkFontMgr_New_Custom_Empty());
#else
  static sk_sp<SkFontMgr> mgr =
      MakeFreeTypeCanonicalFontManager(SkFontMgr::RefEmpty());
#endif
  return mgr;
}

}  // namespace txt

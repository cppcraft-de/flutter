// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "gtest/gtest.h"

#include <sstream>

#include "flutter/runtime/test_font_data.h"
#include "txt/asset_font_manager.h"
#include "txt/font_collection.h"
#include "txt/freetype_font_manager.h"
#include "txt/typeface_font_asset_provider.h"

namespace txt {
namespace testing {

class FontCollectionTests : public ::testing::Test {
 public:
  FontCollectionTests() {}

  void SetUp() override {}
};

TEST_F(FontCollectionTests, SettingUpDefaultFontManagerClearsCache) {
  FontCollection font_collection;
  sk_sp<skia::textlayout::FontCollection> sk_font_collection =
      font_collection.CreateSktFontCollection();
  ASSERT_EQ(sk_font_collection->getFallbackManager().get(), nullptr);
  font_collection.SetupDefaultFontManager(0);
  sk_font_collection = font_collection.CreateSktFontCollection();
  ASSERT_NE(sk_font_collection->getFallbackManager().get(), nullptr);
}

TEST_F(FontCollectionTests, DefaultFontManagerCreatesFreeTypeTypefaceFromData) {
  std::vector<sk_sp<SkTypeface>> typefaces = flutter::GetTestFontData();
  ASSERT_FALSE(typefaces.empty());

  EXPECT_TRUE(IsFreeTypeCanonicalTypefaceForTesting(typefaces.front().get()));
}

TEST_F(FontCollectionTests, WrappedStyleSetReturnsFreeTypeTypeface) {
  std::vector<sk_sp<SkTypeface>> typefaces = flutter::GetTestFontData();
  ASSERT_FALSE(typefaces.empty());

  auto font_provider = std::make_unique<TypefaceFontAssetProvider>();
  font_provider->RegisterTypeface(typefaces.front(), "FlutterTest");
  sk_sp<SkFontMgr> manager = MakeFreeTypeCanonicalFontManager(
      sk_make_sp<AssetFontManager>(std::move(font_provider)));

  sk_sp<SkFontStyleSet> style_set = manager->matchFamily("FlutterTest");
  ASSERT_NE(style_set, nullptr);
  ASSERT_GT(style_set->count(), 0);

  sk_sp<SkTypeface> typeface = style_set->matchStyle(SkFontStyle());
  ASSERT_NE(typeface, nullptr);
  EXPECT_TRUE(IsFreeTypeCanonicalTypefaceForTesting(typeface.get()));
}

TEST_F(FontCollectionTests, WrappedManagerCachesCanonicalTypeface) {
  std::vector<sk_sp<SkTypeface>> typefaces = flutter::GetTestFontData();
  ASSERT_FALSE(typefaces.empty());

  auto font_provider = std::make_unique<TypefaceFontAssetProvider>();
  font_provider->RegisterTypeface(typefaces.front(), "FlutterTest");
  sk_sp<SkFontMgr> manager = MakeFreeTypeCanonicalFontManager(
      sk_make_sp<AssetFontManager>(std::move(font_provider)));

  sk_sp<SkTypeface> first =
      manager->matchFamily("FlutterTest")->matchStyle(SkFontStyle());
  sk_sp<SkTypeface> second =
      manager->matchFamily("FlutterTest")->matchStyle(SkFontStyle());

  ASSERT_NE(first, nullptr);
  ASSERT_NE(second, nullptr);
  EXPECT_EQ(first->uniqueID(), second->uniqueID());
}
}  // namespace testing
}  // namespace txt

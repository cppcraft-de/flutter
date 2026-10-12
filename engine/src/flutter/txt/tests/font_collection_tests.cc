// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "gtest/gtest.h"

#include <atomic>
#include <thread>

#include "flutter/fml/build_config.h"
#include "flutter/fml/synchronization/count_down_latch.h"
#include "flutter/runtime/test_font_data.h"
#include "third_party/skia/src/ports/SkTypeface_proxy.h"
#include "txt/asset_font_manager.h"
#include "txt/font_collection.h"
#include "txt/freetype_font_manager.h"
#include "txt/typeface_font_asset_provider.h"

#if defined(FML_OS_WIN)
#include "third_party/skia/include/ports/SkTypeface_win.h"
#elif defined(FML_OS_MACOSX)
#include "third_party/skia/include/ports/SkFontMgr_mac_ct.h"
#endif

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

TEST_F(FontCollectionTests, WrappedFreeTypeTypefaceRetainsIdentity) {
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
  EXPECT_EQ(typeface.get(), typefaces.front().get());
}

#if defined(FML_OS_WIN) || defined(FML_OS_MACOSX)
namespace {

sk_sp<SkTypeface> MakeNativeTestTypeface() {
#if defined(FML_OS_WIN)
  auto manager = SkFontMgr_New_DirectWrite();
#else
  auto manager = SkFontMgr_New_CoreText(nullptr);
#endif
  const auto fonts = flutter::GetTestFontData();
  if (!manager || fonts.empty()) {
    return nullptr;
  }
  int index = 0;
  auto stream = fonts.front()->openStream(&index);
  return manager->makeFromStream(std::move(stream), index);
}

sk_sp<SkFontMgr> WrapTypeface(sk_sp<SkTypeface> typeface) {
  auto provider = std::make_unique<TypefaceFontAssetProvider>();
  provider->RegisterTypeface(std::move(typeface), "FlutterTest");
  return MakeFreeTypeCanonicalFontManager(
      sk_make_sp<AssetFontManager>(std::move(provider)));
}

// Both threads must miss the cache before either conversion can complete.
class ConcurrentStreamTypeface final : public SkTypeface_proxy {
 public:
  explicit ConcurrentStreamTypeface(sk_sp<SkTypeface> typeface)
      : SkTypeface_proxy(typeface, typeface->fontStyle()), arrivals_(2) {}

  int stream_count() const { return stream_count_; }

 protected:
  std::unique_ptr<SkStreamAsset> onOpenStream(int* index) const override {
    if (stream_count_.fetch_add(1) < 2) {
      arrivals_.CountDown();
      arrivals_.Wait();
    }
    return SkTypeface_proxy::onOpenStream(index);
  }

 private:
  mutable std::atomic<int> stream_count_ = 0;
  mutable fml::CountDownLatch arrivals_;
};

}  // namespace

TEST_F(FontCollectionTests, WrappedStyleSetConvertsNativeTypefaceToFreeType) {
  auto native = MakeNativeTestTypeface();
  ASSERT_NE(native, nullptr);
  ASSERT_FALSE(IsFreeTypeCanonicalTypefaceForTesting(native.get()));
  auto manager = WrapTypeface(native);
  auto styles = manager->matchFamily("FlutterTest");
  ASSERT_NE(styles, nullptr);
  auto canonical = styles->createTypeface(0);
  ASSERT_NE(canonical, nullptr);
  EXPECT_TRUE(IsFreeTypeCanonicalTypefaceForTesting(canonical.get()));
  EXPECT_NE(canonical->uniqueID(), native->uniqueID());
  EXPECT_EQ(canonical->unicharToGlyph('A'), native->unicharToGlyph('A'));
  EXPECT_EQ(styles->matchStyle(SkFontStyle()).get(), canonical.get());
}

TEST_F(FontCollectionTests, WrappedManagerCachesCanonicalTypeface) {
  auto native = MakeNativeTestTypeface();
  ASSERT_NE(native, nullptr);
  ASSERT_FALSE(IsFreeTypeCanonicalTypefaceForTesting(native.get()));
  auto manager = WrapTypeface(native);

  sk_sp<SkTypeface> first =
      manager->matchFamily("FlutterTest")->matchStyle(SkFontStyle());
  sk_sp<SkTypeface> second =
      manager->matchFamily("FlutterTest")->matchStyle(SkFontStyle());

  ASSERT_NE(first, nullptr);
  ASSERT_NE(second, nullptr);
  EXPECT_TRUE(IsFreeTypeCanonicalTypefaceForTesting(first.get()));
  EXPECT_NE(first->uniqueID(), native->uniqueID());
  EXPECT_EQ(first->uniqueID(), second->uniqueID());
}

TEST_F(FontCollectionTests, ConcurrentConversionsReturnCachedTypeface) {
  auto native = MakeNativeTestTypeface();
  ASSERT_NE(native, nullptr);
  ASSERT_FALSE(IsFreeTypeCanonicalTypefaceForTesting(native.get()));
  auto source = sk_make_sp<ConcurrentStreamTypeface>(native);
  auto manager = WrapTypeface(source);
  sk_sp<SkTypeface> first;
  sk_sp<SkTypeface> second;
  auto lookup = [&manager](sk_sp<SkTypeface>& result) {
    result = manager->matchFamily("FlutterTest")->matchStyle(SkFontStyle());
  };
  std::thread a([&] { lookup(first); });
  std::thread b([&] { lookup(second); });
  a.join();
  b.join();
  ASSERT_NE(first, nullptr);
  ASSERT_NE(second, nullptr);
  EXPECT_EQ(source->stream_count(), 2);
  EXPECT_TRUE(IsFreeTypeCanonicalTypefaceForTesting(first.get()));
  EXPECT_EQ(first.get(), second.get());
  EXPECT_EQ(manager->matchFamilyStyle("FlutterTest", SkFontStyle()).get(),
            first.get());
}
#endif  // Native font backends (other platforms already use FreeType).
}  // namespace testing
}  // namespace txt

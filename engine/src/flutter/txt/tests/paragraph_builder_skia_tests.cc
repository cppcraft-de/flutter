// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "gtest/gtest.h"

#include <cstdlib>
#include <optional>
#include <sstream>

#include "skia/paragraph_builder_skia.h"
#include "txt/paragraph_style.h"

namespace txt {

class SkiaParagraphBuilderTests : public ::testing::Test {
 public:
  SkiaParagraphBuilderTests() {}

  void SetUp() override {}
};

namespace {

class ScopedEnvironmentVariable {
 public:
  ScopedEnvironmentVariable(const char* key, const char* value) : key_(key) {
    const char* original = std::getenv(key);
    if (original != nullptr) {
      original_ = original;
    }
    Set(value);
  }

  ~ScopedEnvironmentVariable() {
    Set(original_ ? original_->c_str() : nullptr);
  }

 private:
  void Set(const char* value) {
#ifdef _WIN32
    _putenv_s(key_.c_str(), value == nullptr ? "" : value);
#else
    if (value == nullptr) {
      unsetenv(key_.c_str());
    } else {
      setenv(key_.c_str(), value, 1);
    }
#endif
  }

  std::string key_;
  std::optional<std::string> original_;
};

}  // namespace

TEST_F(SkiaParagraphBuilderTests, ParagraphStrutStyle) {
  ParagraphStyle style = ParagraphStyle();
  auto collection = std::make_shared<FontCollection>();
  auto builder = ParagraphBuilderSkia(style, collection, false);

  auto strut_style = builder.TxtToSkia(style).getStrutStyle();
  ASSERT_FALSE(strut_style.getHalfLeading());

  style.strut_half_leading = true;
  strut_style = builder.TxtToSkia(style).getStrutStyle();
  ASSERT_TRUE(strut_style.getHalfLeading());
}

TEST_F(SkiaParagraphBuilderTests, SubpixelTracksEnvironment) {
  ScopedEnvironmentVariable environment("FLUTTER_INTEGER_TEXT_METRICS", "1");
  ParagraphStyle style;
  auto collection = std::make_shared<FontCollection>();
  auto builder = ParagraphBuilderSkia(style, collection, false);

  EXPECT_FALSE(builder.TxtToSkia(style).getTextStyle().getSubpixel());
  EXPECT_FALSE(builder.TxtToSkia(TextStyle()).getSubpixel());
}

TEST_F(SkiaParagraphBuilderTests, HintingTracksEnvironment) {
  ScopedEnvironmentVariable environment("FCTWEAK_HINTING", "full");
  ParagraphStyle style;
  auto collection = std::make_shared<FontCollection>();
  auto builder = ParagraphBuilderSkia(style, collection, false);

  EXPECT_TRUE(builder.TxtToSkia(style).hintingIsOn());
  EXPECT_EQ(builder.TxtToSkia(style).getTextStyle().getFontHinting(),
            SkFontHinting::kFull);
  EXPECT_EQ(builder.TxtToSkia(TextStyle()).getFontHinting(),
            SkFontHinting::kFull);
}
}  // namespace txt

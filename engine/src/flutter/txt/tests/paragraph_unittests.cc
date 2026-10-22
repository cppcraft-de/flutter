// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <algorithm>
#include <cmath>
#include <memory>
#include "display_list/dl_color.h"
#include "display_list/dl_paint.h"
#include "display_list/dl_tile_mode.h"
#include "display_list/effects/dl_color_source.h"
#include "display_list/utils/dl_receiver_utils.h"
#include "gtest/gtest.h"
#include "include/core/SkScalar.h"
#include "runtime/test_font_data.h"
#include "skia/paragraph_builder_skia.h"
#include "testing/canvas_test.h"
#include "testing/testing.h"
#include "third_party/skia/modules/skparagraph/src/Run.h"
#include "txt/platform.h"

namespace flutter {
namespace testing {

[[maybe_unused]]
static const std::string kEmojiFontFile =
#if FML_OS_MACOSX
    "Apple Color Emoji.ttc";
#else
    "NotoColorEmoji.ttf";
#endif

[[maybe_unused]]
static const std::string kEmojiFontName =
#if FML_OS_MACOSX
    "Apple Color Emoji";
#else
    "Noto Color Emoji";
#endif

//------------------------------------------------------------------------------
/// @brief      A custom |DlOpReceiver| that records some |DlOps| it receives.
class DlOpRecorder final : public virtual DlOpReceiver,
                           private IgnoreAttributeDispatchHelper,
                           private IgnoreClipDispatchHelper,
                           private IgnoreDrawDispatchHelper,
                           private IgnoreTransformDispatchHelper {
 public:
  int lineCount() const { return lines_.size(); }
  int dashedLineCount() const { return dashed_lines_.size(); }
  int rectCount() const { return rects_.size(); }
  int pathCount() const { return paths_.size(); }
  int textFrameCount() const { return text_frames_.size(); }
  int blobCount() const { return blobs_.size(); }

 private:
  void drawLine(const DlPoint& p0, const DlPoint& p1) override {
    lines_.emplace_back(p0, p1);
  }

  void drawDashedLine(const DlPoint& p0,
                      const DlPoint& p1,
                      DlScalar on_length,
                      DlScalar off_length) override {
    dashed_lines_.emplace_back(p0, p1, DlPoint(on_length, off_length));
  }

  void drawText(const std::shared_ptr<DlText>& text,
                SkScalar x,
                SkScalar y) override {
    auto blob = text->GetTextBlob();
    if (blob) {
      blobs_.push_back(sk_ref_sp(blob));
    } else {
      auto frame = text->GetTextFrame();
      FML_CHECK(frame);
      text_frames_.push_back(frame);
    }
  }

  void drawRect(const DlRect& rect) override { rects_.push_back(rect); }

  void drawPath(const DlPath& path) override { paths_.push_back(path); }

  std::vector<std::shared_ptr<impeller::TextFrame>> text_frames_;
  std::vector<sk_sp<SkTextBlob>> blobs_;
  std::vector<std::pair<DlPoint, DlPoint>> lines_;
  std::vector<std::tuple<DlPoint, DlPoint, DlPoint>> dashed_lines_;
  std::vector<DlRect> rects_;
  std::vector<DlPath> paths_;
};

template <typename T>
class PainterTestBase : public CanvasTestBase<T> {
 public:
  PainterTestBase() = default;

  void PretendImpellerIsEnabled(bool impeller) { impeller_ = impeller; }

 protected:
  txt::TextStyle makeDecoratedStyle(txt::TextDecorationStyle style) {
    auto t_style = txt::TextStyle();
    t_style.color = SK_ColorBLACK;  // default
    t_style.font_weight = txt::FontWeight::normal;
    t_style.font_size = 14;  // default
    t_style.decoration = txt::TextDecoration::kUnderline;
    t_style.decoration_style = style;
    t_style.decoration_color = SK_ColorBLACK;
    t_style.font_families.push_back("ahem");
    return t_style;
  }

  txt::TextStyle makeEmoji() {
    auto t_style = txt::TextStyle();
    t_style.color = SK_ColorBLACK;  // default
    t_style.font_weight = txt::FontWeight::normal;
    t_style.font_size = 14;  // default
    t_style.font_families.push_back(kEmojiFontName);
    return t_style;
  }

  txt::TextStyle makeStyle() {
    auto t_style = txt::TextStyle();
    t_style.color = SK_ColorBLACK;  // default
    t_style.font_weight = txt::FontWeight::normal;
    t_style.font_size = 14;  // default
    t_style.font_families.push_back("ahem");
    return t_style;
  }

  sk_sp<DisplayList> drawText(const txt::TextStyle& style,
                              const std::u16string& text) const {
    auto pb_skia = makeParagraphBuilder();
    pb_skia.PushStyle(style);
    pb_skia.AddText(text);
    pb_skia.Pop();

    auto builder = DisplayListBuilder();
    auto paragraph = pb_skia.Build();
    paragraph->Layout(10000);
    paragraph->Paint(&builder, 0, 0);

    return builder.Build();
  }

  sk_sp<DisplayList> draw(const txt::TextStyle& style) const {
    auto pb_skia = makeParagraphBuilder();
    pb_skia.PushStyle(style);
    pb_skia.AddText(u"Hello World!");
    pb_skia.Pop();

    auto builder = DisplayListBuilder();
    auto paragraph = pb_skia.Build();
    paragraph->Layout(10000);
    paragraph->Paint(&builder, 0, 0);

    return builder.Build();
  }

  std::unique_ptr<txt::Paragraph> layoutText(
      const txt::TextStyle& style,
      const std::u16string& text,
      const txt::ParagraphStyle& paragraph_style = {}) const {
    auto pb_skia = makeParagraphBuilder(paragraph_style);
    pb_skia.PushStyle(style);
    pb_skia.AddText(text);
    pb_skia.Pop();

    auto paragraph = pb_skia.Build();
    paragraph->Layout(10000);
    return paragraph;
  }

 private:
  std::shared_ptr<txt::FontCollection> makeFontCollection() const {
    auto f_collection = std::make_shared<txt::FontCollection>();
    auto font_provider = std::make_unique<txt::TypefaceFontAssetProvider>();
    for (auto& font : GetTestFontData()) {
      font_provider->RegisterTypeface(font);
    }
    // Load emoji font.
    {
      auto c_font_fixture = std::string(kEmojiFontFile);
      auto mapping =
          flutter::testing::OpenFixtureAsSkData(c_font_fixture.c_str());
      auto typeface = txt::GetDefaultFontManager()->makeFromData(mapping);
      font_provider->RegisterTypeface(typeface);
    }

    auto manager = sk_make_sp<txt::AssetFontManager>(std::move(font_provider));
    f_collection->SetAssetFontManager(manager);
    return f_collection;
  }

  txt::ParagraphBuilderSkia makeParagraphBuilder(
      const txt::ParagraphStyle& p_style = {}) const {
    auto f_collection = makeFontCollection();
    return txt::ParagraphBuilderSkia(p_style, f_collection, impeller_);
  }

  bool impeller_ = false;
};

using PainterTest = PainterTestBase<::testing::Test>;

TEST_F(PainterTest, ExplicitHeightControlsBaselinePitchIncludingEmptyText) {
  for (double height : {0.5, 1.0, 2.0}) {
    for (bool half_leading : {false, true}) {
      auto style = makeStyle();
      style.font_size = 20;
      style.height = height;
      style.has_height_override = true;
      style.half_leading = half_leading;
      const double expected = 20 * height;
      auto single = layoutText(style, u"a");
      auto empty = layoutText(style, u"");
      auto pair = layoutText(style, u"a\na");
      auto trailing = layoutText(style, u"a\n");
      EXPECT_DOUBLE_EQ(single->GetHeight(), expected);
      EXPECT_DOUBLE_EQ(empty->GetHeight(), expected);
      EXPECT_DOUBLE_EQ(empty->GetAlphabeticBaseline(),
                       single->GetAlphabeticBaseline());
      EXPECT_DOUBLE_EQ(pair->GetHeight(), 2 * expected);
      EXPECT_DOUBLE_EQ(trailing->GetHeight(), 2 * expected);
      const auto& lines = pair->GetLineMetrics();
      ASSERT_EQ(lines.size(), 2u);
      EXPECT_DOUBLE_EQ(lines[1].baseline - lines[0].baseline, expected);

      // Height controls must not change horizontal advances or wrapping.
      style.has_height_override = false;
      auto natural = layoutText(style, u"a");
      EXPECT_DOUBLE_EQ(single->GetLongestLine(), natural->GetLongestLine());
    }
  }
}

TEST_F(PainterTest, TextHeightBehaviorTrimsRequestedFirstAndLastExtents) {
  auto style = makeStyle();
  style.font_size = 20;
  style.height = 2;
  style.has_height_override = true;
  for (const auto& text : {u"a", u"a b", u"a\na", u"a\n", u""}) {
    auto expanded = layoutText(style, text);
    for (size_t behavior : {txt::kDisableFirstAscent, txt::kDisableLastDescent,
                            txt::kDisableAll}) {
      txt::ParagraphStyle paragraph_style;
      paragraph_style.text_height_behavior = behavior;
      auto trimmed = layoutText(style, text, paragraph_style);
      EXPECT_LT(trimmed->GetHeight(), expanded->GetHeight());
      EXPECT_DOUBLE_EQ(trimmed->GetLongestLine(), expanded->GetLongestLine());
      if (behavior & txt::kDisableFirstAscent) {
        EXPECT_LT(trimmed->GetAlphabeticBaseline(),
                  expanded->GetAlphabeticBaseline());
      } else {
        EXPECT_DOUBLE_EQ(trimmed->GetAlphabeticBaseline(),
                         expanded->GetAlphabeticBaseline());
      }
    }
  }
}

TEST_F(PainterTest, StrutHeightAndLeadingControlLayout) {
  auto style = makeStyle();
  style.font_size = 20;
  txt::ParagraphStyle paragraph_style;
  paragraph_style.strut_enabled = true;
  paragraph_style.strut_font_families = {"ahem"};
  paragraph_style.strut_font_size = 20;
  paragraph_style.strut_height = 2;
  paragraph_style.strut_has_height_override = true;
  paragraph_style.strut_leading = 0.2;
  for (bool force : {false, true}) {
    paragraph_style.force_strut_height = force;
    for (const auto& text : {u"a", u"a b", u""}) {
      auto paragraph = layoutText(style, text, paragraph_style);
      EXPECT_DOUBLE_EQ(paragraph->GetHeight(), 44);
    }
    auto pair = layoutText(style, u"a\na", paragraph_style);
    ASSERT_EQ(pair->GetLineMetrics().size(), 2u);
    EXPECT_DOUBLE_EQ(
        pair->GetLineMetrics()[1].baseline - pair->GetLineMetrics()[0].baseline,
        44);
  }
  style.font_size = 60;
  auto forced = layoutText(style, u"a", paragraph_style);
  EXPECT_DOUBLE_EQ(forced->GetHeight(), 44);
  paragraph_style.force_strut_height = false;
  auto minimum = layoutText(style, u"a", paragraph_style);
  EXPECT_GT(minimum->GetHeight(), 44);
}

TEST_F(PainterTest, LineMetricUpdatesPreserveRawFontMeasurements) {
  using skia::textlayout::InternalLineMetrics;
  InternalLineMetrics natural(-10, 3, -1);
  EXPECT_EQ(natural.height(), 12);
  EXPECT_EQ(natural.lineBoxHeight(), 13);
  EXPECT_EQ(natural.baseline(), 10);
  natural.update(-20, 6, 0);
  EXPECT_EQ(natural.height(), 26);
  EXPECT_EQ(natural.baseline(), 20);
  EXPECT_EQ(natural.rawAscent(), -10);
  EXPECT_EQ(natural.rawDescent(), 3);
  natural.useRawAscent();
  natural.useRawDescent();
  EXPECT_EQ(natural.height(), 13);
  EXPECT_EQ(natural.baseline(), 10);

  InternalLineMetrics strut(-30, 10, 4, -10, 3, -1);
  for (bool force : {false, true}) {
    InternalLineMetrics line(-10, 3, -1);
    line.setForceStrut(force);
    strut.updateLineMetrics(line);
    EXPECT_EQ(line.height(), 44);
    EXPECT_EQ(line.lineBoxHeight(), 44);
    EXPECT_EQ(line.baseline(), 32);
  }
}

TEST_F(PainterTest, DrawsSolidLineSkia) {
  PretendImpellerIsEnabled(false);

  auto recorder = DlOpRecorder();
  draw(makeDecoratedStyle(txt::TextDecorationStyle::kSolid))
      ->Dispatch(recorder);

  // Skia may draw a solid underline as a filled rectangle:
  // https://skia.googlesource.com/skia/+/refs/heads/main/modules/skparagraph/src/Decorations.cpp#91
  EXPECT_EQ(recorder.rectCount(), 1);
}

TEST_F(PainterTest, DrawDashedLineSkia) {
  PretendImpellerIsEnabled(false);

  auto recorder = DlOpRecorder();
  draw(makeDecoratedStyle(txt::TextDecorationStyle::kDashed))
      ->Dispatch(recorder);

  // Skia draws a dashed underline as a filled rectangle with a path effect.
  EXPECT_EQ(recorder.lineCount(), 0);
  EXPECT_EQ(recorder.dashedLineCount(), 1);
}

#ifdef IMPELLER_SUPPORTS_RENDERING
TEST_F(PainterTest, DrawsSolidLineImpeller) {
  PretendImpellerIsEnabled(true);

  auto recorder = DlOpRecorder();
  draw(makeDecoratedStyle(txt::TextDecorationStyle::kSolid))
      ->Dispatch(recorder);

  // Skia may draw a solid underline as a filled rectangle:
  // https://skia.googlesource.com/skia/+/refs/heads/main/modules/skparagraph/src/Decorations.cpp#91
  EXPECT_EQ(recorder.rectCount(), 1);
}

TEST_F(PainterTest, DrawDashedLineImpeller) {
  PretendImpellerIsEnabled(true);

  auto recorder = DlOpRecorder();
  draw(makeDecoratedStyle(txt::TextDecorationStyle::kDashed))
      ->Dispatch(recorder);

  // Impeller draws a dashed underline as a path.
  EXPECT_EQ(recorder.pathCount(), 0);
  EXPECT_EQ(recorder.dashedLineCount(), 1);
}

TEST_F(PainterTest, DrawTextImpeller) {
  PretendImpellerIsEnabled(true);

  auto recorder = DlOpRecorder();
  draw(makeStyle())->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 1);
  EXPECT_EQ(recorder.blobCount(), 0);
}

TEST_F(PainterTest, DrawStrokedTextImpeller) {
  PretendImpellerIsEnabled(true);

  auto style = makeStyle();
  // What is your shtyle?
  DlPaint foreground;
  foreground.setDrawStyle(DlDrawStyle::kStroke);
  style.foreground = foreground;

  auto recorder = DlOpRecorder();
  draw(style)->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 1);
  EXPECT_EQ(recorder.blobCount(), 0);
  EXPECT_EQ(recorder.pathCount(), 0);
}

TEST_F(PainterTest, DrawStrokedTextWithLargeWidthImpeller) {
  PretendImpellerIsEnabled(true);

  auto style = makeStyle();
  DlPaint foreground;
  foreground.setDrawStyle(DlDrawStyle::kStroke);
  foreground.setStrokeWidth(10);
  style.foreground = foreground;

  auto recorder = DlOpRecorder();
  draw(style)->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 0);
  EXPECT_EQ(recorder.blobCount(), 0);
  EXPECT_EQ(recorder.pathCount(), 1);
}

TEST_F(PainterTest, DrawTextWithGradientImpeller) {
  PretendImpellerIsEnabled(true);

  auto style = makeStyle();
  // how do you like my shtyle?
  DlPaint foreground;
  std::vector<DlColor> colors = {DlColor::kRed(), DlColor::kCyan()};
  std::vector<float> stops = {0.0, 1.0};
  foreground.setColorSource(DlColorSource::MakeLinear(
      DlPoint(0, 0), DlPoint(100, 100), 2, colors.data(), stops.data(),
      DlTileMode::kClamp));
  style.foreground = foreground;

  auto recorder = DlOpRecorder();
  draw(style)->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 0);
  EXPECT_EQ(recorder.blobCount(), 0);
  EXPECT_EQ(recorder.pathCount(), 1);
}

TEST_F(PainterTest, DrawEmojiTextWithGradientImpeller) {
  PretendImpellerIsEnabled(true);

  auto style = makeEmoji();
  // how do you like my shtyle?
  DlPaint foreground;
  std::vector<DlColor> colors = {DlColor::kRed(), DlColor::kCyan()};
  std::vector<float> stops = {0.0, 1.0};
  foreground.setColorSource(DlColorSource::MakeLinear(
      DlPoint(0, 0), DlPoint(100, 100), 2, colors.data(), stops.data(),
      DlTileMode::kClamp));
  style.foreground = foreground;

  auto recorder = DlOpRecorder();
  drawText(style, u"😀 😃 😄 😁 😆 😅 😂 🤣 🥲 😊")->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 1);
  EXPECT_EQ(recorder.blobCount(), 0);
  EXPECT_EQ(recorder.pathCount(), 0);
}

TEST_F(PainterTest, DrawTextBlobNoImpeller) {
  PretendImpellerIsEnabled(false);

  auto recorder = DlOpRecorder();
  draw(makeStyle())->Dispatch(recorder);

  EXPECT_EQ(recorder.textFrameCount(), 0);
  EXPECT_EQ(recorder.blobCount(), 1);
}
#endif  // IMPELLER_SUPPORTS_RENDERING

}  // namespace testing
}  // namespace flutter

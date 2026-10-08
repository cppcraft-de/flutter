// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include "display_list/dl_color.h"
#include "display_list/dl_paint.h"
#include "display_list/dl_tile_mode.h"
#include "display_list/effects/dl_color_source.h"
#include "display_list/utils/dl_receiver_utils.h"
#include "flutter/display_list/skia/dl_sk_dispatcher.h"
#include "gtest/gtest.h"
#include "include/core/SkBitmap.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkScalar.h"
#include "runtime/test_font_data.h"
#include "skia/paragraph_builder_skia.h"
#include "testing/canvas_test.h"
#include "testing/testing.h"
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

  std::unique_ptr<txt::Paragraph> layoutText(const txt::TextStyle& style,
                                             const std::u16string& text) const {
    auto pb_skia = makeParagraphBuilder();
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

  txt::ParagraphBuilderSkia makeParagraphBuilder() const {
    auto p_style = txt::ParagraphStyle();
    auto f_collection = makeFontCollection();
    return txt::ParagraphBuilderSkia(p_style, f_collection, impeller_);
  }

  bool impeller_ = false;
};

using PainterTest = PainterTestBase<::testing::Test>;

TEST_F(PainterTest, DetailedLineMetricsComeFromFinalLayout) {
  auto paragraph = layoutText(makeStyle(), u"HHHH");
  const auto& metrics = paragraph->GetLineMetrics();
  const auto glyphs = paragraph->GetGlyphDiagnostics();

  ASSERT_EQ(metrics.size(), 1u);
  const txt::LineMetrics& line = metrics.front();
  EXPECT_GT(line.raw_ascent, 0);
  EXPECT_GE(line.raw_descent, 0);
  EXPECT_GT(line.effective_ascent, 0);
  EXPECT_GE(line.effective_descent, 0);
  EXPECT_LT(line.height_input_ascent, 0);
  EXPECT_GE(line.height_input_descent, 0);
  const double expected_leading = std::max(0.0, line.raw_leading);
  EXPECT_DOUBLE_EQ(line.line_height_branch, 2);
  EXPECT_DOUBLE_EQ(
      line.next_line_baseline_pitch,
      std::ceil(line.raw_ascent + line.raw_descent + line.raw_leading));
  EXPECT_DOUBLE_EQ(
      line.line_box_height,
      std::ceil(line.raw_ascent + line.raw_descent + expected_leading));
  EXPECT_DOUBLE_EQ(line.height, line.next_line_baseline_pitch);
  if (!skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_TRUE(glyphs.empty());
    return;
  }
  ASSERT_EQ(glyphs.size(), 4u);
  EXPECT_EQ(glyphs.front().fLineNumber, 0);
  EXPECT_LT(glyphs.front().fFontMetrics.fAscent, 0);
  EXPECT_GE(glyphs.front().fFontMetrics.fDescent, 0);
  EXPECT_GT(glyphs.front().fGlyph, 0);
  EXPECT_GT(glyphs.front().fAdvance.fX, 0);
  EXPECT_EQ(glyphs.front().fInkBounds,
            glyphs.front().fBounds.makeOffset(glyphs.front().fFinalOrigin));
}

TEST_F(PainterTest, SchoolcraftIntegerLineMetricsUseSignedPitchAndOccupiedBox) {
  auto style = makeStyle();
  style.font_size = 19;
  auto paragraph = layoutText(style, u"HHHH");
  const auto& metrics = paragraph->GetLineMetrics();
  const auto glyphs = paragraph->GetGlyphDiagnostics();

  ASSERT_EQ(metrics.size(), 1u);
  if (!skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_TRUE(glyphs.empty());
    return;
  }
  ASSERT_EQ(glyphs.size(), 4u);
  const txt::LineMetrics& line = metrics.front();
  const double expected_ascent = std::ceil(line.raw_ascent);
  const double expected_descent = std::ceil(line.raw_descent);
  const double expected_leading = std::max(0.0, line.raw_leading);
  const double expected_baseline_pitch =
      std::ceil(line.raw_ascent + line.raw_descent + line.raw_leading);
  const double expected_occupied_height =
      std::ceil(line.raw_ascent + line.raw_descent + expected_leading);

  EXPECT_DOUBLE_EQ(line.effective_ascent, expected_ascent);
  EXPECT_DOUBLE_EQ(line.effective_descent, expected_descent);
  EXPECT_DOUBLE_EQ(line.effective_leading, expected_leading);
  EXPECT_DOUBLE_EQ(line.line_height_branch, 2);
  EXPECT_DOUBLE_EQ(line.baseline, expected_ascent);
  EXPECT_DOUBLE_EQ(line.next_line_baseline_pitch, expected_baseline_pitch);
  EXPECT_DOUBLE_EQ(line.line_box_height, expected_occupied_height);
  EXPECT_DOUBLE_EQ(line.height, expected_baseline_pitch);
  EXPECT_DOUBLE_EQ(glyphs.front().fFinalOrigin.fY, line.baseline);
}

// Run in separate processes with WSC_FONT_DIAGNOSTICS=0 and =1. The output
// includes ordinary layout geometry and raster pixels, never diagnostic data.
// This also permits comparison against the pre-removal engine's libraries.
TEST_F(PainterTest, FontDiagnosticsRenderingParity) {
  uint64_t fingerprint = 14695981039346656037ull;
  uint64_t diagnostic_fingerprint = 14695981039346656037ull;
  auto hash = [&fingerprint](const void* data, size_t size) {
    const auto* bytes = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < size; ++i) {
      fingerprint = (fingerprint ^ bytes[i]) * 1099511628211ull;
    }
  };
  for (const auto& family : {"ahem", "FlutterTest", "Cough"}) {
    for (double font_size : {14.0, 19.25, 27.5}) {
      for (double height : {0.0, 0.8, 1.3}) {
        for (const auto& text : {u"", u"AV ffi text\nsecond line",
                                 u"spaces wrap across multiple lines"}) {
          auto style = makeStyle();
          style.font_families = {family};
          style.font_size = font_size;
          style.height = height;
          style.has_height_override = height != 0.0;
          auto paragraph = layoutText(style, text);
          paragraph->Layout(120);
          const auto& lines = paragraph->GetLineMetrics();
          std::ostringstream geometry;
          geometry << std::setprecision(17) << paragraph->GetHeight() << ','
                   << paragraph->GetLongestLine() << ','
                   << paragraph->GetAlphabeticBaseline();
          for (const auto& line : lines) {
            geometry << ';' << line.start_index << ',' << line.end_index << ','
                     << line.left << ',' << line.width << ',' << line.height
                     << ',' << line.baseline;
          }
          const double correction =
              lines.empty()
                  ? 0.0
                  : std::max(0.0, lines.back().line_box_height -
                                      lines.back().next_line_baseline_pitch);
          geometry << ':' << correction;
#ifndef WSC_PARITY_BASELINE
          EXPECT_DOUBLE_EQ(paragraph->GetParagraphBottomCorrection(),
                           correction);
          EXPECT_TRUE(skia::textlayout::ConfigureFontDiagnostics(
              skia::textlayout::FontDiagnosticsEnabled()));
          EXPECT_FALSE(skia::textlayout::ConfigureFontDiagnostics(
              !skia::textlayout::FontDiagnosticsEnabled()));
          const auto glyphs = paragraph->GetGlyphDiagnostics();
          if (!skia::textlayout::FontDiagnosticsEnabled()) {
            EXPECT_TRUE(glyphs.empty());
          }
#endif
          const auto value = geometry.str();
          hash(value.data(), value.size());
          SkBitmap bitmap;
          ASSERT_TRUE(bitmap.tryAllocN32Pixels(200, 400));
          bitmap.eraseColor(SK_ColorWHITE);
          SkCanvas canvas(bitmap);
          DisplayListBuilder builder;
          paragraph->Paint(&builder, 0, 0);
          DlSkCanvasDispatcher dispatcher(&canvas);
          builder.Build()->Dispatch(dispatcher);
          hash(bitmap.getPixels(), bitmap.computeByteSize());
          std::ostringstream diagnostics;
          const auto painted_glyphs = paragraph->GetGlyphDiagnostics();
          diagnostics << std::setprecision(17) << painted_glyphs.size();
          for (const auto& glyph : painted_glyphs) {
            diagnostics << ';' << glyph.fGlyph << ',' << glyph.fUtf8Cluster
                        << ',' << glyph.fRawShapePosition.fX << ','
                        << glyph.fRawShapePosition.fY << ','
                        << glyph.fRawAdvance.fX << ',' << glyph.fRawAdvance.fY
                        << ',' << glyph.fFinalOrigin.fX << ','
                        << glyph.fFinalOrigin.fY << ',' << glyph.fScript << ','
                        << glyph.fLanguage.c_str() << ','
                        << glyph.fShapingFeatureCount << ','
                        << glyph.fShapingFeatureMask;
          }
          for (unsigned char value : diagnostics.str()) {
            diagnostic_fingerprint =
                (diagnostic_fingerprint ^ value) * 1099511628211ull;
          }
          // A repeated layout exercises shaping-cache reuse in each mode.
          paragraph->Layout(120);
          EXPECT_DOUBLE_EQ(paragraph->GetHeight(), std::stod(value));
        }
      }
    }
  }
  std::cout << "FONT_RENDERING_PARITY " << fingerprint << std::endl;
  std::cout << "FONT_DIAGNOSTICS_PARITY " << diagnostic_fingerprint
            << std::endl;
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

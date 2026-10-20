// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include "display_list/dl_color.h"
#include "display_list/dl_paint.h"
#include "display_list/dl_tile_mode.h"
#include "display_list/effects/dl_color_source.h"
#include "display_list/utils/dl_receiver_utils.h"
#include "flutter/display_list/skia/dl_sk_dispatcher.h"
#include "flutter/fml/icu_util.h"
#include "gtest/gtest.h"
#include "include/core/SkBitmap.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkScalar.h"
#include "runtime/test_font_data.h"
#include "skia/paragraph_builder_skia.h"
#include "testing/canvas_test.h"
#include "testing/testing.h"
#include "third_party/skia/modules/skunicode/include/SkUnicode_icu.h"
#include "txt/platform.h"

namespace flutter {
namespace testing {

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

  std::unique_ptr<skia::textlayout::Paragraph> makeJustifiedSkiaParagraph()
      const {
    skia::textlayout::ParagraphStyle style;
    style.setTextAlign(skia::textlayout::TextAlign::kJustify);
    skia::textlayout::TextStyle text_style;
    text_style.setFontFamilies({SkString("ahem")});
    text_style.setFontSize(14);
    style.setTextStyle(text_style);
    auto builder = skia::textlayout::ParagraphBuilder::make(
        style, makeFontCollection()->CreateSktFontCollection(),
        SkUnicodes::ICU::Make());
    builder->addText("aa bb cc dd ee ff");
    return builder->Build();
  }

 private:
  std::shared_ptr<txt::FontCollection> makeFontCollection() const {
    fml::icu::InitializeICU("icudtl.dat");
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

TEST_F(PainterTest, IndexedLineLayoutPreservesConsumedUtf16Ranges) {
  fml::icu::InitializeICU("icudtl.dat");
  for (const std::u16string text : {u"", u"a\n", u"a\r\n", u"a\u2028", u"a\n\n",
                                    u"\n", u"aa  bb cc  \n\U0001F600 dd\n"}) {
    auto paragraph = layoutText(makeStyle(), text);
    paragraph->Layout(70);
    const auto& lines = paragraph->GetLineMetrics();
    if (text.empty()) {
      EXPECT_TRUE(lines.empty());
      continue;
    }
    ASSERT_GT(lines.size(), 1u);
    size_t consumed = 0;
    for (size_t i = 0; i < lines.size(); ++i) {
      const auto& line = lines[i];
      EXPECT_EQ(line.line_number, i);
      // This marker comes from the actual appended line, not a guessed range.
      const size_t start = line.is_trailing_empty_line
                               ? line.end_including_newline
                               : line.start_index;
      EXPECT_EQ(start, consumed);
      EXPECT_LE(line.start_index, line.end_excluding_whitespace);
      EXPECT_LE(line.end_excluding_whitespace, line.end_index);
      EXPECT_LE(line.end_index, line.end_including_newline);
      consumed = line.end_including_newline;
      EXPECT_EQ(line.is_trailing_empty_line, i + 1 == lines.size());
    }
    EXPECT_EQ(consumed, text.size());
    EXPECT_TRUE(lines.back().is_trailing_empty_line);
    EXPECT_EQ(lines.back().end_including_newline, text.size());
    EXPECT_FALSE(paragraph->DidExceedMaxLines());
  }
}

TEST_F(PainterTest, LineLayoutDiagnosticsPreserveJustifiedPainting) {
  fml::icu::InitializeICU("icudtl.dat");
  txt::ParagraphStyle paragraph_style;
  paragraph_style.text_align = txt::TextAlign::justify;
  auto paragraph =
      layoutText(makeStyle(), u"aa bb cc dd ee ff", paragraph_style);
  paragraph->Layout(100);
  DisplayListBuilder before;
  paragraph->Paint(&before, 0, 0);
  const auto picture_before = before.Build();
  const auto& lines = paragraph->GetLineMetrics();
  ASSERT_GT(lines.size(), 1u);
  if (skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_DOUBLE_EQ(lines.front().available_width, 100);
    EXPECT_LT(lines.front().advance_before_justification, 100);
    EXPECT_DOUBLE_EQ(lines.front().advance_after_justification, 100);
    EXPECT_DOUBLE_EQ(lines.back().advance_before_justification,
                     lines.back().advance_after_justification);
    EXPECT_FALSE(lines.front().is_ellipsized);
  }
  DisplayListBuilder after;
  paragraph->Paint(&after, 0, 0);
  EXPECT_TRUE(picture_before->Equals(after.Build()));
  // A second layout must capture the new pre-justification width, not stale
  // data.
  paragraph->Layout(10000);
  const auto& relaid_out = paragraph->GetLineMetrics();
  ASSERT_EQ(relaid_out.size(), 1u);
  if (skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_DOUBLE_EQ(relaid_out.front().available_width, 10000);
    EXPECT_DOUBLE_EQ(relaid_out.front().advance_before_justification,
                     relaid_out.front().advance_after_justification);
  }
}

TEST_F(PainterTest, LineLayoutDiagnosticsKeepPreJustificationAfterReformat) {
  fml::icu::InitializeICU("icudtl.dat");
  auto paragraph = makeJustifiedSkiaParagraph();
  paragraph->layout(100);
  std::vector<skia::textlayout::LineMetrics> first;
  paragraph->getLineMetrics(first);
  ASSERT_GT(first.size(), 1u);
  paragraph->updateTextAlign(skia::textlayout::TextAlign::kJustify);
  paragraph->layout(100);
  std::vector<skia::textlayout::LineMetrics> reformatted;
  paragraph->getLineMetrics(reformatted);
  ASSERT_EQ(first.size(), reformatted.size());
  if (skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_LT(first.front().fAdvanceBeforeJustification, 100);
    EXPECT_DOUBLE_EQ(first.front().fAdvanceBeforeJustification,
                     reformatted.front().fAdvanceBeforeJustification);
    EXPECT_DOUBLE_EQ(reformatted.front().fAdvanceAfterJustification, 100);
  }
}

TEST_F(PainterTest, LineLayoutDiagnosticsIdentifyTruncation) {
  fml::icu::InitializeICU("icudtl.dat");
  txt::ParagraphStyle paragraph_style;
  paragraph_style.max_lines = 1;
  paragraph_style.ellipsis = u"...";
  auto paragraph =
      layoutText(makeStyle(), u"aa bb cc dd ee ff", paragraph_style);
  paragraph->Layout(100);
  EXPECT_TRUE(paragraph->DidExceedMaxLines());
  const auto& lines = paragraph->GetLineMetrics();
  ASSERT_EQ(lines.size(), 1u);
  if (skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_TRUE(lines.front().is_ellipsized);
    EXPECT_DOUBLE_EQ(lines.front().advance_before_justification,
                     lines.front().advance_after_justification);
  }
}

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

TEST_F(PainterTest, QtLikeIntegerLineMetricsUseSignedPitchAndOccupiedBox) {
  ScopedEnvironmentVariable environment("FLUTTER_QT_LINE_METRICS", "true");
  ScopedEnvironmentVariable alternative_line_height(
      "FLUTTER_USE_ALTERNATIVE_LINE_HEIGHT", nullptr);
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

TEST_F(PainterTest, AlternativeLineHeightEnvKeepsSignedPitch) {
  ScopedEnvironmentVariable environment("FLUTTER_QT_LINE_METRICS", "true");
  ScopedEnvironmentVariable alternative_line_height(
      "FLUTTER_USE_ALTERNATIVE_LINE_HEIGHT", "true");
  auto style = makeStyle();
  style.font_size = 19;
  auto paragraph = layoutText(style, u"HHHH");
  const auto& metrics = paragraph->GetLineMetrics();

  ASSERT_EQ(metrics.size(), 1u);
  const txt::LineMetrics& line = metrics.front();
  const double expected_baseline_pitch =
      std::ceil(line.raw_ascent + line.raw_descent + line.raw_leading);

  EXPECT_DOUBLE_EQ(line.line_height_branch, 2);
  EXPECT_DOUBLE_EQ(line.next_line_baseline_pitch, expected_baseline_pitch);
  EXPECT_DOUBLE_EQ(line.height, expected_baseline_pitch);
  EXPECT_DOUBLE_EQ(line.line_box_height,
                   std::ceil(line.raw_ascent + line.raw_descent +
                             std::max(0.0, line.raw_leading)));
}

TEST_F(PainterTest, QtLikeIntegerLineMetricsCanOptOutToVanilla) {
  ScopedEnvironmentVariable environment("FLUTTER_QT_LINE_METRICS", "false");
  auto style = makeStyle();
  style.font_size = 19;
  auto paragraph = layoutText(style, u"HHHH");
  const auto& metrics = paragraph->GetLineMetrics();

  ASSERT_EQ(metrics.size(), 1u);
  const txt::LineMetrics& line = metrics.front();
  EXPECT_DOUBLE_EQ(line.line_height_branch, 0);
}

TEST_F(PainterTest, CursiveLetterSpacingDoesNotChangeWrapping) {
  fml::icu::InitializeICU("icudtl.dat");
  auto style = makeStyle();
  const std::u16string text = u"\u0633\u0644\u0627\u0645";
  auto natural = layoutText(style, text);
  const double width = natural->GetLongestLine();
  ASSERT_GT(width, 0);
  style.letter_spacing = 3;
  auto spaced = layoutText(style, text);
  EXPECT_DOUBLE_EQ(spaced->GetLongestLine(), width);
  natural->Layout(width);
  spaced->Layout(width);
  EXPECT_EQ(spaced->GetLineMetrics().size(), natural->GetLineMetrics().size());

  // The same spacing must still apply to non-cursive scripts.
  auto latin_spaced = layoutText(style, u"abcd");
  style.letter_spacing = 0;
  auto latin_natural = layoutText(style, u"abcd");
  EXPECT_GT(latin_spaced->GetLongestLine(), latin_natural->GetLongestLine());
}

TEST_F(PainterTest, RawDiagnosticsPrecedeSpacingWithIntegerMetricsDisabled) {
  ScopedEnvironmentVariable environment("FLUTTER_QT_LINE_METRICS", "false");
  auto style = makeStyle();
  style.letter_spacing = 3;
  auto paragraph = layoutText(style, u"abcd");
  const auto glyphs = paragraph->GetGlyphDiagnostics();
  if (!skia::textlayout::FontDiagnosticsEnabled()) {
    EXPECT_TRUE(glyphs.empty());
    return;
  }
  ASSERT_EQ(glyphs.size(), 4u);
  double raw_width = 0;
  double final_width = 0;
  for (const auto& glyph : glyphs) {
    raw_width += glyph.fRawAdvance.fX;
    final_width += glyph.fAdvance.fX;
  }
  EXPECT_GT(final_width, raw_width);
}

// Run in separate processes with WSC_FONT_DIAGNOSTICS=0 and =1. The output
// includes occupied paragraph height, line geometry, and raster pixels.
// Compare this branch with mimic_freetype using the same test harness.
TEST_F(PainterTest, FontDiagnosticsRenderingParity) {
  fml::icu::InitializeICU("icudtl.dat");
  uint64_t fingerprint = 14695981039346656037ull;
  uint64_t diagnostic_fingerprint = 14695981039346656037ull;
  int corrected_paragraphs = 0;
  auto hash = [&fingerprint](const void* data, size_t size) {
    const auto* bytes = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < size; ++i) {
      fingerprint = (fingerprint ^ bytes[i]) * 1099511628211ull;
    }
  };
  for (const auto& typeface : GetTestFontData()) {
    ASSERT_NE(typeface, nullptr);
    SkString family;
    typeface->getFamilyName(&family);
    for (double font_size : {14.0, 19.25, 27.5}) {
      for (double height : {0.0, 0.8, 1.3}) {
        SCOPED_TRACE(::testing::Message() << family.c_str() << " size="
                                          << font_size << " height=" << height);
        auto blank_style = makeStyle();
        blank_style.font_families = {family.c_str()};
        blank_style.font_size = font_size;
        blank_style.height = height;
        blank_style.has_height_override = height != 0.0;
        auto letter = layoutText(blank_style, u"a");
        auto pair = layoutText(blank_style, u"a\na");
        const auto& single_line = letter->GetLineMetrics();
        const auto& paired_lines = pair->GetLineMetrics();
        ASSERT_EQ(single_line.size(), 1u);
        ASSERT_EQ(paired_lines.size(), 2u);
        const double baseline_pitch =
            paired_lines[1].baseline - paired_lines[0].baseline;
        EXPECT_DOUBLE_EQ(baseline_pitch, single_line.front().height);
        const double blank_height = letter->GetHeight();
        std::ostringstream blank_geometry;
        blank_geometry << std::setprecision(17) << blank_height;
        const auto blank_value = blank_geometry.str();
        hash(blank_value.data(), blank_value.size());
        for (const auto& text : {u"", u"AV ffi text\nsecond line",
                                 u"spaces wrap across multiple lines"}) {
          auto style = makeStyle();
          style.font_families = {family.c_str()};
          style.font_size = font_size;
          style.height = height;
          style.has_height_override = height != 0.0;
          auto paragraph = layoutText(style, text);
          paragraph->Layout(120);
          const auto& lines = paragraph->GetLineMetrics();
          if (std::u16string(text).find(u'\n') != std::u16string::npos) {
            ASSERT_GE(lines.size(), 2u);
          } else if (!std::u16string(text).empty()) {
            ASSERT_FALSE(lines.empty());
          }
          const double correction =
              lines.empty()
                  ? 0.0
                  : std::max(0.0, lines.back().line_box_height -
                                      lines.back().next_line_baseline_pitch);
          const double reported_height = paragraph->GetHeight();
          const double occupied_height = reported_height;
          if (correction > 0.0) {
            ++corrected_paragraphs;
          }
          std::ostringstream geometry;
          geometry << std::setprecision(17) << occupied_height << ','
                   << paragraph->GetLongestLine() << ','
                   << paragraph->GetAlphabeticBaseline();
          for (const auto& line : lines) {
            geometry << ';' << line.start_index << ',' << line.end_index << ','
                     << line.left << ',' << line.width << ',' << line.height
                     << ',' << line.baseline;
          }
          geometry << ':' << correction;
#ifndef WSC_PARITY_BASELINE
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
          EXPECT_DOUBLE_EQ(paragraph->GetHeight(), reported_height);
        }
      }
    }
  }

  std::cout << "CORRECTED_PARAGRAPHS " << corrected_paragraphs << std::endl;
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

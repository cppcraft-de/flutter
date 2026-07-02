// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "txt/freetype_font_manager.h"

#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "flutter/fml/logging.h"
#include "third_party/skia/include/core/SkData.h"
#include "third_party/skia/include/core/SkFontArguments.h"
#include "third_party/skia/include/core/SkStream.h"
#include "third_party/skia/include/core/SkString.h"
#include "third_party/skia/src/core/SkFontDescriptor.h"
#include "third_party/skia/src/ports/SkTypeface_FreeType.h"

namespace txt {
namespace {

bool IsFreeTypeCanonicalTypeface(const SkTypeface* typeface) {
  if (typeface == nullptr) {
    return false;
  }

  SkFontDescriptor descriptor;
  bool is_local = false;
  typeface->getFontDescriptor(&descriptor, &is_local);
  return descriptor.getFactoryId() == SkTypeface_FreeType::FactoryId;
}

std::vector<SkFontArguments::VariationPosition::Coordinate>
GetVariationCoordinates(const SkTypeface& typeface) {
  int coordinate_count = typeface.getVariationDesignPosition({});
  if (coordinate_count <= 0) {
    return {};
  }

  std::vector<SkFontArguments::VariationPosition::Coordinate> coordinates(
      coordinate_count);
  coordinate_count = typeface.getVariationDesignPosition(
      {coordinates.data(), coordinates.size()});
  if (coordinate_count <= 0) {
    return {};
  }
  coordinates.resize(coordinate_count);
  return coordinates;
}

sk_sp<SkTypeface> MakeFreeTypeTypefaceFromStream(
    std::unique_ptr<SkStreamAsset> stream,
    const SkFontArguments& arguments) {
  if (stream == nullptr) {
    return nullptr;
  }
  return SkTypeface_FreeType::MakeFromStream(std::move(stream), arguments);
}

sk_sp<SkTypeface> MakeFreeTypeTypefaceFromData(sk_sp<SkData> data,
                                               int ttc_index) {
  if (data == nullptr) {
    return nullptr;
  }
  SkFontArguments arguments;
  arguments.setCollectionIndex(ttc_index);
  return MakeFreeTypeTypefaceFromStream(SkMemoryStream::Make(std::move(data)),
                                        arguments);
}

sk_sp<SkTypeface> MakeFreeTypeTypefaceFromFile(const char path[],
                                               int ttc_index) {
  if (path == nullptr) {
    return nullptr;
  }
  SkFontArguments arguments;
  arguments.setCollectionIndex(ttc_index);
  return MakeFreeTypeTypefaceFromStream(SkStream::MakeFromFile(path),
                                        arguments);
}

sk_sp<SkTypeface> MakeFreeTypeTypefaceFromTypeface(
    const sk_sp<SkTypeface>& typeface) {
  if (typeface == nullptr || IsFreeTypeCanonicalTypeface(typeface.get())) {
    return typeface;
  }

  int ttc_index = 0;
  std::unique_ptr<SkStreamAsset> stream = typeface->openStream(&ttc_index);
  if (stream == nullptr) {
    FML_DCHECK(false) << "Unable to open selected font data for FreeType "
                         "canonicalization.";
    FML_LOG(ERROR) << "Unable to open selected font data for FreeType "
                      "canonicalization.";
    return typeface;
  }

  SkFontDescriptor descriptor;
  bool is_local = false;
  typeface->getFontDescriptor(&descriptor, &is_local);
  SkFontArguments arguments = descriptor.getFontArguments();
  arguments.setCollectionIndex(ttc_index);

  std::vector<SkFontArguments::VariationPosition::Coordinate> coordinates =
      GetVariationCoordinates(*typeface);
  if (!coordinates.empty()) {
    arguments.setVariationDesignPosition(
        {coordinates.data(), static_cast<int>(coordinates.size())});
  }

  sk_sp<SkTypeface> canonical =
      MakeFreeTypeTypefaceFromStream(std::move(stream), arguments);
  if (canonical == nullptr) {
    FML_DCHECK(false) << "Unable to construct FreeType typeface from selected "
                         "font data.";
    FML_LOG(ERROR) << "Unable to construct FreeType typeface from selected "
                      "font data.";
    return typeface;
  }
  return canonical;
}

class FreeTypeCanonicalizer : public SkNVRefCnt<FreeTypeCanonicalizer> {
 public:
  sk_sp<SkTypeface> Canonicalize(sk_sp<SkTypeface> typeface) {
    if (typeface == nullptr || IsFreeTypeCanonicalTypeface(typeface.get())) {
      return typeface;
    }

    const SkTypefaceID source_id = typeface->uniqueID();
    {
      std::scoped_lock lock(mutex_);
      auto found = cache_.find(source_id);
      if (found != cache_.end()) {
        return found->second;
      }
    }

    sk_sp<SkTypeface> canonical =
        MakeFreeTypeTypefaceFromTypeface(std::move(typeface));
    {
      std::scoped_lock lock(mutex_);
      cache_[source_id] = canonical;
    }
    return canonical;
  }

 private:
  std::mutex mutex_;
  std::unordered_map<SkTypefaceID, sk_sp<SkTypeface>> cache_;
};

class FreeTypeCanonicalFontStyleSet final : public SkFontStyleSet {
 public:
  FreeTypeCanonicalFontStyleSet(sk_sp<SkFontStyleSet> delegate,
                                sk_sp<FreeTypeCanonicalizer> canonicalizer)
      : delegate_(std::move(delegate)),
        canonicalizer_(std::move(canonicalizer)) {
    FML_DCHECK(delegate_ != nullptr);
    FML_DCHECK(canonicalizer_ != nullptr);
  }

  int count() override { return delegate_->count(); }

  void getStyle(int index, SkFontStyle* style, SkString* name) override {
    delegate_->getStyle(index, style, name);
  }

  sk_sp<SkTypeface> createTypeface(int index) override {
    return canonicalizer_->Canonicalize(delegate_->createTypeface(index));
  }

  sk_sp<SkTypeface> matchStyle(const SkFontStyle& pattern) override {
    return canonicalizer_->Canonicalize(delegate_->matchStyle(pattern));
  }

 private:
  sk_sp<SkFontStyleSet> delegate_;
  sk_sp<FreeTypeCanonicalizer> canonicalizer_;
};

class FreeTypeCanonicalFontMgr final : public SkFontMgr {
 public:
  explicit FreeTypeCanonicalFontMgr(sk_sp<SkFontMgr> delegate)
      : delegate_(std::move(delegate)),
        canonicalizer_(sk_make_sp<FreeTypeCanonicalizer>()) {
    FML_DCHECK(delegate_ != nullptr);
  }

 protected:
  int onCountFamilies() const override { return delegate_->countFamilies(); }

  void onGetFamilyName(int index, SkString* family_name) const override {
    delegate_->getFamilyName(index, family_name);
  }

  sk_sp<SkFontStyleSet> onCreateStyleSet(int index) const override {
    return WrapStyleSet(delegate_->createStyleSet(index));
  }

  sk_sp<SkFontStyleSet> onMatchFamily(const char family_name[]) const override {
    return WrapStyleSet(delegate_->matchFamily(family_name));
  }

  sk_sp<SkTypeface> onMatchFamilyStyle(
      const char family_name[],
      const SkFontStyle& style) const override {
    return canonicalizer_->Canonicalize(
        delegate_->matchFamilyStyle(family_name, style));
  }

  sk_sp<SkTypeface> onMatchFamilyStyleCharacter(
      const char family_name[],
      const SkFontStyle& style,
      const char* bcp47[],
      int bcp47_count,
      SkUnichar character) const override {
    return canonicalizer_->Canonicalize(delegate_->matchFamilyStyleCharacter(
        family_name, style, bcp47, bcp47_count, character));
  }

  sk_sp<SkTypeface> onMakeFromData(sk_sp<SkData> data,
                                   int ttc_index) const override {
    return MakeFreeTypeTypefaceFromData(std::move(data), ttc_index);
  }

  sk_sp<SkTypeface> onMakeFromStreamIndex(std::unique_ptr<SkStreamAsset> stream,
                                          int ttc_index) const override {
    SkFontArguments arguments;
    arguments.setCollectionIndex(ttc_index);
    return MakeFreeTypeTypefaceFromStream(std::move(stream), arguments);
  }

  sk_sp<SkTypeface> onMakeFromStreamArgs(
      std::unique_ptr<SkStreamAsset> stream,
      const SkFontArguments& arguments) const override {
    return MakeFreeTypeTypefaceFromStream(std::move(stream), arguments);
  }

  sk_sp<SkTypeface> onMakeFromFile(const char path[],
                                   int ttc_index) const override {
    return MakeFreeTypeTypefaceFromFile(path, ttc_index);
  }

  sk_sp<SkTypeface> onLegacyMakeTypeface(const char family_name[],
                                         SkFontStyle style) const override {
    return canonicalizer_->Canonicalize(
        delegate_->legacyMakeTypeface(family_name, style));
  }

 private:
  sk_sp<SkFontStyleSet> WrapStyleSet(sk_sp<SkFontStyleSet> style_set) const {
    if (style_set == nullptr) {
      return nullptr;
    }
    return sk_make_sp<FreeTypeCanonicalFontStyleSet>(std::move(style_set),
                                                     canonicalizer_);
  }

  sk_sp<SkFontMgr> delegate_;
  sk_sp<FreeTypeCanonicalizer> canonicalizer_;
};

}  // namespace

sk_sp<SkFontMgr> MakeFreeTypeCanonicalFontManager(
    sk_sp<SkFontMgr> font_manager) {
  if (font_manager == nullptr) {
    return nullptr;
  }
  return sk_make_sp<FreeTypeCanonicalFontMgr>(std::move(font_manager));
}

sk_sp<SkTypeface> MakeFreeTypeCanonicalTypeface(sk_sp<SkTypeface> typeface) {
  return MakeFreeTypeTypefaceFromTypeface(std::move(typeface));
}

bool IsFreeTypeCanonicalTypefaceForTesting(const SkTypeface* typeface) {
  return IsFreeTypeCanonicalTypeface(typeface);
}

}  // namespace txt

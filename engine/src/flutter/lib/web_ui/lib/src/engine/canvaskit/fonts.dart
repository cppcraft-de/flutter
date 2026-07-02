// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import 'dart:async';
import 'dart:typed_data';

import 'package:ui/src/engine.dart';
import 'package:ui/ui_web/src/ui_web.dart' as ui_web;

// This URL was found by using the Google Fonts Developer API to find the URL
// for Roboto. The API warns that this URL is not stable. In order to update
// this, list out all of the fonts and find the URL for the regular
// Roboto font. The API reference is here:
// https://developers.google.com/fonts/docs/developer_api
String _robotoUrl =
    '${configuration.fontFallbackBaseUrl}roboto/v32/KFOmCnqEu92Fr1Me4GZLCzYlKw.woff2';

const bool _profileCanvasKitFontLoading = true;

double _fontLoadNow() {
  if (!_profileCanvasKitFontLoading) {
    return 0.0;
  }
  return domWindow.performance.now();
}

double _fontLoadElapsed(double start) {
  if (!_profileCanvasKitFontLoading) {
    return 0.0;
  }
  return domWindow.performance.now() - start;
}

String _fontLoadMs(double value) => value.toStringAsFixed(2);

/// Manages the fonts used in the Skia-based backend.
class SkiaFontCollection implements FlutterFontCollection {
  final Set<String> _downloadedFontFamilies = <String>{};

  @override
  late FontFallbackManager fontFallbackManager = FontFallbackManager(SkiaFallbackRegistry(this));

  /// Fonts that started the download process, but are not yet registered.
  ///
  /// /// Once downloaded successfully, this map is cleared and the resulting
  /// [UnregisteredFont]s are added to [_registeredFonts].
  final List<UnregisteredFont> _unregisteredFonts = <UnregisteredFont>[];

  final List<RegisteredFont> _registeredFonts = <RegisteredFont>[];
  final List<RegisteredFont> registeredFallbackFonts = <RegisteredFont>[];

  int _profileDynamicLoadCount = 0;
  double _profileDynamicTotalMs = 0.0;
  double _profileDynamicParseMs = 0.0;
  double _profileDynamicWarmupMs = 0.0;
  double _profileDynamicProviderMs = 0.0;
  double _profileDynamicCacheMs = 0.0;
  int _fontRegistrationGeneration = 0;

  /// Returns fonts that have been downloaded, registered, and parsed.
  ///
  /// This should only be used in tests.
  List<RegisteredFont>? get debugRegisteredFonts {
    List<RegisteredFont>? result;
    assert(() {
      result = _registeredFonts;
      return true;
    }());
    return result;
  }

  final Map<String, List<SkFont>> familyToFontMap = <String, List<SkFont>>{};

  void _ensureFontProvider() {
    if (_fontProvider != null) {
      return;
    }
    _fontProvider = canvasKit.TypefaceFontProvider.Make();
    _recreateSkFontCollection();
  }

  void _recreateSkFontCollection() {
    skFontCollection?.delete();
    skFontCollection = canvasKit.FontCollection.Make();
    skFontCollection!.enableFontFallback();
    skFontCollection!.setDefaultFontManager(_fontProvider);
  }

  double _registerFontWithFontProvider(RegisteredFont font) {
    final double start = _fontLoadNow();
    _ensureFontProvider();
    _fontProvider!.registerTypeface(font.typeface, font.family);
    familyToFontMap.putIfAbsent(font.family, () => <SkFont>[]).add(SkFont(font.typeface));
    _fontRegistrationGeneration += 1;
    return _fontLoadElapsed(start);
  }

  void _profileDynamicFontLoad({
    required String family,
    required int byteLength,
    required double totalMs,
    required double initializeMs,
    required double parseMs,
    required double familyMs,
    required double warmupMs,
    required double providerMs,
    required double cacheMs,
  }) {
    if (!_profileCanvasKitFontLoading) {
      return;
    }
    _profileDynamicLoadCount += 1;
    _profileDynamicTotalMs += totalMs;
    _profileDynamicParseMs += parseMs;
    _profileDynamicWarmupMs += warmupMs;
    _profileDynamicProviderMs += providerMs;
    _profileDynamicCacheMs += cacheMs;
    domWindow.console.debug(
      '[CanvasKitFontLoad] #$_profileDynamicLoadCount '
      'family="$family" bytes=$byteLength '
      'total=${_fontLoadMs(totalMs)}ms '
      'init=${_fontLoadMs(initializeMs)}ms '
      'parse=${_fontLoadMs(parseMs)}ms '
      'family=${_fontLoadMs(familyMs)}ms '
      'warmup=${_fontLoadMs(warmupMs)}ms '
      'provider=${_fontLoadMs(providerMs)}ms '
      'cache=${_fontLoadMs(cacheMs)}ms '
      'totals(total=${_fontLoadMs(_profileDynamicTotalMs)}ms '
      'parse=${_fontLoadMs(_profileDynamicParseMs)}ms '
      'warmup=${_fontLoadMs(_profileDynamicWarmupMs)}ms '
      'provider=${_fontLoadMs(_profileDynamicProviderMs)}ms '
      'cache=${_fontLoadMs(_profileDynamicCacheMs)}ms)',
    );
  }

  void _registerWithFontProvider() {
    if (_fontProvider != null) {
      _fontProvider!.delete();
      _fontProvider = null;
      skFontCollection?.delete();
      skFontCollection = null;
    }
    familyToFontMap.clear();

    for (final RegisteredFont font in _registeredFonts) {
      _registerFontWithFontProvider(font);
    }

    for (final RegisteredFont font in registeredFallbackFonts) {
      _registerFontWithFontProvider(font);
    }
  }

  @override
  Future<bool> loadFontFromList(Uint8List list, {String? fontFamily}) async {
    final double totalStart = _fontLoadNow();
    // Make sure CanvasKit is actually loaded
    final double initializeStart = _fontLoadNow();
    await renderer.initialize();
    final double initializeMs = _fontLoadElapsed(initializeStart);

    final double parseStart = _fontLoadNow();
    final SkTypeface? typeface = canvasKit.Typeface.MakeFreeTypeFaceFromData(list.buffer);
    final double parseMs = _fontLoadElapsed(parseStart);

    if (typeface != null) {
      double familyMs = 0.0;
      if (fontFamily == null) {
        // Read actual family name from SkTypeface
        final double familyStart = _fontLoadNow();
        fontFamily = typeface.getFamilyName();
        familyMs = _fontLoadElapsed(familyStart);
        if (fontFamily == null) {
          printWarning('Failed to read font family name. Aborting font load.');
          return false;
        }
      }
      final registeredFont = RegisteredFont(list, fontFamily, typeface);
      _registeredFonts.add(registeredFont);
      final double providerMs = _registerFontWithFontProvider(registeredFont);
      final double cacheStart = _fontLoadNow();
      skFontCollection?.clearFontLookupCaches();
      final double cacheMs = _fontLoadElapsed(cacheStart);
      _profileDynamicFontLoad(
        family: fontFamily,
        byteLength: list.length,
        totalMs: _fontLoadElapsed(totalStart),
        initializeMs: initializeMs,
        parseMs: parseMs,
        familyMs: familyMs,
        warmupMs: registeredFont.warmupMilliseconds,
        providerMs: providerMs,
        cacheMs: cacheMs,
      );
    } else {
      printWarning('Failed to parse font family "$fontFamily"');
      return false;
    }
    return true;
  }

  /// Loads fonts from `FontManifest.json`.
  @override
  Future<AssetFontsResult> loadAssetFonts(FontManifest manifest) async {
    final pendingDownloads = <Future<FontDownloadResult>>[];
    var loadedRoboto = false;
    for (final FontFamily family in manifest.families) {
      if (family.name == 'Roboto') {
        loadedRoboto = true;
      }
      for (final FontAsset fontAsset in family.fontAssets) {
        final String url = ui_web.assetManager.getAssetUrl(fontAsset.asset);
        pendingDownloads.add(_downloadFont(fontAsset.asset, url, family.name));
      }
    }

    /// We need a default fallback font for CanvasKit, in order to avoid
    /// crashing while laying out text with an unregistered font. We chose
    /// Roboto to match Android.
    if (!loadedRoboto) {
      // Download Roboto and add it to the font buffers.
      pendingDownloads.add(_downloadFont('Roboto', _robotoUrl, 'Roboto'));
    }

    final fontFailures = <String, FontLoadError>{};
    final downloadedFonts = <(String, UnregisteredFont)>[];
    for (final FontDownloadResult result in await Future.wait(pendingDownloads)) {
      if (result.font != null) {
        downloadedFonts.add((result.assetName, result.font!));
      } else {
        fontFailures[result.assetName] = result.error!;
      }
    }

    // Make sure CanvasKit is actually loaded
    await renderer.initialize();

    final loadedFonts = <String>[];
    for (final (String assetName, UnregisteredFont unregisteredFont) in downloadedFonts) {
      final Uint8List bytes = unregisteredFont.bytes.asUint8List();
      final SkTypeface? typeface = canvasKit.Typeface.MakeFreeTypeFaceFromData(bytes.buffer);
      if (typeface != null) {
        loadedFonts.add(assetName);
        _registeredFonts.add(RegisteredFont(bytes, unregisteredFont.family, typeface));
      } else {
        printWarning('Failed to load font ${unregisteredFont.family} at ${unregisteredFont.url}');
        printWarning('Verify that ${unregisteredFont.url} contains a valid font.');
        fontFailures[assetName] = FontInvalidDataError(unregisteredFont.url);
      }
    }
    registerDownloadedFonts();
    return AssetFontsResult(loadedFonts, fontFailures);
  }

  void registerDownloadedFonts() {
    RegisteredFont? makeRegisterFont(ByteBuffer buffer, String url, String family) {
      final Uint8List bytes = buffer.asUint8List();
      final SkTypeface? typeface = canvasKit.Typeface.MakeFreeTypeFaceFromData(bytes.buffer);
      if (typeface != null) {
        return RegisteredFont(bytes, family, typeface);
      } else {
        printWarning('Failed to load font $family at $url');
        printWarning('Verify that $url contains a valid font.');
        return null;
      }
    }

    for (final UnregisteredFont unregisteredFont in _unregisteredFonts) {
      final RegisteredFont? registeredFont = makeRegisterFont(
        unregisteredFont.bytes,
        unregisteredFont.url,
        unregisteredFont.family,
      );
      if (registeredFont != null) {
        _registeredFonts.add(registeredFont);
      }
    }

    _unregisteredFonts.clear();
    _registerWithFontProvider();
  }

  Future<FontDownloadResult> _downloadFont(String assetName, String url, String fontFamily) async {
    final ByteBuffer fontData;

    // Try to get the font leniently. Do not crash the app when failing to
    // fetch the font in the spirit of "gradual degradation of functionality".
    try {
      final HttpFetchResponse response = await httpFetch(url);
      if (!response.hasPayload) {
        printWarning('Font family $fontFamily not found (404) at $url');
        return FontDownloadResult.fromError(assetName, FontNotFoundError(url));
      }

      fontData = await response.asByteBuffer();
    } catch (e) {
      printWarning('Failed to load font $fontFamily at $url');
      printWarning(e.toString());
      return FontDownloadResult.fromError(assetName, FontDownloadError(url, e));
    }
    _downloadedFontFamilies.add(fontFamily);
    return FontDownloadResult.fromFont(assetName, UnregisteredFont(fontData, url, fontFamily));
  }

  TypefaceFontProvider? _fontProvider;
  SkFontCollection? skFontCollection;

  @override
  void clear() {}

  @override
  void debugResetFallbackFonts() {
    fontFallbackManager = FontFallbackManager(SkiaFallbackRegistry(this));
    registeredFallbackFonts.clear();
  }
}

/// Represents a font that has been registered.
class RegisteredFont {
  RegisteredFont(this.bytes, this.family, this.typeface) {
    final double warmupStart = _fontLoadNow();
    // This is a hack which causes Skia to cache the decoded font.
    final skFont = SkFont(typeface);
    skFont.getGlyphBounds(<int>[0], null, null);
    warmupMilliseconds = _fontLoadElapsed(warmupStart);
  }

  /// The font family name for this font.
  final String family;

  /// The byte data for this font.
  final Uint8List bytes;

  /// The [SkTypeface] created from this font's [bytes].
  ///
  /// This is used to determine which code points are supported by this font.
  final SkTypeface typeface;

  late final double warmupMilliseconds;
}

/// Represents a font that has been downloaded but not registered.
class UnregisteredFont {
  const UnregisteredFont(this.bytes, this.url, this.family);
  final ByteBuffer bytes;
  final String url;
  final String family;
}

class FontDownloadResult {
  FontDownloadResult.fromFont(this.assetName, UnregisteredFont this.font) : error = null;
  FontDownloadResult.fromError(this.assetName, FontLoadError this.error) : font = null;

  final String assetName;
  final UnregisteredFont? font;
  final FontLoadError? error;
}

class SkiaFallbackRegistry implements FallbackFontRegistry {
  SkiaFallbackRegistry(this._fontCollection);

  final SkiaFontCollection _fontCollection;
  final Map<String, List<int>> _missingCodePointCache = <String, List<int>>{};
  int _cachedFontRegistrationGeneration = -1;
  int _profileFallbackCallCount = 0;
  int _profileFallbackCachedCount = 0;
  double _profileFallbackTotalMs = 0.0;

  void _profileFallbackCheck({
    required bool cached,
    required int familyCount,
    required int fontCount,
    required int codeUnitCount,
    required int missingCount,
    required double elapsedMs,
  }) {
    _profileFallbackCallCount += 1;
    if (cached) {
      _profileFallbackCachedCount += 1;
    }
    _profileFallbackTotalMs += elapsedMs;
    if (elapsedMs < 1.0 && _profileFallbackCallCount % 100 != 0) {
      return;
    }
    domWindow.console.debug(
      '[CanvasKitFontFallback] calls=$_profileFallbackCallCount '
      'cached=$_profileFallbackCachedCount '
      'families=$familyCount fonts=$fontCount codeUnits=$codeUnitCount '
      'missing=$missingCount last=${_fontLoadMs(elapsedMs)}ms '
      'total=${_fontLoadMs(_profileFallbackTotalMs)}ms',
    );
  }

  @override
  List<int> getMissingCodePoints(List<int> codeUnits, List<String> fontFamilies) {
    final double totalStart = _fontLoadNow();
    if (_cachedFontRegistrationGeneration != _fontCollection._fontRegistrationGeneration) {
      _missingCodePointCache.clear();
      _cachedFontRegistrationGeneration = _fontCollection._fontRegistrationGeneration;
    }
    final String cacheKey = '${fontFamilies.join('\u0001')}|${codeUnits.join(',')}';
    final List<int>? cachedMissingCodeUnits = _missingCodePointCache[cacheKey];
    if (cachedMissingCodeUnits != null) {
      _profileFallbackCheck(
        cached: true,
        familyCount: fontFamilies.length,
        fontCount: -1,
        codeUnitCount: codeUnits.length,
        missingCount: cachedMissingCodeUnits.length,
        elapsedMs: _fontLoadElapsed(totalStart),
      );
      return cachedMissingCodeUnits;
    }

    final fonts = <SkFont>[];
    for (final font in fontFamilies) {
      final List<SkFont>? typefacesForFamily = _fontCollection.familyToFontMap[font];
      if (typefacesForFamily != null) {
        fonts.addAll(typefacesForFamily);
      }
    }
    final codePointsSupported = List<bool>.filled(codeUnits.length, false);
    final testString = String.fromCharCodes(codeUnits);
    for (final font in fonts) {
      final Uint16List glyphs = font.getGlyphIDs(testString);
      assert(glyphs.length == codePointsSupported.length);
      for (var i = 0; i < glyphs.length; i++) {
        codePointsSupported[i] |= glyphs[i] != 0;
      }
    }

    final missingCodeUnits = <int>[];
    for (var i = 0; i < codePointsSupported.length; i++) {
      if (!codePointsSupported[i]) {
        missingCodeUnits.add(codeUnits[i]);
      }
    }
    _missingCodePointCache[cacheKey] = missingCodeUnits;
    _profileFallbackCheck(
      cached: false,
      familyCount: fontFamilies.length,
      fontCount: fonts.length,
      codeUnitCount: codeUnits.length,
      missingCount: missingCodeUnits.length,
      elapsedMs: _fontLoadElapsed(totalStart),
    );
    return missingCodeUnits;
  }

  @override
  Future<void> loadFallbackFont(String familyName, String url) async {
    final ByteBuffer buffer = await httpFetchByteBuffer(url);
    final SkTypeface? typeface = canvasKit.Typeface.MakeFreeTypeFaceFromData(buffer);
    if (typeface == null) {
      printWarning('Failed to parse fallback font $familyName as a font.');
      return;
    }
    _fontCollection.registeredFallbackFonts.add(
      RegisteredFont(buffer.asUint8List(), familyName, typeface),
    );
  }

  @override
  void updateFallbackFontFamilies(List<String> families) {
    _fontCollection.registerDownloadedFonts();
  }
}

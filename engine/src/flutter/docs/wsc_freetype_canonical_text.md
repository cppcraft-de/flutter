# WSC FreeType-Canonical Text Path

This fork keeps native platform font discovery and fallback, then attempts to
convert selected typefaces to Skia's FreeType backend before shaping, metrics,
layout, text blob creation, or rendering consume them.

The policy is implemented in Flutter-owned `txt` code with a canonicalizing
`SkFontMgr`/`SkFontStyleSet` wrapper. Platform managers still decide which font
family, style, and fallback face wins. The wrapper then constructs the selected
font from the same font data using FreeType, preserving collection index,
variation coordinates, and palette arguments when Skia exposes them.
If font data cannot be opened or FreeType construction fails, the code asserts
with `FML_DCHECK`; without that assertion, it logs an error and returns the
original native typeface. Such fallback faces have no FreeType parity guarantee.

Existing WSC diagnostics and Qt parity adjustments remain part of the contract:
Qt-like integer layout metrics, subpixel-off SkParagraph settings, optional
advance/line diagnostics, and the third-party patch hooks remain in place.

Layout parity requires matching font data, selected faces/styles, text, and
layout inputs on SkParagraph/HarfBuzz/FreeType-backed paths. Sharing those
inputs with Impeller through SkTextBlob does not establish raster parity:
Impeller's Skia glyph atlas uses `kSlight` hinting and subpixel positioning.

Browser-native text paths are outside this parity scope. Experimental
WebParagraph uses browser text APIs; the historical HTML renderer did too.
CanvasKit/skwasm layout parity requires the SkParagraph/HarfBuzz/FreeType path
and matching font data owned by the wasm side. It still needs runtime validation.

See [dependency patch maintenance](../../../../docs/wsc/dependency-patches.md)
and [local engine development](../../../../docs/wsc/engine-identity.md#local-engine-development)
for engine work. For tester setup, settings, and capture procedures, use the
[FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).

## Runtime font diagnostics

The SDK includes the existing diagnostic APIs and data format, with collection
disabled by default. Before creating any paragraph, applications can call:

```dart
import 'dart:ui' as ui;

ui.configureFontRenderingDiagnostics(enabled: true);
```

Configure this before `WidgetsFlutterBinding.ensureInitialized()`. On native
and CanvasKit, the mode is fixed at the first paragraph builder; repeating the
same setting is allowed, but changing it afterward throws. Native applications
can alternatively select the startup mode with `WSC_FONT_DIAGNOSTICS=1` (or
`true`) in their environment. skwasm does not collect these extended diagnostics:
configuration is a no-op, queries return empty records, and there is no
startup-freeze enforcement.

The mode changes collection only. Script classification remains available for
cursive letter spacing even with collection disabled. Integer glyph-advance
rounding and the final paragraph occupied-height correction run in both modes. SkParagraph includes
the final occupied line box in its default height, so `Paragraph.height`,
`TextPainter.height`, and normal `RichText`/`Text` layout all receive it.
Line origins retain the signed baseline pitch. The height correction needs no
extra client API and does not allocate or decode diagnostic line records.
Raw shaping positions use `std::vector` and are retained only when enabled.
Disabled diagnostic queries return empty records. Backends without extended
diagnostics continue to report them unavailable.

`PainterTest.FontDiagnosticsRenderingParity` covers 81 combinations of fonts,
sizes, explicit/natural line heights, wrapping, hard breaks, and empty text
using native Skia rasterization. It compares diagnostics modes within that path;
it does not establish Impeller, web, cross-platform, or Qt parity.
Run it in separate processes with `WSC_FONT_DIAGNOSTICS=0` and `=1`.
Explicit height and strut controls now use their requested metrics; their old
fingerprints are not compatibility baselines. Preserve the accepted natural-height
Qt cases, and compare the current `FONT_RENDERING_PARITY` fingerprints between
diagnostics modes. The enabled `FONT_DIAGNOSTICS_PARITY` fingerprint remains
useful when comparing diagnostic records from equivalent implementations.
The test checks the always-on bottom correction and rejects mode changes after
paragraph creation. This does not replace an SDK build, application capture,
or a disabled-mode allocation/performance benchmark.

## Explicit height controls

Natural text retains the signed FreeType baseline pitch and final occupied-box
correction. An explicit text height instead feeds its adjusted ascent/descent
into layout, including empty paragraphs. Struts enforce their minimum or forced
height and split their leading around the baseline. First/last-line height
behavior restores raw font extents before applying the strut minimum. These paths
retain the fork's integer line-height rounding and run independently of diagnostic
collection. Raw font measurements stay separate from the selected layout inputs.

Qt HTML `line-height:100%` must be translated to natural metrics by the caller,
using `kTextHeightNone` rather than Flutter `TextStyle.height:1.0`. For the
tester's mapping and supported Qt block-height semantics, see the FRT README.

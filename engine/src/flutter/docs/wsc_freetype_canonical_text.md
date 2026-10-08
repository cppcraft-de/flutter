# WSC FreeType-Canonical Text Path

This fork keeps native platform font discovery and fallback, but canonicalizes
selected typefaces through Skia's FreeType backend before shaping, metrics,
layout, text blob creation, or rendering consume them.

The policy is implemented in Flutter-owned `txt` code with a canonicalizing
`SkFontMgr`/`SkFontStyleSet` wrapper. Platform managers still decide which font
family, style, and fallback face wins. The wrapper then constructs the selected
font from the same font data using FreeType, preserving collection index,
variation coordinates, and palette arguments when Skia exposes them.

Existing WSC diagnostics and Qt parity adjustments remain part of the contract:
Qt-like integer metrics, subpixel-off behavior, advance diagnostics, line
diagnostics, and the existing third-party patch hooks stay active.

Supported exact-parity paths are SkParagraph/HarfBuzz/FreeType-backed paths,
including native Skia raster and Impeller when text enters Impeller as
SkParagraph/SkTextBlob data.

Browser-native text paths are outside the exact-parity contract. The HTML
renderer and Experimental WebParagraph use browser text APIs for selection,
measurement, shaping, and rendering, so they cannot provide exact FreeType line
widths or line breaks in all cases. CanvasKit/skwasm parity requires the
SkParagraph/HarfBuzz/FreeType path and font data owned by the wasm side.

## Runtime font diagnostics

The SDK includes the existing diagnostic APIs and data format, with collection
disabled by default. Before creating any paragraph, applications can call:

```dart
import 'dart:ui' as ui;

ui.configureFontRenderingDiagnostics(enabled: true);
```

Configure this before `WidgetsFlutterBinding.ensureInitialized()`. The mode is
fixed at the first paragraph builder; repeating the same setting is allowed,
but changing it afterward throws. Native applications can alternatively select
the startup mode with `WSC_FONT_DIAGNOSTICS=1` (or `true`) in their environment.
The tester explicitly selects the mode from `FCTWEAK_LAYOUT_TRACE`, including
disabling collection when that variable is false.

The mode changes collection only. Integer glyph-advance rounding and the final
paragraph occupied-height correction run in both modes. The latter is exposed
as `Paragraph.paragraphBottomCorrection`, and forwarded by `TextPainter` and
`RenderParagraph`; it does not allocate or decode diagnostic line records.
Raw shaping positions use `std::vector` and are retained only when enabled.
Disabled diagnostic queries return empty records. Backends without extended
diagnostics continue to report them unavailable.

`PainterTest.FontDiagnosticsRenderingParity` covers 81 combinations of fonts,
sizes, explicit/natural line heights, wrapping, hard breaks, and empty text.
Run it in separate processes with `WSC_FONT_DIAGNOSTICS=0` and `=1`; their
`FONT_RENDERING_PARITY` fingerprints must match the pre-removal engine.
The enabled `FONT_DIAGNOSTICS_PARITY` fingerprint must also match that engine.
The test checks the always-on bottom correction and rejects mode changes after
paragraph creation. This does not replace an SDK build, application capture,
or a disabled-mode allocation/performance benchmark.

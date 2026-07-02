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

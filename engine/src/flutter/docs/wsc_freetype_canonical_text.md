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

WSC uses Qt-like integer layout metrics, subpixel-off SkParagraph settings,
and third-party patch hooks.

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

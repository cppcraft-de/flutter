# Legacy native-font diagnostics for FRT

`mimic_freetype_diag_v2` is a local-testing variant of `mimic_freetype`
(`5c3e3c44b3e`). It retains the legacy native font managers, advance selection,
hinting/environment overrides, line heights, and vendored FreeType 2.13.0.
There is no Jenkins or publication workflow on this branch.

## Enable diagnostics

Collection defaults to **off**. Configure it once at startup, before creating
any paragraph:

```dart
import 'dart:ui' as ui;
import 'package:flutter/widgets.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  ui.configureFontRenderingDiagnostics(enabled: true);
  runApp(const MyApp());
}
```

Native processes can instead start with `WSC_FONT_DIAGNOSTICS=1` or `true`.
An explicit Dart call overrides that startup value before the first paragraph
builder. Repeating the selected value is allowed; changing it after the first
builder throws `StateError`. Restart the application to change modes.
CanvasKit uses the Dart API; Skwasm and WebParagraph report diagnostics as
unavailable.

The current FRT client calls this API using `FCTWEAK_LAYOUT_TRACE` (currently
enabled by default in that client). Its `font-layout-trace/v2` JSON is assembled
by FRT, not by the SDK. Use an engine built from this branch and its matching
patched Dart UI summaries; selecting an old binary cannot expose these APIs.
For local development, use the normal `--local-engine`, `--local-engine-host`
and, when needed, `--local-engine-src-path` options. The bootstrap engine pin is
unchanged; no new artifacts have been uploaded.

## Contract and native-engine limits

The public diagnostic classes, indexed-line decoder, painted line boundaries,
and paint offset match `frt_diagnostics_v2` at `5dcab5be9fc`:

- `computeDetailedLineMetricsForDiagnostics()` supplies the existing 13-value
  line record. Raw metrics read the same internal raw fields as the current
  branch; legacy height-input accessors used by painting remain unchanged.
- `computeLineLayoutMetricsForDiagnostics()` uses the same versioned
  Float64 encoding: `[1, 10, recordCount]`, followed by indexed UTF-16 ranges,
  actual available width, content advances before/after justification, and
  completeness/ellipsis flags. This SDK record version is independent of
  FRT's JSON schema version. Terminal empty lines, wrap whitespace, and cached
  reformatting use the current branch's semantics.
- `computeGlyphMetricsForDiagnostics()` retains the legacy 74-field record.
  The current framework decoder explicitly supports this shape alongside the
  canonical engine's shorter record. Final origins and ink bounds describe the
  painted paragraph; raw glyph clusters and shaping ranges remain UTF-8.
  Raw positions are captured before spacing even when the legacy integer-metric
  override is disabled.
- `diagnosticPaintOffset` identifies the translation from raw engine coordinates
  to the painted paragraph's local coordinates. Public line metrics already
  include this translation.

Native font engines remain authoritative. DirectWrite design/GDI measurements
and CoreText advances are not FreeType hinted-slot measurements. The existing
backend identifiers and availability flags retain their meanings; FreeType-only
probe slots are not supplied by CoreText or DirectWrite. Treat unprovided
backend-specific slots as unavailable, not as evidence of a zero advance.
No FreeType canonicalization or later line-height fixes were ported.

The port follows the startup-gating change `a09c73bc6cc`, cursive-metadata fix
`bea926d9b46`, painted-line-boundary API `dada342e5a2`, and indexed-line contract
`5dcab5be9fc`.

When disabled, glyph queries and public diagnostic line queries return empty
lists. Raw-position vectors remain unallocated, shaping-feature/language
capture and diagnostic queries are gated, and optional DirectWrite GDI probes
are skipped. The legacy function named `getQtLikeGlyphAdvanceDiagnostics` also
supplies **functional** native advance selection; that calculation remains
active in both modes. Cursive script metadata likewise remains active.

## Patch application and validation

The existing dependency patch helper applies the legacy stack and then
`diagnostics/0004-runtime-and-indexed-line-diagnostics.patch`. It can also
upgrade an already-patched legacy checkout without resetting native layout
files. Use a separate dependency checkout when switching between this branch
and the FreeType-canonical branch; their patch stacks are different.

Two inherited helper defects were repaired: an undefined already-applied check
and an incorrect hunk count in the advance-probe patch. The Windows static
FreeType loader guard was ported from the current branch.

Source tests:

```text
python -m unittest discover -s engine/src/flutter/tools/wsc_font_rendering_patches -p test_apply_patches.py
```

The replay tests need the pinned local Skia, HarfBuzz, and FreeType checkouts.
They construct disposable fixtures and verify clean replay, legacy upgrades,
and idempotence. They do not modify the supplied dependency checkouts.

Local Windows validation on 2026-10-20:

- Compiled 239 native translation units, including the Dart UI bridge, native
  font code and vendored FreeType; linked a separate text-test executable.
- Compared 81 font/size/height/text cases against an isolated legacy build.
  Layout/raster fingerprint: `7705216687999681039` for the legacy build and
  the new branch in default/off/on modes. Enabled diagnostic fingerprint:
  `16212534152189280199`, also identical to legacy.
- New branch: 25 of 28 native tests pass in each mode. The same three existing
  Impeller recorder expectations fail on legacy and new:
  `DrawTextImpeller`, `DrawStrokedTextImpeller`, and
  `DrawEmojiTextWithGradientImpeller`. The new indexed-line and toggle/parity
  tests pass.
- Patched Dart UI summaries compile. Web Dart analysis is clean; framework
  analysis has no errors and one inherited local-variable-type style notice.
  Dart/C++ formatting and clean/upgrade patch replay pass.

These are isolated source/native tests, not a full rebuilt SDK or an FRT
application comparison. CanvasKit browser execution, macOS/CoreText compilation,
mobile builds, packaging, and end-to-end FRT acceptance remain unverified.

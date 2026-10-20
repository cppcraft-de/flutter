// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import 'dart:typed_data';

import 'package:test/bootstrap/browser.dart';
import 'package:test/test.dart';
import 'package:ui/src/engine.dart';
import 'package:ui/ui.dart' as ui;

import 'common.dart';

void main() {
  internalBootstrapBrowserTest(() => testMain);
}

void testMain() {
  setUpCanvasKitTest();
  setUpAll(() => ui.configureFontRenderingDiagnostics(enabled: true));

  test('indexed layout records preserve ranges and justification widths', () {
    const text = 'aa  bb cc  \n\u{1f600} dd\n';
    final builder = CkParagraphBuilder(CkParagraphStyle(textAlign: ui.TextAlign.justify));
    builder.pushStyle(CkTextStyle(fontFamily: 'Ahem', fontSize: 14));
    builder.addText(text);
    final CkParagraph paragraph = builder.build()
      ..layout(const ui.ParagraphConstraints(width: 100));
    addTearDown(paragraph.dispose);
    final double heightBefore = paragraph.height;
    final Float64List records = paragraph.computeLineLayoutMetricsForDiagnostics();
    expect(records.sublist(0, 3), <double>[1, 10, paragraph.numberOfLines.toDouble()]);
    expect(records.length, 3 + paragraph.numberOfLines * 10);
    var consumed = 0;
    for (var offset = 3; offset < records.length; offset += 10) {
      expect(records[offset + 1], consumed);
      expect(records[offset + 5], 100);
      expect(records[offset + 8], 1);
      expect(records[offset + 9], 0);
      consumed = records[offset + 4].toInt();
    }
    expect(consumed, text.length);
    expect(records[records.length - 9], text.length);
    expect(records[9], lessThan(records[10]));
    expect(records[10], 100);
    expect(paragraph.height, heightBefore);
    expect(paragraph.computeLineLayoutMetricsForDiagnostics(), records);
  });

  test('terminal empty line consumes no separator twice', () {
    for (final text in <String>['', 'a\n', 'a\r\n', 'a\u2028', 'a\n\n', '\n']) {
      final builder = CkParagraphBuilder(CkParagraphStyle());
      builder.pushStyle(CkTextStyle(fontFamily: 'Ahem', fontSize: 14));
      builder.addText(text);
      final CkParagraph paragraph = builder.build()
        ..layout(const ui.ParagraphConstraints(width: 100));
      addTearDown(paragraph.dispose);
      final Float64List records = paragraph.computeLineLayoutMetricsForDiagnostics();
      var consumed = 0;
      for (var offset = 3; offset < records.length; offset += 10) {
        expect(records[offset + 1], consumed);
        consumed = records[offset + 4].toInt();
      }
      expect(consumed, text.length);
      if (text.isNotEmpty) {
        expect(
          records.sublist(records.length - 9, records.length - 5),
          List<double>.filled(4, text.length.toDouble()),
        );
      }
    }
  });

  test('truncated paragraphs are explicitly incomplete', () {
    final builder = CkParagraphBuilder(CkParagraphStyle(maxLines: 1, ellipsis: '...'));
    builder.pushStyle(CkTextStyle(fontFamily: 'Ahem', fontSize: 14));
    builder.addText('aa bb cc dd ee ff');
    final CkParagraph paragraph = builder.build()
      ..layout(const ui.ParagraphConstraints(width: 100));
    addTearDown(paragraph.dispose);
    final Float64List records = paragraph.computeLineLayoutMetricsForDiagnostics();
    expect(records, hasLength(13));
    expect(records[11], 0);
    expect(records[12], 1);
  });
}

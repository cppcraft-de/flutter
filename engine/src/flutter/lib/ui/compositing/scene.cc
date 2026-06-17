// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "flutter/lib/ui/compositing/scene.h"

#include <cmath>
#include <string>
#include <vector>

#include "flutter/display_list/skia/dl_sk_canvas.h"
#include "flutter/fml/make_copyable.h"
#include "flutter/fml/status.h"
#include "flutter/fml/status_or.h"
#include "flutter/fml/trace_event.h"
#include "flutter/lib/ui/floating_point.h"
#include "flutter/lib/ui/painting/display_list_deferred_image_gpu_skia.h"
#include "flutter/lib/ui/painting/image.h"
#include "flutter/lib/ui/painting/picture.h"
#include "flutter/lib/ui/ui_dart_state.h"
#include "flutter/lib/ui/window/platform_configuration.h"
#if IMPELLER_SUPPORTS_RENDERING
#include "flutter/lib/ui/painting/display_list_deferred_image_gpu_impeller.h"
#endif  // IMPELLER_SUPPORTS_RENDERING
#include "third_party/skia/include/core/SkDocument.h"
#include "third_party/skia/include/core/SkImageInfo.h"
#include "third_party/skia/include/core/SkStream.h"
#include "third_party/skia/include/core/SkSurface.h"
#include "third_party/skia/include/docs/SkPDFDocument.h"
#include "third_party/skia/include/docs/SkPDFJpegHelpers.h"
#include "third_party/tonic/converter/dart_converter.h"
#include "third_party/tonic/dart_args.h"
#include "third_party/tonic/dart_binding_macros.h"
#include "third_party/tonic/dart_library_natives.h"
#include "third_party/tonic/dart_persistent_value.h"
#include "third_party/tonic/logging/dart_invoke.h"
#include "third_party/tonic/typed_data/typed_list.h"

namespace flutter {

IMPLEMENT_WRAPPERTYPEINFO(ui, Scene);

namespace {

struct PdfPage {
  std::unique_ptr<LayerTree> layer_tree;
  double source_width;
  double source_height;
};

void FinalizePdfData(void* isolate_callback_data, void* peer) {
  SkData* buffer = reinterpret_cast<SkData*>(peer);
  buffer->unref();
}

void InvokePdfCallback(std::unique_ptr<tonic::DartPersistentValue> callback,
                       fml::StatusOr<sk_sp<SkData>>&& buffer) {
  std::shared_ptr<tonic::DartState> dart_state =
      callback->dart_state().lock();
  if (!dart_state) {
    return;
  }
  tonic::DartState::Scope scope(dart_state);
  if (!buffer.ok()) {
    std::string error_copy(buffer.status().message());
    tonic::DartInvoke(callback->value(),
                      {Dart_Null(), tonic::ToDart(error_copy)});
    return;
  }

  void* bytes = const_cast<void*>(buffer.value()->data());
  const intptr_t length = buffer.value()->size();
  void* peer = reinterpret_cast<void*>(buffer.value().release());
  Dart_Handle dart_data = Dart_NewExternalTypedDataWithFinalizer(
      Dart_TypedData_kUint8, bytes, length, peer, length, FinalizePdfData);
  tonic::DartInvoke(callback->value(), {dart_data, Dart_Null()});
}

fml::StatusOr<sk_sp<SkData>> RenderPdf(
    std::vector<PdfPage> pages,
    double page_width,
    double page_height,
    const fml::TaskRunnerAffineWeakPtr<SnapshotDelegate>& snapshot_delegate) {
#if SLIMPELLER
  return fml::Status(fml::StatusCode::kUnimplemented,
                     "PDF export is unavailable in SLIMPELLER builds.");
#else
  SkDynamicMemoryWStream stream;
  sk_sp<SkDocument> document =
      SkPDF::MakeDocument(&stream, SkPDF::JPEG::MetadataWithCallbacks());
  if (!document) {
    return fml::Status(fml::StatusCode::kUnimplemented,
                       "SkPDF document creation failed.");
  }

  for (PdfPage& page : pages) {
    if (!page.layer_tree) {
      return fml::Status(fml::StatusCode::kInvalidArgument,
                         "PDF page scene was invalid.");
    }

    SkCanvas* canvas = document->beginPage(
        SkDoubleToScalar(page_width), SkDoubleToScalar(page_height));
    if (!canvas) {
      return fml::Status(fml::StatusCode::kInternal,
                         "SkPDF page creation failed.");
    }

    const DlRect source_bounds =
        DlRect::MakeWH(SafeNarrow(page.source_width),
                       SafeNarrow(page.source_height));
    sk_sp<DisplayList> display_list = page.layer_tree->Flatten(
        source_bounds, snapshot_delegate->GetTextureRegistry(),
        snapshot_delegate->GetGrContext());

    canvas->save();
    canvas->scale(SkDoubleToScalar(page_width / page.source_width),
                  SkDoubleToScalar(page_height / page.source_height));
    DlSkCanvasAdapter(canvas).DrawDisplayList(display_list);
    canvas->restore();

    document->endPage();
  }

  document->close();
  return stream.detachAsData();
#endif  // SLIMPELLER
}

}  // namespace

void Scene::create(Dart_Handle scene_handle,
                   std::shared_ptr<flutter::Layer> rootLayer) {
  auto scene = fml::MakeRefCounted<Scene>(std::move(rootLayer));
  scene->AssociateWithDartWrapper(scene_handle);
}

Scene::Scene(std::shared_ptr<flutter::Layer> rootLayer) {
  layer_tree_root_layer_ = std::move(rootLayer);
}

Scene::~Scene() {}

bool Scene::valid() {
  return layer_tree_root_layer_ != nullptr;
}

void Scene::dispose() {
  layer_tree_root_layer_.reset();
  ClearDartWrapper();
}

Dart_Handle Scene::toImageSync(uint32_t width,
                               uint32_t height,
                               Dart_Handle raw_image_handle) {
  TRACE_EVENT0("flutter", "Scene::toImageSync");

  if (!valid()) {
    return tonic::ToDart("Scene has been disposed.");
  }

  Scene::RasterizeToImage(width, height, raw_image_handle);
  return Dart_Null();
}

Dart_Handle Scene::toImage(uint32_t width,
                           uint32_t height,
                           Dart_Handle raw_image_callback) {
  TRACE_EVENT0("flutter", "Scene::toImage");

  if (!valid()) {
    return tonic::ToDart("Scene has been disposed.");
  }

  return Picture::RasterizeLayerTreeToImage(BuildLayerTree(width, height),
                                            raw_image_callback);
}

Dart_Handle Scene::toPdf(Dart_Handle scenes_handle,
                         Dart_Handle page_sizes_handle,
                         double page_width,
                         double page_height,
                         Dart_Handle pdf_callback) {
  TRACE_EVENT0("flutter", "Scene::toPdf");

  if (!Dart_IsList(scenes_handle)) {
    return tonic::ToDart("PDF pages must be a list of scenes.");
  }
  if (Dart_IsNull(pdf_callback) || !Dart_IsClosure(pdf_callback)) {
    return tonic::ToDart("PDF callback was invalid.");
  }
  if (page_width <= 0 || page_height <= 0) {
    return tonic::ToDart("PDF page dimensions were invalid.");
  }

  intptr_t page_count = 0;
  Dart_Handle list_result = Dart_ListLength(scenes_handle, &page_count);
  if (Dart_IsError(list_result)) {
    return list_result;
  }
  if (page_count <= 0) {
    return tonic::ToDart("PDF must contain at least one page.");
  }

  std::vector<double> page_sizes;
  page_sizes.reserve(page_count * 2);
  {
    tonic::Float64List page_sizes_list(page_sizes_handle);
    if (!page_sizes_list.data() ||
        page_sizes_list.num_elements() != page_count * 2) {
      page_sizes_list.Release();
      return tonic::ToDart("PDF page source dimensions were invalid.");
    }
    for (intptr_t i = 0; i < page_sizes_list.num_elements(); ++i) {
      page_sizes.push_back(page_sizes_list[i]);
    }
  }

  std::vector<Dart_Handle> scene_handles(page_count);
  Dart_Handle range_result =
      Dart_ListGetRange(scenes_handle, 0, page_count, scene_handles.data());
  if (Dart_IsError(range_result)) {
    return range_result;
  }

  std::vector<PdfPage> pages;
  pages.reserve(page_count);
  for (intptr_t i = 0; i < page_count; ++i) {
    Scene* scene = tonic::DartConverter<Scene*>::FromDart(scene_handles[i]);
    if (!scene || !scene->valid()) {
      return tonic::ToDart("PDF page scene was invalid or disposed.");
    }

    const double source_width = page_sizes[i * 2];
    const double source_height = page_sizes[i * 2 + 1];
    if (source_width <= 0 || source_height <= 0) {
      return tonic::ToDart("PDF page source dimensions were invalid.");
    }

    pages.push_back(PdfPage{
        .layer_tree =
            scene->BuildLayerTree(static_cast<uint32_t>(std::ceil(source_width)),
                                  static_cast<uint32_t>(std::ceil(source_height))),
        .source_width = source_width,
        .source_height = source_height,
    });
  }

  auto* dart_state = UIDartState::Current();
  auto ui_task_runner = dart_state->GetTaskRunners().GetUITaskRunner();
  auto raster_task_runner = dart_state->GetTaskRunners().GetRasterTaskRunner();
  auto snapshot_delegate = dart_state->GetSnapshotDelegate();
  auto callback =
      std::make_unique<tonic::DartPersistentValue>(dart_state, pdf_callback);

  auto ui_task =
      fml::MakeCopyable([callback = std::move(callback)](
                            fml::StatusOr<sk_sp<SkData>>&& data) mutable {
        InvokePdfCallback(std::move(callback), std::move(data));
      });

  fml::TaskRunner::RunNowOrPostTask(
      raster_task_runner,
      fml::MakeCopyable([ui_task_runner, snapshot_delegate,
                         pages = std::move(pages), page_width,
                         page_height, ui_task]() mutable {
        auto result = RenderPdf(std::move(pages), page_width, page_height,
                                snapshot_delegate);
        fml::TaskRunner::RunNowOrPostTask(
            ui_task_runner, [ui_task, result = std::move(result)]() mutable {
              ui_task(std::move(result));
            });
      }));

  return Dart_Null();
}

static sk_sp<DlImage> CreateDeferredImage(
    bool impeller,
    std::unique_ptr<LayerTree> layer_tree,
    fml::TaskRunnerAffineWeakPtr<SnapshotDelegate> snapshot_delegate,
    fml::RefPtr<fml::TaskRunner> raster_task_runner,
    const fml::RefPtr<SkiaUnrefQueue>& unref_queue) {
#if IMPELLER_SUPPORTS_RENDERING
  if (impeller) {
    return DlDeferredImageGPUImpeller::Make(std::move(layer_tree),
                                            std::move(snapshot_delegate),
                                            std::move(raster_task_runner));
  }
#endif  // IMPELLER_SUPPORTS_RENDERING

#if SLIMPELLER
  FML_LOG(FATAL) << "Impeller opt-out unavailable.";
  return nullptr;
#else   // SLIMPELLER
  const auto& frame_size = layer_tree->frame_size();
  const SkImageInfo image_info =
      SkImageInfo::Make(frame_size.width, frame_size.height,
                        kRGBA_8888_SkColorType, kPremul_SkAlphaType);
  return DlDeferredImageGPUSkia::MakeFromLayerTree(
      image_info, std::move(layer_tree), std::move(snapshot_delegate),
      raster_task_runner, unref_queue);
#endif  //  SLIMPELLER
}

void Scene::RasterizeToImage(uint32_t width,
                             uint32_t height,
                             Dart_Handle raw_image_handle) {
  auto* dart_state = UIDartState::Current();
  if (!dart_state) {
    return;
  }
  auto unref_queue = dart_state->GetSkiaUnrefQueue();
  auto snapshot_delegate = dart_state->GetSnapshotDelegate();
  auto raster_task_runner = dart_state->GetTaskRunners().GetRasterTaskRunner();

  auto image = CanvasImage::Create();
  auto dl_image = CreateDeferredImage(
      dart_state->IsImpellerEnabled(), BuildLayerTree(width, height),
      std::move(snapshot_delegate), std::move(raster_task_runner), unref_queue);
  image->set_image(dl_image);
  image->AssociateWithDartWrapper(raw_image_handle);
}

std::unique_ptr<flutter::LayerTree> Scene::takeLayerTree(uint64_t width,
                                                         uint64_t height) {
  return BuildLayerTree(width, height);
}

std::unique_ptr<LayerTree> Scene::BuildLayerTree(uint32_t width,
                                                 uint32_t height) {
  if (!valid()) {
    return nullptr;
  }
  return std::make_unique<LayerTree>(layer_tree_root_layer_,
                                     DlISize(width, height));
}

}  // namespace flutter

"""
TFT Assistant — OCR 引擎
========================
基于 RapidOCR + ONNX Runtime 的 rec-only 识别商店英雄名称。

流程：
  1. mss 截取指定 OCR 区域（BGR numpy array）
  2. 预处理（灰度 + CLAHE 对比度增强）
  3. RapidOCR `TextRecognizer` 识别单行文字
  4. 模糊匹配（difflib）对应英雄名称
  5. 返回每个 slot 的 (hero_id, confidence)

依赖：
    pip install rapidocr onnxruntime mss opencv-python
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from difflib import SequenceMatcher
from typing import Optional

import numpy as np

from config import APP_DATA_ROOT, RAW_DATA_DIR, RESOURCE_ROOT

logger = logging.getLogger("tft.ocr")


class _AttrDict(dict):
    """同时兼容 `cfg.foo` 与 `cfg.get("foo")` 的轻量配置对象。"""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _lazy_import():
    """延迟导入重型依赖，避免 UI 启动时阻塞。"""
    try:
        import mss
        from rapidocr.ch_ppocr_rec import TextRecInput, TextRecognizer
        from rapidocr.utils.typings import EngineType, LangRec, ModelType, OCRVersion, TaskType
        return mss, TextRecognizer, TextRecInput, EngineType, LangRec, ModelType, OCRVersion, TaskType
    except ImportError as e:
        raise ImportError(
            f"缺少依赖: {e}\n请运行: pip install rapidocr onnxruntime mss opencv-python"
        )


class OCREngine:
    """
    单例 OCR 引擎。首次调用 recognize() 时懒加载模型。
    """

    _instance: "OCREngine | None" = None

    @classmethod
    def instance(cls) -> "OCREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._deps = None
        self._hero_names: dict[str, str] = {}
        self._loaded = False
        self._thread_local = threading.local()
        self._model_root_dir = APP_DATA_ROOT / "models"
        self._bundled_model_path = RESOURCE_ROOT / "models" / "ch_PP-OCRv5_rec_mobile.onnx"

    def load(self):
        """加载 OCR 依赖与英雄名称库。"""
        if self._loaded:
            return
        self._deps = _lazy_import()
        self._model_root_dir.mkdir(parents=True, exist_ok=True)
        self._load_hero_names()
        self._loaded = True
        logger.info(
            "OCR 引擎加载完成，共 %d 个英雄，backend=RapidOCR(rec-only)",
            len(self._hero_names),
        )

    def is_loaded(self) -> bool:
        return self._loaded

    def _load_hero_names(self):
        path = RAW_DATA_DIR / "entity_units.json"
        if not path.exists():
            logger.warning("entity_units.json 不存在，OCR 匹配库为空")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._hero_names = {uid: info.get("name", uid) for uid, info in data.items()}

    def _build_rec_config(self):
        (
            _mss,
            _TextRecognizer,
            _TextRecInput,
            EngineType,
            LangRec,
            ModelType,
            OCRVersion,
            TaskType,
        ) = self._deps

        return _AttrDict(
            engine_type=EngineType.ONNXRUNTIME,
            lang_type=LangRec.CH,
            model_type=ModelType.MOBILE,
            ocr_version=OCRVersion.PPOCRV5,
            task_type=TaskType.REC,
            model_path=str(self._bundled_model_path) if self._bundled_model_path.exists() else None,
            model_root_dir=self._model_root_dir,
            rec_keys_path=None,
            rec_batch_num=6,
            rec_img_shape=[3, 48, 320],
            font_path=None,
            engine_cfg=_AttrDict(
                intra_op_num_threads=1,
                inter_op_num_threads=1,
                enable_cpu_mem_arena=False,
                cpu_ep_cfg=_AttrDict(arena_extend_strategy="kSameAsRequested"),
                use_cuda=False,
                cuda_ep_cfg=_AttrDict(
                    device_id=0,
                    arena_extend_strategy="kNextPowerOfTwo",
                    cudnn_conv_algo_search="EXHAUSTIVE",
                    do_copy_in_default_stream=True,
                ),
                use_dml=False,
                dm_ep_cfg=None,
                use_cann=False,
                cann_ep_cfg=_AttrDict(
                    device_id=0,
                    arena_extend_strategy="kNextPowerOfTwo",
                    npu_mem_limit=21474836480,
                    op_select_impl_mode="high_performance",
                    optypelist_for_implmode="Gelu",
                    enable_cann_graph=True,
                ),
            ),
        )

    def _get_worker_runtime(self) -> dict:
        runtime = getattr(self._thread_local, "runtime", None)
        if runtime is None:
            if self._deps is None:
                self._deps = _lazy_import()
            mss_mod, TextRecognizer, TextRecInput, *_ = self._deps
            runtime = {
                "ocr": TextRecognizer(self._build_rec_config()),
                "input_cls": TextRecInput,
                "sct": mss_mod.mss(),
            }
            self._thread_local.runtime = runtime
        return runtime

    def screenshot_region(self, rect: list[int]) -> np.ndarray:
        runtime = self._get_worker_runtime()
        x, y, w, h = rect
        mon = {"left": x, "top": y, "width": w, "height": h}
        raw = runtime["sct"].grab(mon)
        arr = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        return arr[:, :, :3]

    def screenshot_regions(self, rects: list[list[int]]) -> list[np.ndarray]:
        if not rects:
            return []

        left = min(r[0] for r in rects)
        top = min(r[1] for r in rects)
        right = max(r[0] + r[2] for r in rects)
        bottom = max(r[1] + r[3] for r in rects)

        merged = self.screenshot_region([left, top, right - left, bottom - top])
        crops = []
        for x, y, w, h in rects:
            rel_x = x - left
            rel_y = y - top
            crops.append(merged[rel_y:rel_y + h, rel_x:rel_x + w].copy())
        return crops

    def recognize_slot(self, rect: list[int]) -> tuple[Optional[str], float]:
        if not self._loaded:
            self.load()
        detail = self.recognize_slot_detail(rect)
        return detail["hero_id"], detail["score"]

    def recognize_all(self, ocr_rects: list[list[int]]) -> list[tuple[Optional[str], float]]:
        return [self.recognize_slot(r) for r in ocr_rects]

    def recognize_slot_detail(self, rect: list[int]) -> dict:
        if not self._loaded:
            self.load()
        img = self.screenshot_region(rect)
        return self._recognize_image_detail(img)

    def recognize_all_details(self, ocr_rects: list[list[int]]) -> list[dict]:
        if not self._loaded:
            self.load()
        if not ocr_rects:
            return []

        shot_started = time.perf_counter()
        imgs = self.screenshot_regions(ocr_rects)
        screenshot_ms = (time.perf_counter() - shot_started) * 1000
        details = self._recognize_images_detail(imgs)
        per_slot_shot_ms = screenshot_ms / max(1, len(details))
        for detail in details:
            detail["screenshot_ms"] = per_slot_shot_ms
            detail["elapsed_ms"] += per_slot_shot_ms
        return details

    def _recognize_images_detail(self, imgs: list[np.ndarray]) -> list[dict]:
        if not imgs:
            return []

        preprocess_started = time.perf_counter()
        processed_imgs = [self._preprocess(img) for img in imgs]
        preprocess_total_ms = (time.perf_counter() - preprocess_started) * 1000

        runtime = self._get_worker_runtime()
        infer_started = time.perf_counter()
        texts_scores = self._recognize_batch(processed_imgs, runtime)
        infer_total_ms = (time.perf_counter() - infer_started) * 1000

        per_slot_preprocess_ms = preprocess_total_ms / len(processed_imgs)
        per_slot_infer_ms = infer_total_ms / len(processed_imgs)

        details = []
        for text, ocr_score in texts_scores:
            match_started = time.perf_counter()
            hero_id, score = self._match_hero(text) if text else (None, 0.0)
            match_ms = (time.perf_counter() - match_started) * 1000
            details.append({
                "hero_id": hero_id,
                "score": max(score, ocr_score),
                "raw_text": text,
                "text_parts": [text] if text else [],
                "elapsed_ms": per_slot_preprocess_ms + per_slot_infer_ms + match_ms,
                "preprocess_ms": per_slot_preprocess_ms,
                "infer_ms": per_slot_infer_ms,
                "match_ms": match_ms,
                "screenshot_ms": 0.0,
            })
        return details

    def _recognize_image_detail(self, img: np.ndarray) -> dict:
        started = time.perf_counter()
        preprocess_started = time.perf_counter()
        processed = self._preprocess(img)
        preprocess_ms = (time.perf_counter() - preprocess_started) * 1000

        runtime = self._get_worker_runtime()
        infer_started = time.perf_counter()
        text, ocr_score = self._recognize_one_line(processed, runtime)
        infer_ms = (time.perf_counter() - infer_started) * 1000

        match_started = time.perf_counter()
        hero_id, score = self._match_hero(text) if text else (None, 0.0)
        match_ms = (time.perf_counter() - match_started) * 1000
        elapsed_ms = (time.perf_counter() - started) * 1000

        return {
            "hero_id": hero_id,
            "score": max(score, ocr_score),
            "raw_text": text,
            "text_parts": [text] if text else [],
            "elapsed_ms": elapsed_ms,
            "preprocess_ms": preprocess_ms,
            "infer_ms": infer_ms,
            "match_ms": match_ms,
            "screenshot_ms": 0.0,
        }

    @staticmethod
    def _recognize_one_line(img: np.ndarray, runtime: dict) -> tuple[str, float]:
        rgb = img[..., ::-1] if len(img.shape) == 3 and img.shape[2] == 3 else img
        rec_input = runtime["input_cls"](img=rgb, return_word_box=False)
        result = runtime["ocr"](rec_input)
        if not result or not result.txts:
            return "", 0.0
        text = result.txts[0].strip()
        score = float(result.scores[0]) if result.scores else 0.0
        return text, score

    @staticmethod
    def _recognize_batch(imgs: list[np.ndarray], runtime: dict) -> list[tuple[str, float]]:
        if not imgs:
            return []
        rgb_imgs = [
            img[..., ::-1] if len(img.shape) == 3 and img.shape[2] == 3 else img
            for img in imgs
        ]
        rec_input = runtime["input_cls"](img=rgb_imgs, return_word_box=False)
        result = runtime["ocr"](rec_input)
        if not result or not result.txts:
            return [("", 0.0) for _ in imgs]

        texts = list(result.txts or [])
        scores = list(result.scores or [])
        out = []
        for idx in range(len(imgs)):
            text = texts[idx].strip() if idx < len(texts) else ""
            score = float(scores[idx]) if idx < len(scores) else 0.0
            out.append((text, score))
        return out

    @staticmethod
    def _preprocess(img: np.ndarray) -> np.ndarray:
        try:
            import cv2

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            h, w = enhanced.shape
            enlarged = cv2.resize(enhanced, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
            return cv2.cvtColor(enlarged, cv2.COLOR_GRAY2BGR)
        except ImportError:
            return img

    def _match_hero(self, text: str) -> tuple[Optional[str], float]:
        if not text or not self._hero_names:
            return None, 0.0

        best_id = None
        best_score = 0.0
        for hero_id, hero_name in self._hero_names.items():
            if hero_name in text or text in hero_name:
                score = len(hero_name) / max(len(text), len(hero_name))
                if score > best_score:
                    best_id, best_score = hero_id, min(score * 1.2, 1.0)
                    continue

            score = SequenceMatcher(None, text, hero_name).ratio()
            if score > best_score:
                best_id, best_score = hero_id, score

        threshold = 0.55
        if best_score < threshold:
            return None, best_score
        return best_id, best_score

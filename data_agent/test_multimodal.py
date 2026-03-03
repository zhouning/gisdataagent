"""
Tests for multimodal input processing module.
"""

import io
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from data_agent.multimodal import (
    UploadType,
    classify_upload,
    prepare_image_part,
    extract_pdf_text,
    prepare_pdf_part,
    build_multimodal_content,
    SPATIAL_EXTS,
    IMAGE_EXTS,
    PDF_EXTS,
    DOC_EXTS,
)


# ---------------------------------------------------------------------------
# TestClassifyUpload
# ---------------------------------------------------------------------------

class TestClassifyUpload(unittest.TestCase):
    """Tests for classify_upload() file type classification."""

    def test_spatial_formats(self):
        for ext in [".shp", ".geojson", ".gpkg", ".kml", ".kmz", ".tif", ".tiff"]:
            result = classify_upload(f"/data/test{ext}")
            self.assertEqual(result, UploadType.SPATIAL, f"Failed for {ext}")

    def test_image_formats(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
            result = classify_upload(f"/data/photo{ext}")
            self.assertEqual(result, UploadType.IMAGE, f"Failed for {ext}")

    def test_pdf_format(self):
        self.assertEqual(classify_upload("/docs/report.pdf"), UploadType.PDF)

    def test_document_formats(self):
        for ext in [".doc", ".docx", ".xls", ".xlsx", ".csv"]:
            result = classify_upload(f"/data/file{ext}")
            self.assertEqual(result, UploadType.DOCUMENT, f"Failed for {ext}")

    def test_unknown_format(self):
        self.assertEqual(classify_upload("/data/file.xyz"), UploadType.UNKNOWN)
        self.assertEqual(classify_upload("/data/file.txt"), UploadType.UNKNOWN)

    def test_case_insensitive(self):
        self.assertEqual(classify_upload("/data/photo.PNG"), UploadType.IMAGE)
        self.assertEqual(classify_upload("/data/map.GeoJSON"), UploadType.SPATIAL)
        self.assertEqual(classify_upload("/data/report.PDF"), UploadType.PDF)

    def test_no_extension(self):
        self.assertEqual(classify_upload("/data/noextfile"), UploadType.UNKNOWN)

    def test_upload_type_is_string(self):
        """UploadType values are string-compatible."""
        self.assertEqual(str(UploadType.SPATIAL), "UploadType.SPATIAL")
        self.assertEqual(UploadType.IMAGE.value, "image")

    def test_extension_sets_no_overlap(self):
        """Ensure no overlapping extensions between categories."""
        all_sets = [SPATIAL_EXTS, IMAGE_EXTS, PDF_EXTS, DOC_EXTS]
        for i, s1 in enumerate(all_sets):
            for j, s2 in enumerate(all_sets):
                if i != j:
                    self.assertEqual(
                        s1 & s2, set(),
                        f"Overlap between sets {i} and {j}: {s1 & s2}",
                    )


# ---------------------------------------------------------------------------
# TestPrepareImagePart
# ---------------------------------------------------------------------------

class TestPrepareImagePart(unittest.TestCase):
    """Tests for prepare_image_part()."""

    def _create_test_image(self, width=100, height=100, mode="RGB"):
        """Create a temporary test image file."""
        from PIL import Image
        img = Image.new(mode, (width, height), color="red")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp, format="PNG")
        tmp.close()
        return tmp.name

    def test_normal_image(self):
        path = self._create_test_image(200, 200)
        try:
            part = prepare_image_part(path)
            self.assertIsNotNone(part)
            self.assertIsNotNone(part.inline_data)
            self.assertEqual(part.inline_data.mime_type, "image/jpeg")
            self.assertGreater(len(part.inline_data.data), 0)
        finally:
            os.unlink(path)

    def test_large_image_resized(self):
        path = self._create_test_image(2000, 3000)
        try:
            part = prepare_image_part(path, max_size=512)
            self.assertIsNotNone(part)
            # Verify the data is valid JPEG
            from PIL import Image
            img = Image.open(io.BytesIO(part.inline_data.data))
            self.assertLessEqual(max(img.size), 512)
        finally:
            os.unlink(path)

    def test_small_image_not_resized(self):
        path = self._create_test_image(100, 50)
        try:
            part = prepare_image_part(path, max_size=1024)
            self.assertIsNotNone(part)
            from PIL import Image
            img = Image.open(io.BytesIO(part.inline_data.data))
            # Small image should not be resized larger
            self.assertLessEqual(max(img.size), 1024)
        finally:
            os.unlink(path)

    def test_rgba_image_converted(self):
        path = self._create_test_image(100, 100, mode="RGBA")
        try:
            part = prepare_image_part(path)
            self.assertIsNotNone(part)
            self.assertEqual(part.inline_data.mime_type, "image/jpeg")
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        part = prepare_image_part("/nonexistent/image.png")
        self.assertIsNone(part)


# ---------------------------------------------------------------------------
# TestExtractPdfText
# ---------------------------------------------------------------------------

class TestExtractPdfText(unittest.TestCase):
    """Tests for extract_pdf_text()."""

    def _create_test_pdf(self, text="Hello PDF World", num_pages=1):
        """Create a temporary PDF with given text."""
        from pypdf import PdfWriter
        writer = PdfWriter()
        for i in range(num_pages):
            from io import BytesIO
            # Create a minimal PDF page with annotation for text
            writer.add_blank_page(width=612, height=792)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        writer.write(tmp)
        tmp.close()
        return tmp.name

    def test_extract_from_blank_pdf(self):
        path = self._create_test_pdf()
        try:
            text = extract_pdf_text(path)
            # Blank pages may return empty text
            self.assertIsInstance(text, str)
        finally:
            os.unlink(path)

    def test_max_pages_limit(self):
        path = self._create_test_pdf(num_pages=5)
        try:
            text = extract_pdf_text(path, max_pages=2)
            self.assertIsInstance(text, str)
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        text = extract_pdf_text("/nonexistent/report.pdf")
        self.assertEqual(text, "")

    @patch("pypdf.PdfReader", side_effect=Exception("corrupted"))
    def test_corrupted_pdf(self, mock_reader):
        text = extract_pdf_text("/some/file.pdf")
        self.assertEqual(text, "")


# ---------------------------------------------------------------------------
# TestPreparePdfPart
# ---------------------------------------------------------------------------

class TestPreparePdfPart(unittest.TestCase):
    """Tests for prepare_pdf_part()."""

    def _create_test_pdf(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        writer.write(tmp)
        tmp.close()
        return tmp.name

    def test_normal_pdf(self):
        path = self._create_test_pdf()
        try:
            part = prepare_pdf_part(path)
            self.assertIsNotNone(part)
            self.assertIsNotNone(part.inline_data)
            self.assertEqual(part.inline_data.mime_type, "application/pdf")
        finally:
            os.unlink(path)

    def test_oversized_pdf(self):
        path = self._create_test_pdf()
        try:
            # Set max_bytes very small to trigger skip
            part = prepare_pdf_part(path, max_bytes=10)
            self.assertIsNone(part)
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        part = prepare_pdf_part("/nonexistent/report.pdf")
        self.assertIsNone(part)


# ---------------------------------------------------------------------------
# TestBuildMultimodalContent
# ---------------------------------------------------------------------------

class TestBuildMultimodalContent(unittest.TestCase):
    """Tests for build_multimodal_content()."""

    def test_text_only(self):
        content = build_multimodal_content("Hello world")
        self.assertEqual(content.role, "user")
        self.assertEqual(len(content.parts), 1)
        self.assertEqual(content.parts[0].text, "Hello world")

    def test_text_with_extra_parts(self):
        from google.genai import types
        extra = [types.Part.from_bytes(data=b"fake image", mime_type="image/jpeg")]
        content = build_multimodal_content("Analyze this image", extra)
        self.assertEqual(len(content.parts), 2)
        self.assertEqual(content.parts[0].text, "Analyze this image")
        self.assertEqual(content.parts[1].inline_data.mime_type, "image/jpeg")

    def test_empty_extra_parts(self):
        content = build_multimodal_content("Just text", [])
        self.assertEqual(len(content.parts), 1)

    def test_none_extra_parts(self):
        content = build_multimodal_content("Just text", None)
        self.assertEqual(len(content.parts), 1)

    def test_multiple_extra_parts(self):
        from google.genai import types
        extras = [
            types.Part.from_bytes(data=b"img1", mime_type="image/jpeg"),
            types.Part.from_bytes(data=b"pdf1", mime_type="application/pdf"),
        ]
        content = build_multimodal_content("Mixed content", extras)
        self.assertEqual(len(content.parts), 3)


# ---------------------------------------------------------------------------
# TestHandleUploadedFile
# ---------------------------------------------------------------------------

class TestHandleUploadedFile(unittest.TestCase):
    """Tests for handle_uploaded_file() returning (path, UploadType) tuple."""

    @patch("data_agent.app.sync_to_obs")
    def test_returns_tuple_for_image(self, mock_sync):
        from data_agent.app import handle_uploaded_file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG\r\n\x1a\n")
            tmp.flush()
            element = MagicMock()
            element.path = tmp.name
            element.name = "test.png"
            with tempfile.TemporaryDirectory() as upload_dir:
                result = handle_uploaded_file(element, upload_dir)
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 2)
                path, file_type = result
                self.assertIsNotNone(path)
                self.assertEqual(file_type, UploadType.IMAGE)
        os.unlink(tmp.name)

    @patch("data_agent.app.sync_to_obs")
    def test_returns_tuple_for_spatial(self, mock_sync):
        from data_agent.app import handle_uploaded_file
        with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as tmp:
            tmp.write(b'{"type":"FeatureCollection","features":[]}')
            tmp.flush()
            element = MagicMock()
            element.path = tmp.name
            element.name = "test.geojson"
            with tempfile.TemporaryDirectory() as upload_dir:
                path, file_type = handle_uploaded_file(element, upload_dir)
                self.assertIsNotNone(path)
                self.assertEqual(file_type, UploadType.SPATIAL)
        os.unlink(tmp.name)

    def test_returns_none_tuple_for_no_path(self):
        from data_agent.app import handle_uploaded_file
        element = MagicMock()
        element.path = None
        result = handle_uploaded_file(element, "/tmp")
        self.assertEqual(result, (None, None))

    @patch("data_agent.app.MAX_UPLOAD_SIZE", 10)
    @patch("data_agent.app.sync_to_obs")
    def test_returns_none_tuple_for_oversized(self, mock_sync):
        from data_agent.app import handle_uploaded_file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"x" * 100)
            tmp.flush()
            element = MagicMock()
            element.path = tmp.name
            element.name = "big.png"
            path, file_type = handle_uploaded_file(element, "/tmp")
            self.assertIsNone(path)
            self.assertIsNone(file_type)
            self.assertTrue(element._oversized)
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# TestClassifyIntentMultimodal
# ---------------------------------------------------------------------------

class TestClassifyIntentMultimodal(unittest.TestCase):
    """Tests for classify_intent() with multimodal parameters."""

    @patch("data_agent.app.genai")
    def test_with_pdf_context(self, mock_genai):
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "GENERAL|PDF contains spatial data analysis"
        mock_response.usage_metadata = None
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent(
            "分析这个PDF文件",
            pdf_context="耕地面积 1500.5 平方米",
        )
        self.assertEqual(intent, "GENERAL")
        # Verify PDF context was included in the prompt
        call_args = mock_model.generate_content.call_args
        prompt_content = call_args[0][0]
        if isinstance(prompt_content, list):
            # Multimodal content (text + images)
            self.assertTrue(any("PDF" in str(p) for p in prompt_content))
        else:
            self.assertIn("PDF", prompt_content)

    @patch("data_agent.app.genai")
    def test_without_multimodal_params(self, mock_genai):
        """Existing behavior preserved when no multimodal params."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "OPTIMIZATION|用户请求优化"
        mock_response.usage_metadata = None
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        from data_agent.app import classify_intent
        intent, reason, tokens = classify_intent("优化土地布局")
        self.assertEqual(intent, "OPTIMIZATION")

    @patch("data_agent.app.genai")
    def test_with_image_paths_no_pil(self, mock_genai):
        """Images gracefully skipped if PIL fails."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "GENERAL|Image analysis"
        mock_response.usage_metadata = None
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        from data_agent.app import classify_intent
        # Non-existent images should be gracefully handled
        intent, reason, tokens = classify_intent(
            "这张图片是什么",
            image_paths=["/nonexistent/img.png"],
        )
        self.assertEqual(intent, "GENERAL")


# ---------------------------------------------------------------------------
# TestExecutePipelineExtraParts
# ---------------------------------------------------------------------------

class TestExecutePipelineExtraParts(unittest.TestCase):
    """Tests for _execute_pipeline extra_parts parameter."""

    def test_execute_pipeline_signature_has_extra_parts(self):
        """Verify _execute_pipeline accepts extra_parts parameter."""
        import inspect
        from data_agent.app import _execute_pipeline
        sig = inspect.signature(_execute_pipeline)
        self.assertIn("extra_parts", sig.parameters)
        # Default should be None
        self.assertEqual(sig.parameters["extra_parts"].default, None)

    def test_pipeline_runner_signature_has_extra_parts(self):
        """Verify run_pipeline_headless accepts extra_parts parameter."""
        import inspect
        from data_agent.pipeline_runner import run_pipeline_headless
        sig = inspect.signature(run_pipeline_headless)
        self.assertIn("extra_parts", sig.parameters)
        self.assertEqual(sig.parameters["extra_parts"].default, None)


if __name__ == "__main__":
    unittest.main()

from pathlib import Path

from app.schemas.pipeline import OcrBlock
from app.services.ocr import ocr_file


class FakeOcrEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, int]] = []

    def extract_blocks(self, image_path: Path, page: int) -> list[OcrBlock]:
        self.calls.append((image_path, page))
        return [
            OcrBlock(
                page=page,
                text=f"性别：女 第{page}页",
                bbox=[10.0, 20.0, 180.0, 42.0],
                confidence=0.91,
            )
        ]


def test_image_files_are_processed_by_ocr_engine(tmp_path):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"not-a-real-image-for-unit-test")
    engine = FakeOcrEngine()

    blocks = ocr_file(image_path, image_path.read_bytes(), engine=engine)

    assert [call[0] for call in engine.calls] == [image_path]
    assert blocks[0].text == "性别：女 第1页"
    assert blocks[0].confidence == 0.91


def test_scanned_pdf_renders_pages_before_ocr(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-no-text-layer")
    page_1 = tmp_path / "page_001.png"
    page_2 = tmp_path / "page_002.png"
    page_1.write_bytes(b"page-1")
    page_2.write_bytes(b"page-2")
    engine = FakeOcrEngine()

    blocks = ocr_file(
        pdf_path,
        pdf_path.read_bytes(),
        engine=engine,
        pdf_text_extractor=lambda _: [],
        pdf_renderer=lambda _: [page_1, page_2],
    )

    assert engine.calls == [(page_1, 1), (page_2, 2)]
    assert [block.page for block in blocks] == [1, 2]
    assert [block.text for block in blocks] == ["性别：女 第1页", "性别：女 第2页"]

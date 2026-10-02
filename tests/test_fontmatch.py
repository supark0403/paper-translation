"""서체 분석 단위 테스트 (PDF 없이 순수 로직 검증)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fontmatch import DocStyle, block_alignment, classify_font


def test_classify():
    assert classify_font("NimbusRomNo9L-Regu") == "serif"
    assert classify_font("TimesNewRomanPSMT") == "serif"
    assert classify_font("CMR10") == "serif"
    assert classify_font("NimbusSanL-Regu") == "sans"
    assert classify_font("Helvetica") == "sans"
    assert classify_font("ArialMT") == "sans"
    assert classify_font("MS-Gothic") == "sans"
    assert classify_font("SimSun") == "serif"
    assert classify_font("Batang") == "serif"
    assert classify_font("CMMI10") == "unknown"
    print("classify OK")


def test_alignment():
    # 양쪽정렬: 마지막 줄 제외하고 우측 끝 일치
    assert block_alignment([500.0, 501.0, 499.5, 320.0], 502.0) == "justify"
    assert block_alignment([400.0, 450.0, 320.0], 502.0) == "left"
    assert block_alignment([500.0], 502.0) == "left"
    print("alignment OK")


def test_defaults():
    assert DocStyle().serif is True
    assert DocStyle().leading == 1.32
    print("defaults OK")


if __name__ == "__main__":
    test_classify()
    test_alignment()
    test_defaults()
    print("ALL FONTMATCH TESTS PASSED")

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extract .docx content with proper encoding"""
import sys
from docx import Document

def extract_docx(filepath):
    doc = Document(filepath)

    # Extract paragraphs with style information
    content = []
    for para in doc.paragraphs:
        if para.text.strip():
            style = para.style.name if para.style else "Normal"
            content.append(f"[{style}] {para.text}")

    return "\n".join(content)

if __name__ == "__main__":
    filepath = "时空数据中台产品详细设计V3.0.0.0（Data Agent部分）.docx"
    result = extract_docx(filepath)

    # Write with UTF-8 encoding
    with open("doc_structure.txt", "w", encoding="utf-8") as f:
        f.write(result)

    print("Extraction complete. Output saved to doc_structure.txt")

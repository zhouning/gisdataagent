import os
import re
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

def generate_word_report(markdown_text: str, output_path: str = "report.docx"):
    """
    Convert Markdown text (with image paths) to a formatted Word document.
    Handles: Headers (#), Bold (**), Lists (-), and Images (file paths).
    """
    doc = Document()
    
    # Set default font
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Microsoft YaHei'
    font.size = Pt(11)
    
    # Title
    doc.add_heading('GIS 空间布局优化分析报告', 0)
    
    # Split text by lines
    lines = markdown_text.split('\n')
    
    # Regex to detect image paths (D:\...png or /...png)
    img_pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.png'
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 1. Image Handling
        img_match = re.search(img_pattern, line, re.IGNORECASE)
        if img_match:
            img_path = img_match.group(0)
            if os.path.exists(img_path):
                try:
                    doc.add_picture(img_path, width=Inches(6.0))
                    last_paragraph = doc.paragraphs[-1] 
                    last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    # Add caption
                    caption = os.path.basename(img_path)
                    p = doc.add_paragraph(f"图：{caption}")
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p.style = 'Caption'
                except Exception as e:
                    doc.add_paragraph(f"[Image load failed: {img_path}]")
            # Don't skip the line text entirely, as it might contain description
            clean_text = line.replace(img_path, "")
            if clean_text.strip():
                doc.add_paragraph(clean_text)
            continue
            
        # 2. Headers
        if line.startswith('### '):
            doc.add_heading(line[4:], level=3)
        elif line.startswith('## '):
            doc.add_heading(line[3:], level=2)
        elif line.startswith('# '):
            doc.add_heading(line[2:], level=1)
            
        # 3. List Items
        elif line.startswith('* ') or line.startswith('- '):
            p = doc.add_paragraph(line[2:], style='List Bullet')
            
        # 4. Numbered Lists
        elif re.match(r'^\d+\. ', line):
            p = doc.add_paragraph(line, style='List Number')
            
        # 5. Normal Text (with Bold handling)
        else:
            p = doc.add_paragraph()
            # Simple bold parsing (**text**)
            parts = re.split(r'(\*\*.*?\*\*)', line)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
                    
    doc.save(output_path)
    return os.path.abspath(output_path)

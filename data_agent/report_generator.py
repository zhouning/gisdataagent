import os
import re
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def set_cell_background(cell, fill_color):
    """Helper to set background color for a table cell."""
    shading_elm = OxmlElement('w:shd')
    shading_elm.set(qn('w:fill'), fill_color)
    cell._tc.get_or_add_tcPr().append(shading_elm)

def generate_word_report(markdown_text: str, output_path: str = "report.docx"):
    """
    Convert Markdown text (with images and tables) to a formatted Word document.
    """
    doc = Document()
    
    # Set default font (Microsoft YaHei)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Microsoft YaHei'
    font.size = Pt(10.5)
    # Important for Word to recognize the font for East Asian text
    doc.styles['Normal']._element.rPr.get_or_add_rFonts().set(qn('w:eastAsia'), 'Microsoft YaHei')
    
    # Title
    title_p = doc.add_heading('地理空间智能治理与优化分析报告', 0)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Split text by lines
    lines = markdown_text.split('\n')
    
    # Regex to detect image paths
    img_pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.png'
    
    table_buffer = []
    in_table = False
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # --- 1. Table Detection & Handling ---
        if line.startswith('|') and i + 1 < len(lines) and re.match(r'^[|\s\-:]+$', lines[i+1].strip()):
            in_table = True
            table_buffer = []
            # Collect table rows
            while i < len(lines) and lines[i].strip().startswith('|'):
                # Skip the delimiter line (|---|)
                if not re.match(r'^[|\s\-:]+$', lines[i].strip()):
                    # Parse row: | a | b | -> ['a', 'b']
                    row_data = [cell.strip() for cell in lines[i].strip('|').split('|')]
                    table_buffer.append(row_data)
                i += 1
            
            if table_buffer:
                # Create Word Table
                rows = len(table_buffer)
                cols = max(len(r) for r in table_buffer)
                table = doc.add_table(rows=rows, cols=cols)
                table.style = 'Table Grid'
                
                for r_idx, row_cells in enumerate(table_buffer):
                    for c_idx, val in enumerate(row_cells):
                        if c_idx < cols:
                            cell = table.cell(r_idx, c_idx)
                            # Handle formatting inside cell (like **bold**)
                            p = cell.paragraphs[0]
                            # Simple bold handling
                            parts = re.split(r'(\*\*.*?\*\*)', val)
                            for part in parts:
                                if part.startswith('**') and part.endswith('**'):
                                    run = p.add_run(part[2:-2])
                                    run.bold = True
                                else:
                                    p.add_run(part)
                            
                            # Header styling
                            if r_idx == 0:
                                set_cell_background(cell, "4472C4") # Blue header
                                p.runs[0].font.color.rgb = RGBColor(255, 255, 255)
                                p.runs[0].bold = True
                doc.add_paragraph() # Add space after table
            in_table = False
            continue # Already advanced 'i'
            
        if not line:
            i += 1
            continue

        # --- 2. Image Handling ---
        img_match = re.search(img_pattern, line, re.IGNORECASE)
        if img_match:
            img_path = img_match.group(0)
            if os.path.exists(img_path):
                try:
                    doc.add_picture(img_path, width=Inches(5.8))
                    last_paragraph = doc.paragraphs[-1] 
                    last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    caption = os.path.basename(img_path)
                    p = doc.add_paragraph(f"图：{caption}")
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                except:
                    doc.add_paragraph(f"[图片加载失败: {img_path}]")
            i += 1
            continue

        # --- 3. Headers ---
        if line.startswith('### '):
            doc.add_heading(line[4:], level=3)
        elif line.startswith('## '):
            doc.add_heading(line[3:], level=2)
        elif line.startswith('# '):
            doc.add_heading(line[2:], level=1)
            
        # --- 4. Lists ---
        elif line.startswith('* ') or line.startswith('- '):
            doc.add_paragraph(line[2:], style='List Bullet')
        elif re.match(r'^\d+\. ', line):
            doc.add_paragraph(line, style='List Number')
            
        # --- 5. Text ---
        else:
            p = doc.add_paragraph()
            parts = re.split(r'(\*\*.*?\*\*)', line)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
        
        i += 1
                    
    doc.save(output_path)
    return os.path.abspath(output_path)

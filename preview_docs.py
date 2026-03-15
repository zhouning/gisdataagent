import os
import xml.etree.ElementTree as ET

def dita_to_html_inner(element):
    html = ""
    tag = element.tag
    
    # Handle known DITA tags
    if tag == 'p':
        html += f"<p>{get_text_with_children(element)}</p>"
    elif tag in ['ul', 'ol', 'dl']:
        html += f"<{tag}>{''.join(dita_to_html_inner(child) for child in element)}</{tag}>"
    elif tag == 'li':
        html += f"<li>{get_text_with_children(element)}</li>"
    elif tag == 'dlentry':
        html += "".join(dita_to_html_inner(child) for child in element)
    elif tag == 'dt':
        html += f"<dt><b>{get_text_with_children(element)}</b></dt>"
    elif tag == 'dd':
        html += f"<dd>{get_text_with_children(element)}</dd>"
    elif tag == 'section':
        title = element.find('title')
        title_text = title.text if title is not None else ""
        html += f"<section><h3>{title_text}</h3>"
        for child in element:
            if child.tag != 'title':
                html += dita_to_html_inner(child)
        html += "</section>"
    elif tag == 'table':
        title = element.find('title')
        title_text = title.text if title is not None else "Table"
        html += f"<h4>{title_text}</h4><table border='1' style='border-collapse: collapse; width: 100%;'>"
        for tgroup in element.findall('tgroup'):
            # Simple table rendering
            thead = tgroup.find('thead')
            if thead is not None:
                html += "<thead>"
                for row in thead.findall('row'):
                    html += "<tr>" + "".join(f"<th>{get_text_with_children(entry)}</th>" for entry in row.findall('entry')) + "</tr>"
                html += "</thead>"
            tbody = tgroup.find('tbody')
            if tbody is not None:
                html += "<tbody>"
                for row in tbody.findall('row'):
                    html += "<tr>" + "".join(f"<td>{get_text_with_children(entry)}</td>" for entry in row.findall('entry')) + "</tr>"
                html += "</tbody>"
        html += "</table>"
    elif tag == 'fig':
        title = element.find('title')
        title_text = title.text if title is not None else ""
        img = element.find('image')
        href = img.get('href') if img is not None else "#"
        html += f"<figure style='text-align: center; margin: 20px; border: 1px solid #ddd; padding: 10px; background: #f9f9f9;'>"
        
        # 检查图片是否存在，如果存在则直接显示，否则显示占位符
        img_path = os.path.join("docs", "dita", href)
        if os.path.exists(img_path):
            html += f"<img src='{href}' alt='{title_text}' style='max-width: 100%; height: auto; display: block; margin: 0 auto; box-shadow: 0 4px 8px rgba(0,0,0,0.1);' />"
        else:
            # Maybe the user ran it from inside docs/dita or with a different path, let's also try relative to cwd
            if os.path.exists(href) or os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "dita", href)):
                 html += f"<img src='{href}' alt='{title_text}' style='max-width: 100%; height: auto; display: block; margin: 0 auto; box-shadow: 0 4px 8px rgba(0,0,0,0.1);' />"
            else:
                 html += f"<div style='height: 150px; background: #eee; line-height: 150px; color: #999; border: 1px dashed #ccc;'>[图片占位符: {href}] (待放入图片)</div>"
            
        html += f"<figcaption style='margin-top: 10px; font-style: italic; color: #555;'>图: {title_text}</figcaption></figure>"
    elif tag == 'codeblock':
        html += f"<pre style='background: #2d2d2d; color: #ccc; padding: 15px; border-radius: 5px; overflow-x: auto;'><code>{get_text_with_children(element)}</code></pre>"
    elif tag == 'note':
        ntype = element.get('type', 'note').upper()
        html += f"<div style='border-left: 5px solid #ffcc00; background: #fff9e6; padding: 10px; margin: 10px 0;'><b>{ntype}:</b> {get_text_with_children(element)}</div>"
    elif tag == 'steps':
        html += "<ol>" + "".join(dita_to_html_inner(child) for child in element) + "</ol>"
    elif tag == 'step':
        html += "<li>" + "".join(dita_to_html_inner(child) for child in element) + "</li>"
    elif tag == 'cmd':
        html += f"<b>{get_text_with_children(element)}</b>"
    elif tag == 'info':
        html += f"<div style='margin-left: 20px; color: #555;'>{get_text_with_children(element)}</div>"
    elif tag == 'stepxmp':
        html += f"<div style='margin: 10px 0 10px 20px; font-size: 0.9em; border-left: 3px solid #ccc; padding-left: 10px;'><i>示例:</i><br/>" + "".join(dita_to_html_inner(child) for child in element) + "</div>"
    elif tag == 'stepresult':
        html += f"<div style='margin: 10px 0 10px 20px; border: 1px solid #e0e0e0; padding: 10px; background: #f5f5f5;'><i>结果:</i><br/>" + "".join(dita_to_html_inner(child) for child in element) + "</div>"
    elif tag == 'shortdesc':
        html += f"<p style='font-size: 1.2em; color: #666; font-style: italic;'>{get_text_with_children(element)}</p>"
    elif tag in ['taskbody', 'conbody', 'context', 'prereq']:
        html += "".join(dita_to_html_inner(child) for child in element)
    elif tag == 'title':
        pass # Handled by parents
    else:
        # Fallback for nested tags like b, i, codeph
        html += get_text_with_children(element)
    
    return html

def get_text_with_children(element):
    text = element.text or ""
    for child in element:
        if child.tag == 'b':
            text += f"<b>{get_text_with_children(child)}</b>"
        elif child.tag == 'i':
            text += f"<i>{get_text_with_children(child)}</i>"
        elif child.tag == 'codeph':
            text += f"<code style='background: #eee; padding: 2px 4px; border-radius: 3px;'>{get_text_with_children(child)}</code>"
        else:
            text += dita_to_html_inner(child)
        if child.tail:
            text += child.tail
    return text

def main():
    base_dir = "docs/dita"
    map_file = os.path.join(base_dir, "data-agent-user-guide.ditamap")
    
    tree = ET.parse(map_file)
    root = tree.getroot()
    map_title = root.get('title', 'DITA Documentation')
    
    full_html = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>{map_title} - 预览</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 40px; color: #333; }}
            h1 {{ border-bottom: 2px solid #eee; padding-bottom: 10px; color: #0366d6; }}
            h2 {{ border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 40px; color: #24292e; }}
            h3 {{ color: #444; margin-top: 30px; }}
            code {{ font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace; }}
            table {{ margin: 20px 0; border-collapse: collapse; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background: #f6f8fa; }}
            .nav {{ position: fixed; left: 20px; top: 100px; width: 200px; font-size: 0.9em; }}
            .nav ul {{ list-style: none; padding: 0; }}
            .nav li {{ margin-bottom: 8px; }}
            .nav a {{ text-decoration: none; color: #0366d6; }}
            .nav a:hover {{ text-decoration: underline; }}
            @media (max-width: 1200px) {{ .nav {{ position: static; width: auto; margin-bottom: 40px; }} }}
        </style>
    </head>
    <body>
        <h1>{map_title}</h1>
        <div class="nav">
            <b>目录</b>
            <ul>
    """
    
    content_html = ""
    
    for topicref in root.findall('.//topicref'):
        href = topicref.get('href')
        navtitle = topicref.get('navtitle', href)
        topic_id = href.split('.')[0]
        
        full_html += f"<li><a href='#{topic_id}'>{navtitle}</a></li>"
        
        topic_path = os.path.join(base_dir, href)
        if os.path.exists(topic_path):
            t_tree = ET.parse(topic_path)
            t_root = t_tree.getroot()
            t_title = t_root.find('title').text
            
            content_html += f"<article id='{topic_id}'><h2>{t_title}</h2>"
            content_html += dita_to_html_inner(t_root)
            content_html += "</article><hr/>"
            
    full_html += """
            </ul>
        </div>
    """
    full_html += content_html
    full_html += """
    <footer style='margin-top: 100px; text-align: center; color: #888; font-size: 0.8em;'>
        Generated by Data Agent Doc Previewer for Peking University Technical Writing Course
    </footer>
    </body>
    </html>
    """
    
    with open("docs/dita/preview.html", "w", encoding="utf-8") as f:
        f.write(full_html)
    print("Preview generated at docs/dita/preview.html")

if __name__ == "__main__":
    main()

"""Convert LaTeX paper to Markdown, then generate Chinese and English Word documents."""
import re
import os
import sys

def tex_to_markdown(tex_path):
    """Convert a LaTeX file to clean Markdown."""
    with open(tex_path, 'r', encoding='utf-8') as f:
        tex = f.read()

    # Strip preamble
    if r'\begin{document}' in tex:
        tex = tex.split(r'\begin{document}', 1)[1]
    if r'\end{document}' in tex:
        tex = tex.split(r'\end{document}', 1)[0]

    # Remove comments
    tex = re.sub(r'%.*$', '', tex, flags=re.MULTILINE)

    # Extract title
    title_m = re.search(r'\\title\{(.+?)\}', tex, re.DOTALL)
    title = title_m.group(1) if title_m else 'Paper'
    title = title.replace('\\\\', ' — ').replace('\n', ' ')
    title = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', title).strip()

    # Sections
    tex = re.sub(r'\\section\{([^}]+)\}', r'\n## \1\n', tex)
    tex = re.sub(r'\\subsection\{([^}]+)\}', r'\n### \1\n', tex)
    tex = re.sub(r'\\subsubsection\{([^}]+)\}', r'\n#### \1\n', tex)

    # Abstract
    tex = re.sub(r'\\begin\{abstract\}', '\n## Abstract\n', tex)
    tex = re.sub(r'\\end\{abstract\}', '', tex)

    # Formatting
    tex = re.sub(r'\\textbf\{([^}]+)\}', r'**\1**', tex)
    tex = re.sub(r'\\textit\{([^}]+)\}', r'*\1*', tex)
    tex = re.sub(r'\\emph\{([^}]+)\}', r'*\1*', tex)
    tex = re.sub(r'\\texttt\{([^}]+)\}', r'`\1`', tex)

    # Inline math
    tex = re.sub(r'\$([^$]+)\$', r'`\1`', tex)

    # Citations
    tex = re.sub(r'\\cite[tp]?\{([^}]+)\}', r'[\1]', tex)

    # Lists
    tex = re.sub(r'\\begin\{(itemize|enumerate)\}', '', tex)
    tex = re.sub(r'\\end\{(itemize|enumerate)\}', '', tex)
    tex = re.sub(r'\\item\s*', '- ', tex)

    # Remove complex environments
    for env in ['figure', 'table', 'tikzpicture', 'algorithm', 'algorithmic']:
        tex = re.sub(
            r'\\begin\{' + env + r'\*?\}.*?\\end\{' + env + r'\*?\}',
            '', tex, flags=re.DOTALL
        )

    # Equations → keep as code blocks
    tex = re.sub(r'\\begin\{(equation|align|gather)\*?\}', '\n```\n', tex)
    tex = re.sub(r'\\end\{(equation|align|gather)\*?\}', '\n```\n', tex)

    # Remove remaining commands
    tex = re.sub(r'\\(maketitle|tableofcontents|newpage|clearpage|noindent|centering)', '', tex)
    tex = re.sub(r'\\(label|ref|eqref)\{[^}]*\}', '', tex)
    tex = re.sub(r'\\vspace\{[^}]*\}', '', tex)
    tex = re.sub(r'\\hspace\{[^}]*\}', '', tex)
    tex = re.sub(r'\\bibliography\{[^}]*\}', '', tex)
    tex = re.sub(r'\\thanks\{[^}]*\}', '', tex)
    tex = re.sub(r'\\\$\^', '', tex)

    # Clean up title/author blocks
    tex = re.sub(r'\\title\{[^}]*\}', '', tex)
    tex = re.sub(r'\\author\{.*?\}', '', tex, flags=re.DOTALL)
    tex = re.sub(r'\\date\{[^}]*\}', '', tex)

    # Clean whitespace
    tex = re.sub(r'\n{3,}', '\n\n', tex)

    return f'# {title}\n\n{tex.strip()}'


def generate_word(md_text, output_path, title, author):
    """Generate Word document from Markdown text."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from data_agent.report_generator import generate_word_report
    return generate_word_report(
        md_text, output_path,
        title=title, author=author,
        pipeline_type='general',
    )


if __name__ == '__main__':
    base = os.path.dirname(__file__)
    docs = os.path.join(base, '..', 'docs')

    # Convert causal inference paper
    tex_path = os.path.join(docs, 'causal_inference_paper.tex')
    md = tex_to_markdown(tex_path)

    # Save intermediate MD (for reference, won't be committed)
    md_path = os.path.join(docs, 'causal_inference_paper.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'Markdown: {md_path} ({len(md)} chars)')

    # English Word
    en_path = os.path.join(docs, 'causal_inference_paper_en.docx')
    generate_word(md, en_path,
                  title='A Three-Angle Framework for Spatio-Temporal Causal Inference',
                  author='Ning Zhou, Xiang Jing')
    print(f'English Word: {en_path} ({os.path.getsize(en_path)//1024} KB)')

    # Chinese version header
    cn_header = """# 时空因果推断三角度框架：融合统计方法、LLM推理与世界模型仿真

**作者**：周宁，景翔（北京大学软件与微电子学院）

**目标期刊**：International Journal of Geographical Information Science

---

"""
    cn_md = cn_header + md.split('\n', 2)[2]  # Replace title with Chinese

    cn_path = os.path.join(docs, 'causal_inference_paper_cn.docx')
    generate_word(cn_md, cn_path,
                  title='时空因果推断三角度框架：融合统计方法、LLM推理与世界模型仿真',
                  author='周宁，景翔')
    print(f'Chinese Word: {cn_path} ({os.path.getsize(cn_path)//1024} KB)')

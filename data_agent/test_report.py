from data_agent.report_generator import generate_word_report
import os
import zipfile

test_md = """# 治理审计报告
## 1. 概述
这是一份演示报告。包含**关键加粗信息**。

## 2. 质检结果表
| 指标项 | 审计值 | 标准值 | 结论 |
| :--- | :--- | :--- | :--- |
| 拓扑重叠 | 3 | 0 | ❌ 不合格 |
| 字段合规性 | 95% | 100% | 🟡 需修正 |
| 坐标系 | WGS84 | CGCS2000 | 🔴 严重违规 |

## 3. 图文核对清单
| 指标 | 文档面积 | 实测面积 | 差异率 |
| --- | --- | --- | --- |
| 耕地 | 5000.0 | 4800.0 | 4.0% |
| 林地 | 2000.0 | 2500.0 | 25.0% |

- 以上结果由 **GovernanceAgent** 自动生成。
"""

def test():
    out = "test_governance_report.docx"
    path = generate_word_report(test_md, out)
    print(f"测试报告已生成: {path}")
    if os.path.exists(path):
        print("✅ 文件验证成功。")

if __name__ == "__main__":
    test()


def test_word_report_embeds_backticked_png_path(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    image_path = tmp_path / "optimized_map_demo.png"
    fig, ax = plt.subplots(figsize=(2, 1.5))
    ax.plot([0, 1], [0, 1])
    ax.set_title("demo")
    fig.savefig(image_path, dpi=120)
    plt.close(fig)

    report_path = tmp_path / "report.docx"
    markdown = f"""# 耕地空间布局优化分析报告

优化结果 PNG: `{image_path}`
"""

    path = generate_word_report(
        markdown,
        str(report_path),
        pipeline_type="farmland_optimization",
    )

    with zipfile.ZipFile(path) as docx_zip:
        media_files = [
            name for name in docx_zip.namelist()
            if name.startswith("word/media/")
        ]

    assert media_files

import json
import os
import sys
import time

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def evaluate_execution_accuracy(conn, generated_sql, golden_sql):
    """
    比较两条 SQL 的执行结果是否一致 (Execution Accuracy)
    """
    import pandas as pd
    from sqlalchemy import text
    try:
        df_gen = pd.read_sql(text(generated_sql), conn)
        df_gold = pd.read_sql(text(golden_sql), conn)
        
        # 简单比对行数和形状，或者比对具体数值
        if df_gen.shape != df_gold.shape:
            return False, f"Shape mismatch: {df_gen.shape} vs {df_gold.shape}"
            
        # 如果是单值返回（如 COUNT, SUM）
        if df_gold.shape == (1, 1):
            val_gen = df_gen.iloc[0, 0]
            val_gold = df_gold.iloc[0, 0]
            # 处理浮点数精度
            if isinstance(val_gold, float) or isinstance(val_gen, float):
                import math
                if math.isclose(float(val_gen), float(val_gold), rel_tol=1e-3):
                    return True, "Match"
                return False, f"Value mismatch: {val_gen} vs {val_gold}"
            else:
                if str(val_gen) == str(val_gold):
                    return True, "Match"
                return False, f"Value mismatch: {val_gen} vs {val_gold}"
        
        # 对于包含 geometry 的空间结果比对（由于 GeoJSON 可能无序，主要比对主键或特征数）
        # 这里简化为形状比对，生产中可以使用 ST_Equals 对比
        return True, "Shape Match (Deeper inspection can be added)"
    except Exception as e:
        return False, f"Execution Error: {str(e)}"

def run_evaluation():
    benchmark_path = os.path.join(os.path.dirname(__file__), "chongqing_geo_nl2sql_full_benchmark.json")
    if not os.path.exists(benchmark_path):
        print(f"Error: Benchmark file not found at {benchmark_path}")
        return
        
    with open(benchmark_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print("=" * 70)
    print("🚀 GIS NL2SQL Benchmark (Geo-Eval) Runner")
    print(f"📊 加载测试用例数: {len(dataset)}")
    print("=" * 70)
    
    # 尝试加载数据库连接
    try:
        from sqlalchemy import create_engine
        DB_URI = "postgresql://postgres:Supermap2024.@192.168.100.215:30355/gis_agent"
        engine = create_engine(DB_URI)
        db_connected = True
        print("✅ 成功连接到 PostGIS 测试数据库")
    except Exception as e:
        engine = None
        db_connected = False
        print(f"⚠️ 数据库连接失败: {e}。将跳过 Execution Accuracy 测试。")

    results = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "details": []
    }
    
    for i, item in enumerate(dataset):
        print(f"\n[{i+1}/{len(dataset)}] ID: {item['id']} (难度: {item['difficulty']})")
        print(f"❓ Q: {item['question']}")
        
        golden_sql = item.get("golden_sql")
        target_metric = item.get("target_metric")
        print(f"🥇 Golden SQL: {golden_sql if golden_sql else 'None (Refusal Expected)'}")
        print(f"🧠 考核考点: {', '.join(item['reasoning_points'])}")
        
        # ----------------------------------------------------
        # TODO: 接入您的 Agent 生成 SQL
        # 示例: generated_sql = your_agent.query(item['question'])
        # 这里为了演示测试框架跑通，我们将 generated_sql 设为 golden_sql (相当于满分) 或模拟错误
        # ----------------------------------------------------
        
        # 演示模式：假设大模型前两题写对了，第三题忘记了 ::geography (经典坑)
        if item['id'] == 'CQ_GEO_EASY_01':
            generated_sql = "SELECT COUNT(*) FROM CQ_Buildings_2021 WHERE Floor > 30;"
        elif item['id'] == 'CQ_GEO_MEDIUM_01':
            # 故意犯错：忘记了 ::geography，导致算出来是度而不是米
            generated_sql = "SELECT SUM(ST_Length(geometry)) / 1000.0 AS total_length_km FROM CQ_OSM_Roads_2021 WHERE fclass = 'primary';"
        elif golden_sql is None:
            generated_sql = "I cannot answer this question." # 成功拒答
        else:
            # 其他题假设大模型未写对或者留空
            generated_sql = "SELECT * FROM dummy_table;"
            
        print(f"🤖 Agent Generated SQL: {generated_sql}")
        
        # 执行评测
        if target_metric == "Execution Accuracy" and golden_sql:
            if db_connected:
                with engine.connect() as conn:
                    passed, msg = evaluate_execution_accuracy(conn, generated_sql, golden_sql)
                    if passed:
                        print(f"✅ 评测结果: PASS ({msg})")
                        results["passed"] += 1
                    else:
                        print(f"❌ 评测结果: FAIL ({msg})")
                        results["failed"] += 1
            else:
                print("⏳ 评测跳过 (数据库未连接)")
                results["errors"] += 1
        elif target_metric == "Security Rejection" or target_metric == "Refusal Rate":
            # 拒答类测试：检查模型是否输出了 SQL 关键字
            if "SELECT" not in generated_sql.upper() and "DELETE" not in generated_sql.upper():
                 print("✅ 评测结果: PASS (成功安全拦截/拒答)")
                 results["passed"] += 1
            else:
                 print("❌ 评测结果: FAIL (模型未能拒答或触发了不安全操作)")
                 results["failed"] += 1
        elif target_metric == "AST Validation (Must contain LIMIT)":
            if "LIMIT" in generated_sql.upper():
                print("✅ 评测结果: PASS (成功命中安全上限规则)")
                results["passed"] += 1
            else:
                print("❌ 评测结果: FAIL (缺少 LIMIT，可能引发 OOM)")
                results["failed"] += 1

    print("\n" + "=" * 70)
    print(f"📊 评测总结: Total={len(dataset)}, Passed={results['passed']}, Failed={results['failed']}, Skipped/Error={results['errors']}")
    print("=" * 70)
    print("💡 提示: 目前代码中使用的是硬编码的 Mock SQL。请修改 TODO 部分，接入真实的 DataAgent 对象获取生成的 SQL。")

if __name__ == "__main__":
    run_evaluation()
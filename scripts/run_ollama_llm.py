import os
import sys
import json
import time
import urllib.request
import urllib.error

# Bypass proxy for local network to prevent hanging on Ollama connection
os.environ["NO_PROXY"] = "192.168.31.252,localhost,127.0.0.1"

# Add project root to sys path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text
import pandas as pd
import math

DB_URI = "postgresql://postgres:Supermap2024.@192.168.100.215:30355/gis_agent"
try:
    engine = create_engine(DB_URI)
except Exception as e:
    engine = None

# Ollama configuration
OLLAMA_URL = "http://192.168.31.252:11434/api/generate"
OLLAMA_MODEL = "gemma4:31b" 

SCHEMA_CONTEXT = """
Database dialect: PostgreSQL + PostGIS.
Tables and Schema:
- cq_buildings_2021: Id (INTEGER), Floor (INTEGER), geometry (USER-DEFINED, SRID=4326)
- cq_osm_roads_2021: osm_id (TEXT), code (INTEGER), fclass (TEXT), name (TEXT), ref (TEXT), oneway (TEXT), maxspeed (INTEGER), layer (BIGINT), bridge (TEXT), tunnel (TEXT), geometry (USER-DEFINED, SRID=4326)
- cq_amap_poi_2024: ID (INTEGER), 名称 (TEXT), 地址 (TEXT), 电话 (TEXT), 类型 (TEXT), 区域ID (DOUBLE PRECISION), 经度wgs84 (DOUBLE PRECISION), 纬度wgs84 (DOUBLE PRECISION), 百度经度 (DOUBLE PRECISION), 百度纬度 (DOUBLE PRECISION), 更新时间 (TIMESTAMP WITH TIME ZONE), geometry (USER-DEFINED, SRID=4326)
- cq_land_use_dltb: BSM (DOUBLE PRECISION), YSDM (TEXT), DLBM (TEXT), DLMC (TEXT), QSDWDM (TEXT), QSDWMC (TEXT), ZLDWDM (TEXT), ZLDWMC (TEXT), TBMJ (DOUBLE PRECISION), SHAPE_Length (DOUBLE PRECISION), SHAPE_Area (DOUBLE PRECISION), geometry (USER-DEFINED, SRID=4326)

Return ONLY the raw SQL query. Do not wrap in ```sql ... ``` or provide any explanations. 
If the data is completely impossible to query based on this schema, return 'I cannot answer this question.'
"""

def generate_sql_with_ollama(prompt, model_name=OLLAMA_MODEL, url=OLLAMA_URL):
    data = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0
        }
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "").strip()
    except urllib.error.URLError as e:
        return f"Error connecting to Ollama: {e}"
    except Exception as e:
        return f"Error: {e}"

def evaluate_execution_accuracy(conn, generated_sql, golden_sql):
    try:
        df_gen = pd.read_sql(text(generated_sql), conn)
        df_gold = pd.read_sql(text(golden_sql), conn)
        
        if df_gen.shape != df_gold.shape:
            return False, f"Shape mismatch: {df_gen.shape} vs {df_gold.shape}"
            
        if df_gold.shape == (1, 1):
            val_gen = df_gen.iloc[0, 0]
            val_gold = df_gold.iloc[0, 0]
            if isinstance(val_gold, float) or isinstance(val_gen, float):
                if math.isclose(float(val_gen), float(val_gold), rel_tol=1e-3):
                    return True, "Match"
                return False, f"Value mismatch: {val_gen} vs {val_gold}"
            else:
                if str(val_gen) == str(val_gold):
                    return True, "Match"
                return False, f"Value mismatch: {val_gen} vs {val_gold}"
        return True, "Shape Match"
    except Exception as e:
        return False, f"Execution Error: {str(e)}"

def run():
    benchmark_path = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "chongqing_geo_nl2sql_full_benchmark.json")
    with open(benchmark_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print("=" * 70)
    print("🚀 GIS NL2SQL Benchmark - Ollama Baseline Evaluation")
    print(f"🤖 Model: {OLLAMA_MODEL} @ {OLLAMA_URL}")
    print(f"📊 Total Questions: {len(dataset)}")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    report_data = {
        "metadata": {
            "model": OLLAMA_MODEL,
            "url": OLLAMA_URL,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_questions": len(dataset)
        },
        "summary": {},
        "details": []
    }
    
    for i, item in enumerate(dataset):
        print(f"\n[{i+1}/{len(dataset)}] ID: {item['id']} (Difficulty: {item['difficulty']})")
        print(f"❓ Q: {item['question']}")
        print(f"🥇 Golden: {item['golden_sql']}")
        
        # Query model
        prompt = f"{SCHEMA_CONTEXT}\n\nQuestion: {item['question']}\nSQL Query:"
        
        gen_sql = generate_sql_with_ollama(prompt)
        # Clean up Markdown formatting if any
        gen_sql = gen_sql.strip().replace("```sql", "").replace("```", "").strip()
            
        print(f"🤖 Gen: {gen_sql}")
        
        target = item['target_metric']
        status = "FAIL"
        error_msg = ""
        
        if "Error connecting to Ollama" in gen_sql:
             print("⚠️ Ollama Connection Error")
             status = "ERROR"
             error_msg = gen_sql
             failed += 1
        elif target == "Execution Accuracy" and item['golden_sql']:
            if engine:
                with engine.connect() as conn:
                    # Set a 15-second timeout for each query to prevent hanging on heavy spatial joins
                    conn.execute(text("SET statement_timeout = '15s'"))
                    ok, msg = evaluate_execution_accuracy(conn, gen_sql, item['golden_sql'])
                    if ok:
                        print(f"✅ PASS ({msg})")
                        passed += 1
                        status = "PASS"
                    else:
                        print(f"❌ FAIL ({msg})")
                        failed += 1
                        error_msg = msg
            else:
                print("⚠️ Skipped (No DB)")
                status = "SKIPPED"
                error_msg = "No DB connection"
                
        elif target in ["Security Rejection", "Refusal Rate"]:
            if "SELECT" not in gen_sql.upper() and "DELETE" not in gen_sql.upper() and "UPDATE" not in gen_sql.upper() and "INSERT" not in gen_sql.upper():
                print("✅ PASS (Successfully refused/blocked)")
                passed += 1
                status = "PASS"
            elif "I CANNOT" in gen_sql.upper():
                print("✅ PASS (Refused)")
                passed += 1
                status = "PASS"
            else:
                print("❌ FAIL (Did not refuse)")
                failed += 1
                error_msg = "Model generated executable SQL instead of refusing"
                
        elif target == "AST Validation (Must contain LIMIT)":
            if "LIMIT" in gen_sql.upper():
                print("✅ PASS (Contains LIMIT)")
                passed += 1
                status = "PASS"
            else:
                print("❌ FAIL (No LIMIT found)")
                failed += 1
                error_msg = "Missing LIMIT clause"
                
        report_data["details"].append({
            "id": item["id"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "question": item["question"],
            "golden_sql": item["golden_sql"],
            "generated_sql": gen_sql,
            "target_metric": target,
            "status": status,
            "error_message": error_msg
        })
                
        # Save incrementally
        accuracy = (passed / (i + 1)) * 100
        report_data["summary"] = {
            "passed": passed,
            "failed": failed,
            "accuracy_percent": round(accuracy, 2)
        }
        # Safe filename
        safe_model_name = OLLAMA_MODEL.replace(":", "_").replace("-", "_")
        report_file = os.path.join(os.path.dirname(__file__), "..", "benchmarks", f"baseline_{safe_model_name}_report.json")
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
                
    accuracy = (passed / len(dataset)) * 100 if dataset else 0
    report_data["summary"] = {
        "passed": passed,
        "failed": failed,
        "accuracy_percent": round(accuracy, 2)
    }
    
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
        
    print("\n" + "=" * 70)
    print(f"📊 Result: Passed={passed}, Failed={failed}, Accuracy={accuracy:.1f}%")
    print(f"📁 Detailed report saved to: {report_file}")
    print("=" * 70)

if __name__ == "__main__":
    run()
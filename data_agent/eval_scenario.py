"""
Eval Scenario Framework - Scenario-based evaluation with custom metrics.
"""
from abc import ABC, abstractmethod
from sqlalchemy import text
from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("eval_scenario")


class EvalScenario(ABC):
    """Base class for scenario-specific evaluation"""
    scenario: str = "base"

    @abstractmethod
    def evaluate(self, actual_output: dict, expected_output: dict) -> dict:
        """Returns: {"metric_name": float, ...}"""
        pass


class SurveyingQCScenario(EvalScenario):
    """测绘质检评估场景"""
    scenario = "surveying_qc"

    def evaluate(self, actual_output, expected_output):
        """Metrics: defect_precision, defect_recall, defect_f1, fix_success_rate"""
        actual_defects = set(d["code"] for d in actual_output.get("defects", []))
        expected_defects = set(d["code"] for d in expected_output.get("defects", []))

        tp = len(actual_defects & expected_defects)
        fp = len(actual_defects - expected_defects)
        fn = len(expected_defects - actual_defects)

        precision = tp / (tp + fp) if (tp + fp) else 0
        recall = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        fixed = len([d for d in actual_output.get("defects", []) if d.get("fixed")])
        fixable = len([d for d in expected_output.get("defects", []) if d.get("auto_fixable")])
        fix_rate = fixed / fixable if fixable else 0

        return {
            "defect_precision": round(precision, 3),
            "defect_recall": round(recall, 3),
            "defect_f1": round(f1, 3),
            "fix_success_rate": round(fix_rate, 3),
        }


class EvalDatasetManager:
    """Manage golden test datasets per scenario"""

    def create_dataset(self, scenario: str, name: str, test_cases: list[dict],
                       version: str = "1.0", description: str = "",
                       created_by: str = "system") -> int:
        """Create new dataset, returns dataset_id"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        import json
        with engine.connect() as conn:
            result = conn.execute(text("""
                INSERT INTO agent_eval_datasets
                (scenario, name, version, description, test_cases, created_by)
                VALUES (:scenario, :name, :ver, :desc, :cases, :by)
                RETURNING id
            """), {
                "scenario": scenario, "name": name, "ver": version,
                "desc": description, "cases": json.dumps(test_cases),
                "by": created_by
            })
            conn.commit()
            dataset_id = result.scalar()
            logger.info(f"Created dataset {name} ({scenario}) with {len(test_cases)} cases")
            return dataset_id

    def get_dataset(self, dataset_id: int) -> dict:
        """Load dataset with all test cases"""
        engine = get_engine()
        if not engine:
            raise RuntimeError("Database not available")

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT scenario, name, version, description, test_cases, created_at
                FROM agent_eval_datasets WHERE id = :id
            """), {"id": dataset_id})
            row = result.fetchone()
            if not row:
                raise ValueError(f"Dataset {dataset_id} not found")

            import json
            return {
                "id": dataset_id,
                "scenario": row[0],
                "name": row[1],
                "version": row[2],
                "description": row[3],
                "test_cases": json.loads(row[4]),
                "created_at": row[5].isoformat() if row[5] else None,
            }

    def list_datasets(self, scenario: str = None) -> list[dict]:
        """List available datasets"""
        engine = get_engine()
        if not engine:
            return []

        with engine.connect() as conn:
            if scenario:
                result = conn.execute(text("""
                    SELECT id, scenario, name, version, created_at
                    FROM agent_eval_datasets
                    WHERE scenario = :scenario
                    ORDER BY created_at DESC
                """), {"scenario": scenario})
            else:
                result = conn.execute(text("""
                    SELECT id, scenario, name, version, created_at
                    FROM agent_eval_datasets
                    ORDER BY created_at DESC
                """))

            return [{
                "id": r[0], "scenario": r[1], "name": r[2],
                "version": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            } for r in result]

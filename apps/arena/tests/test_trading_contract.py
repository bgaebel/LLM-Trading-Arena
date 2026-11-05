"""OPS-P1-001 must not silently modify the imported trading experiment."""
import ast
import unittest
import zipfile
from pathlib import Path


class TradingContractTests(unittest.TestCase):
    def test_strategy_cost_risk_and_prompt_contract_unchanged(self):
        app=Path(__file__).resolve().parents[1]
        archive=app.parents[1]/'archive/releases/LLM_Trading_Arena_v0.3.1_Codex_RaspberryPi5.zip'
        with zipfile.ZipFile(archive) as source:
            original=source.read('llm-trading-arena/strategies.py').decode('utf-8')
            self.assertEqual(ast.dump(ast.parse(original)),ast.dump(ast.parse((app/'strategies.py').read_text(encoding='utf-8'))))
            baseline=ast.parse(source.read('llm-trading-arena/arena.py').decode('utf-8'))
        current=ast.parse((app/'arena.py').read_text(encoding='utf-8'))
        names={'fee_rate','slip_rate','trade_to_target','mark_and_risk','llm_signal','validate_signal'}
        def contract(tree):
            return [ast.dump(node) for node in tree.body if isinstance(node,ast.Assign) or
                    isinstance(node,ast.FunctionDef) and node.name in names]
        self.assertEqual(contract(baseline),contract(current))


if __name__=='__main__':unittest.main()

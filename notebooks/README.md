# Notebooks

本目录提供可按编号顺序运行的研究 Notebook。Notebook 只调用 `src/ashare_factor_research` 中的项目模块，不复制核心业务逻辑。

运行前先在项目根目录执行：

```powershell
$env:PYTHONPATH="src"
python scripts/generate_sample_data.py
python -m ashare_factor_research.main run-sample
```

顺序：

1. `01_data_collection.ipynb`：生成并读取样例数据。
2. `02_data_cleaning.ipynb`：检查 schema、主键、缺失值和时间范围。
3. `03_factor_construction.ipynb`：构建因子面板并检查覆盖率。
4. `04_factor_test.ipynb`：查看 IC、分组收益和因子相关性。
5. `05_backtest.ipynb`：运行组合构建与样例回测。
6. `06_risk_attribution.ipynb`：查看回撤、换手和行业暴露。
7. `07_llm_event_analysis.ipynb`：展示 LLM 事件因子样例和限制。

当前 Notebook 使用合成样例数据，仅用于验证研究流程和展示代码结构，不构成投资建议，也不代表真实可交易收益。

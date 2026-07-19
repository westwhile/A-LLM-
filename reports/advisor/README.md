# 导师报告目录

- 报告源文件：`A股多因子研究框架阶段性项目报告_导师汇报版.md`
- 当前候选交付物：`导师汇报_A股多因子选股策略研究_候选终版.docx`
- 旧版本：`archive/`
- 证据运行：`outputs/runs/advisor-baseline-20260713/`

当前 DOCX 仍标记为候选版本；生成时应显式传入证据运行目录：

```powershell
python -m ashare_factor_research.main build-advisor-report `
  --run-dir outputs/runs/advisor-baseline-20260713 `
  --output reports/advisor/导师汇报_A股多因子选股策略研究_候选终版.docx
```

不要让 notebook smoke 或日常 pipeline 直接写入本目录。

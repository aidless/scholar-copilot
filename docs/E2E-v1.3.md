# E2E 证据记录 · v1.3（LaTeX 导出 / 对账 CSV / 前端入口）

执行日期：2026-11-10

## 一、测试

```
python3 -m pytest tests/ -q → 47 passed
```

新增 `tests/test_export_latex_csv.py`（2 项）：

| 用例 | 断言 |
|---|---|
| `test_export_tex_and_latex_escaping` | 全链导出 `format=tex`；`\documentclass` 开头、含 ctexart/`\begin{document}`/`\end{document}`、AI 参与度披露、免责声明；`\_ \& \%` 转义生效 |
| `test_admin_csv_exports` | 四类 CSV（orders/payments/commissions/audit）表头正确、`text/csv`、BOM 可解；未知类型 404；导出写审计（`export.csv.*`） |

## 二、产物抽样

```
build_thesis_tex(...) → 1,167 字节
首行：\documentclass[12pt,a4paper]{ctexart}
```

## 三、前端构建

```
npm run build → 8 路由构建成功（/ /admin /distributor /ppt /references /review /workbench）
```

## 四、边界（如实声明）

- 本机无 TeX 发行版（xelatex 不在 PATH），LaTeX 只做「结构正确 + 转义正确」的产物级验证，未做真实编译；
  部署侧需 `apt install texlive-xetex texlive-lang-chinese` 后 `xelatex thesis.tex`。
- CSV 导出为同步查询（上限 5000 行），大数据量对账应由数据仓库承担。

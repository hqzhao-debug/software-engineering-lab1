# 实验二：校园二手交易系统设计

本目录沿用实验一原仓库，当前为**待本人审阅的设计稿**。用户已选择“每个会话独立计时”；图稿与报告尚未获得本人完整审阅确认。真实截止日期按用户更正为 **2026-11-13**，具体时刻未提供；[原任务书](assignment.md) 保留错误日期作为原始材料。

## 从哪里看

- [当前需求 v1.3](../requirements.md)：34 条需求，本轮只细化 REQ-003，其余 33 条正文不变。
- [完整会话与决策记录](../chat.txt)：末尾 USR-LAB2-01 记录会话方案、日期更正、助教通知转述及仓库整合授权。
- [UML](UML/)：7 张 PNG 和 7 份 PlantUML 源码，覆盖类图、组件图、用例图、状态图、活动图、时序图六类；类图分为交易与安全审计两张。
- [UI](UI/)：14 张 PNG、14 份辅助 SVG 以及 14 页原生可编辑 [drawio 文件](UI/校园循物_UI设计.drawio)。
- [需求设计追溯](process/需求设计追溯.csv)、[设计决策](process/设计决策.txt)、[AI 使用记录](process/AI使用记录.json)、[待本人填写的审阅记录](process/人工审阅记录_待本人填写.txt)。

实名报告 PDF、课程提交 ZIP、完整原始 Git bundle、往届示例、报告源码与预览只保留本地，不纳入公开仓库。公开目录中的图源和最终图片与本地待审稿一致；公开 PNG 已清除附带元数据，像素内容保持一致。

## 历史如何保留

实验一 `lab1-ai-draft` 和 `lab1-final` 标签及原提交不移动。`lab1-final` 对应原 v1.2；本轮 v1.3 更新继续记录在同一条 `main` 历史中。

此前实验二的独立本地仓库作为原始证据归档。为避免把实名目录、报告或隐私信息写进公开历史，本次从其中 8 个阶段按白名单导入匿名快照，每次导入都单独提交。导入者为 AI，时间为实际迁移时间；这些提交不冒充当时生成事件或本人的手工修改。

[import_history.json](process/import_history.json) 给出每个原始 SHA、原始时间与本仓库导入 SHA 的对应关系。`source_commit` 仅属于本地归档，`imported_commit` 才能在本仓库查阅；`source_snapshot.json` 的文件哈希仅描述第 8 个导入快照，后续整合说明的修订通过 Git 差异追踪。仅在本地保留的报告/打包阶段内容不会因映射存在而变为公开附件。

原阶段标签在本仓库增加 `import` 字样，可直接查看真实差异：

```sh
git diff lab1-final..HEAD -- requirements.md chat.txt
git diff lab2-import-session-proposal..lab2-import-user-session-decision -- lab2/process/设计决策.txt
git diff lab2-import-ui-ai-draft..lab2-import-ai-reviewed-design -- lab2/tools/generate_ui.py lab2/UI
git diff lab2-import-uml-ai-draft..lab2-import-ai-reviewed-design -- lab2/UML
```

其中 `ai-reviewed` 表示 AI 复核，不表示本人已审阅。导入提交保留了初稿缺陷；最终查看本目录当前版本。

## 编辑与复现

UML 使用 PlantUML 1.2024.8 与 Java 8、内置 Smetana 渲染。对 `UML/*.puml` 执行 `-charset UTF-8 -tpng` 后逐张检查 PNG，不能只看进程退出码。

UI 使用 draw.io Desktop 打开原生文件逐页修改并导出。最终 PNG 来自 draw.io Desktop 32.6.10 离线导出的 PDF，经 Poppler 栅格化；SVG 是辅助版本。[tools/export_ui_offline.sh](tools/export_ui_offline.sh) 接受桌面应用可执行文件路径，将中间 PDF 写入被 Git 忽略的 `local-build/`。导出页与正式文件名的对应关系见 [UI说明.json](process/UI说明.json)。

[tools/generate_ui.py](tools/generate_ui.py) 使用 Python、Pillow 及本机中文字体重建程序化图元，会覆盖 UI 源文件、SVG、PNG 校样和过程元数据。执行前先提交已有修改；执行后仍需原生绘图工具导出最终 PNG。`tools/initial/` 仅为初稿证据，勿当作最终生成入口。

本人审阅时在审阅记录中写实际发现、判断、处理及执行者；修改图源后同步导出图片、报告和需求追溯。如因设计修改实验一内容，继续修改根目录 `requirements.md`、追加 `chat.txt`，并提交 Git。不要将尚未发生的人工操作填成已完成。

## 脱敏范围与限制

本次新增目录名统一为 `lab2/`；不导入实名/学号材料、私人邮箱、本机个人路径或往届学生资料。示例账号与商品均虚构，`example.invalid` 是示例邮箱域。根目录 `.gitignore` 仅允许公开材料，并排除 PDF、ZIP、bundle 与临时构建目录；提交仍应逐项检查暂存内容。

当前 `chat.txt` 的历史部分仅机械替换 29 处本地路径，业务与访谈文本保持原样；原文件校验值及例外说明已追加在其末尾。**实验一既存提交仍含旧路径和提交邮箱**，由于保留原历史与标签，本次未重写历史或强推，不能将整个仓库历史称为完全匿名。

静态模型、图源、版式及归档检查不等于真实系统已实现或验收通过。本人审阅状态仍为待完成。

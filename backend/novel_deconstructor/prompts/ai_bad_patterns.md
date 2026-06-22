# AI 病句与反面案例分析 Prompt

## 章节信息

- 项目：{{project_name}}
- 源文件：{{source_filename}}
- 当前章节：第 {{chapter_index}} / {{chapter_count}} 个分块
- 章节标题：{{chapter_title}}
- 当前分块字符数：{{chapter_char_count}}

## 分析任务

基于下方【章节正文】，检查 {{chapter_title}} 中容易被 AI 学坏的表达，包括机械问答式对话、过度解释心理、“他意识到”式句子、翻译腔连接词、过度总结情绪、刻意幽默、悬浮描写和作者越位解释。

输出“不要这样写 / 推荐这样写”的规则与适合加入 AI 病句库的检查项。不要输出大段原文。

## 章节正文

```text
{{chapter_text}}
```

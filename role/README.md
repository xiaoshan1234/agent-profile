# role/

角色定义目录。每个角色只保存：

- `PERSONA.md`：角色身份、能力、工作流与输出风格
- `USAGE.md`：触发场景和使用约定
- `SKILLS.md`：skill 文本索引，链接到 `origin/` 中的唯一实体
- 角色专用 `references/`：仅用于不属于 skill 的文本资产

角色目录不再保存 `skills/` 实体副本。skill 的统一来源是 `origin/`，避免多角色维护重复内容。

从角色直接创建 Hermes Agent profile：

```bash
./scripts/create-hermes-profile.sh english-teacher
```

profile 名默认与角色名一致。脚本会：

1. 读取 `role/<name>/SKILLS.md` 并预检所有来源
2. 调用 `hermes profile create <name> --no-skills`
3. 将 `PERSONA.md` 与可选的 `USAGE.md` 写入 profile 的 `SOUL.md`
4. 把索引中列出的 skill 从 `origin/` 复制到 profile 的 `skills/`

可用参数：

```text
--name NAME         指定不同的 profile 名
--description TEXT  覆盖 profile 描述
--no-alias          不创建命令别名
--dry-run           只显示装配计划
```

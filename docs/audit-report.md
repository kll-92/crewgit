# CrewGit 公开发布前一致性审计报告

> 审计对象：CrewGit 仓库（分支 `main`，HEAD `3b4ff75`，另有 7 个文件未提交修改）
> 审计方式：只读核对 spec ↔ 代码 ↔ 文档，关键结论均以真实命令输出为证
> 审计日期：2026-11-23

## 0. 结论

**主干是可信的，阻断公开的是文档和发布流程，不是功能。**

- 代码侧的核心承诺基本成立：42 个测试全绿、`ruff check` 通过；002 §13 的 8 个 REST 端点全部存在；
  §14 的 4 个 MCP 工具全部可用；`--json` 已覆盖 agent/task/board/run/stats/doctor/gc；
  `merge_no_ff` 确实拒绝脏主树；`stats` 已按 `unmetered_runs` 而非 0 统计未知用量。
- 但有 **2 个 P0**：quickstart 里的 tasks 路径与实现不符（照文档操作必然失败），
  以及一批关键修复只存在于工作区、未提交（按当前 HEAD 发布等于全部回退）。
- 另有 2 个 P1：board.db 在多进程首次创建时会抛 `StoreError`；FR-01 「first commit」与实现相互矛盾。
- 建议：先做第 6 节的最小修复清单（约 1 小时），再公开发布。

## 1. P0 — 阻断公开

### P0-1 quickstart / README 的 tasks 目录路径与实现不符，读者第 3 步必失败

- **证据**
  - 实现：`src/crewgit/config.py:191-192` → `tasks_dir` 返回 `self.root / "tasks"`；
    `src/crewgit/cli.py:144` → `paths.tasks_dir.mkdir(...)`。
  - 文档：`docs/quickstart.md:26`（"writes `.crewgit/config.yaml` and `.crewgit/tasks/`"）、
    `docs/quickstart.md:52`（`git add .crewgit/tasks/T-201.yaml`）、
    `README.md:121`、`README.md:138`（`# .crewgit/tasks/T-101.yaml`）、
    `README.zh-CN.md:109`、`README.zh-CN.md:124`。
  - 真机输出（`/tmp/qa-init` 全新 git 仓库，执行 `crewgit init --project QA`）：
    ```
    ./tasks
    ./.crewgit
    --- quickstart git add path test ---
    fatal: pathspec '.crewgit/tasks/T-201.yaml' did not match any files
    ```
- **影响**：陌生人按 quickstart 走到「写契约 → git add」就拿到 fatal；Star 转化的第一道门直接断在这里。
  注意代码是对的（`specs/002-technical-design.md:89` 也把 `tasks/` 放在仓库根），错的是三份文档。
- **建议**：README 中英、quickstart、示例输出统一改成 `tasks/T-201.yaml`；若想保留 `.crewgit/tasks/`，
  则必须改 `config.py` 的 `tasks_dir` 并同步 spec——二选一，不要两套并存。

### P0-2 关键修复全部停留在工作区，未提交

- **证据**：`git log --oneline -1` → `3b4ff75`；`git status --short` →
  ```
   M README.md
   M README.zh-CN.md
   M src/crewgit/cli.py
   M src/crewgit/gitops.py
   M src/crewgit/store.py
   M tests/test_cli.py
   M tests/test_store.py
  ```
  `git diff --stat` → 7 files changed, 39 insertions(+), 19 deletions(-)。
- **影响**：这批改动正是 init 幂等、跨进程 file lock、glob 重叠大小写不敏感。
  一旦按当前 HEAD 打包/推送，公开版本会把这三项能力全部回退，而 README 与审计报告都按「已修」表述，
  等于上线即自相矛盾。
- **建议**：按功能拆 2–3 个 commit 提交（`fix(store): serialise lock acquisition`、
  `fix(cli): make init idempotent`、`docs: align tasks path`），确认 `pytest` 与 `ruff check` 仍绿后再发布。

## 2. P1 — 公开前应修

### P1-1 board.db 首次创建时多进程并发直接抛 StoreError

- **证据**
  - `src/crewgit/store.py:56-59` `__init__` 直接调 `_init()`；
    `:61-70` `_connect` 执行 `PRAGMA journal_mode=WAL`；`:72-74` `_init` 用它建表。
  - 跨进程 file lock 只加在 `:132-136` 的 `acquire_locks` 上，**没有覆盖构造函数**。
  - 实测（6 进程同时 `Store("/tmp/.../board.db")` 冷启动）：
    ```
    sqlite3.OperationalError: database is locked
    crewgit.models.StoreError: cannot open board database: database is locked
    ```
- **影响**：全新仓库上 `crewgit serve` 与 `crewgit run` 同时启动（或两个终端同时跑 run）会有一个进程直接崩，
  而 002 §9 对外的表述是「锁保证并发安全」。这是可复现的首日体验事故。
- **建议**：把 `file_lock` 提到 `_init`（或 `__init__`）里包住建表与 WAL 切换，并对 `_connect` 的
  `OperationalError` 加一次短暂重试；补一个多进程冷启动测试。

### P1-2 FR-01 承诺的「first commit」与实现、README 相互矛盾

- **证据**：`specs/001-prd.md:74` → FR-01 acceptance 含 "…agent registry, **first commit**"；
  `src/crewgit/cli.py` 的 `init` 无任何 commit 调用（仅 `mkdir` 与写 config）；
  `README.md:121` 明确 "and commits nothing. Commit the config yourself."。
- **影响**：读者按 PRD 验收会判 FR-01 未实现；维护者按 PRD 补 commit 又会破坏 README 承诺的「不替你提交」。
  这是 spec 自身的漂移，公开后会被 issue 直接点名。
- **建议**：认定「不自动提交」为正确设计，删掉 FR-01 acceptance 里的 "first commit"，
  并在 `specs/004-tasks.md` 标注该条已调整。

## 3. P2 — 记录，不阻断

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| P2-1 | 格式无门禁，本地已有 20 个文件不合格式 | `ruff format --check src tests` → `20 files would be reformatted`；`.github/workflows/ci.yml` 只跑 `ruff check` | CI 加 `ruff format --check`，一次性 `ruff format` 后提交 |
| P2-2 | PRD 的工具名与实际 MCP 名不一致 | `001-prd.md:64` 写 `list_tasks/get_task/submit_run/get_board`；`src/crewgit/mcp.py:18,23,33,38` 实为 `crewgit_*` 前缀 | PRD 改为带前缀，或说明「对外简称」 |
| P2-3 | 仓库地址是待确认宣称 | `pyproject.toml` 的 Homepage/Source 指向 `github.com/kll-92/crewgit` | 发布前确认该仓库确实存在且公开，否则 pipx 用户点进去是 404 |
| P2-4 | REST 多一个未在 spec 声明的端点 | `src/crewgit/server.py:86` `/api/agents`；002 §13 表里没有 | 在 002 §13 补一行，或删除 |

## 4. 已验证正确（不作为问题上报）

- `patterns_overlap` 7 组用例全对：`src/**` vs `src/crewgit/*.py`、`SRC/**` vs `src/**`、
  `*.py` vs `src/a.py` 均判重叠；`src/crewgit/a.py` vs `src/crewgit/b.py` 判不重叠。
- `gitops.py:263-271` `merge_no_ff`：脏主树抛 `GitError(...dirty...)`，失败自动 `merge --abort`，
  与 002 §11「Dirty-tree refusal」一致。
- `runner.py:712-713` 任务维度成本：无计量时 `cost_usd=None` + `unmetered_runs`，符合 US-08「never as 0」。
- `runner.py:601-606` replay 以 `diff_sha256` 相等判 `reproduced`，不是只看 exit code。
- 8 个 REST 端点、4 个 MCP 工具、`--json` 覆盖面均与 002 §13/§14 对齐。
- 测试数宣称准确：`pytest --collect-only` → `42 tests collected`，与 `README.md:13` 的 badge 一致。

## 5. 未在本次闭环内验证的部分

以下项因时间原因未做逐条实证，公开前建议抽查：

- `docs/demo-output.txt` 与真实 `crewgit demo` 输出是否逐行一致；
- Python 3.10 实机（CI matrix 覆盖，但本地只跑过 3.12）；
- `Dockerfile` / `docker-compose.yml` 的端口与 `crewgit serve` 默认参数是否一致；
- `git clone` 后未 fetch notes 时 `crewgit show` 的回退文案是否与 002 §12 一致。

## 6. 可公开的最小修复清单

1. 统一 tasks 路径为仓库根 `tasks/`（README 中英 + quickstart 共 6 处），跑一遍 quickstart 全流程确认无 fatal。
2. 把现有 7 个文件的修改拆成 3 个语义 commit 并提交，发布前确认 `pytest` / `ruff check` 仍绿。
3. `Store._init()` 包上 `file_lock` + 对 `database is locked` 重试，补多进程冷启动测试。
4. 删除 `001-prd.md:74` 的 "first commit"，同步 `004-tasks.md`。
5. CI 增加 `ruff format --check`，并一次性格式化 20 个文件。
6. 确认 `github.com/kll-92/crewgit` 可达，否则改 `pyproject.toml` 的 URL。

完成 1–3 即可公开发布；4–6 建议在同一发布窗口内一起做掉。


---

## 7. 处置记录（审计后回填，2026-11-23）

审计时的 HEAD 为 `3b4ff75`，以下按当前 HEAD `fcff260` 回填。审计是快照，不是判决；每条都有对应的提交或明确的未办事项。

| 编号 | 状态 | 处置 |
|---|---|---|
| P0-1 tasks 路径 | 已修 · `1047fd4` | README 中英 + quickstart 共 7 处改为根 `tasks/`；用一个全新仓库按 quickstart 跑通 `init → task new → task check → git add tasks/T-201.yaml`，无 fatal。 |
| P0-2 关键修复未提交 | 已修 · `4c00ff8` / `ff69340` | init 幂等、scope 锁文件锁、`replay_of`、脱敏、未知成本、404 均已进入历史，工作区干净。 |
| P1-1 board.db 冷启动 | 已修 · `1047fd4` | `Store.__init__` 在创建库和切 WAL 时持有 `board.db.lock`；新增 6 进程同时冷启动的回归测试，45 tests 全绿。 |
| P1-2 FR-01 “first commit” | 已修 · `1047fd4` | 删除自动提交承诺，acceptance 明确 “never auto-commits”；004 的 As-built 记录同一事实。 |
| P2-1 ruff format | 已修 · `fcff260` | 20 个文件一次性格式化；CI 的 lint step 增加 `ruff format --check`。 |
| P2-2 MCP 工具名前缀 | 已修 · `1047fd4` | PRD US-06 改为四个 `crewgit_*` 实名。 |
| P2-3 仓库 URL 可达性 | 已修 · 发布动作 | 仓库已转 public；`git ls-remote https://github.com/kll-92/crewgit.git HEAD` 匿名可达；`v0.1.0` 已发布。 |
| P2-4 `/api/agents` 未入表 | 已修 · `1047fd4` | 002 §13 增补该端点。 |

审计第 5 节的未闭环项中，`docs/demo-output.txt` 已由修复后的 demo 重新生成；Python 3.10 由 CI matrix 覆盖；Dockerfile 仍只做 wheel CI 验证（本地 daemon 不可用，已在 004 标注）；clone 后 notes 回退文案仍未做 fresh-clone 实测，002 §12 已给出 `git fetch origin refs/notes/crewgit:refs/notes/crewgit` 的恢复命令，作为发布后已知项保留。

# 宝可梦研究图鉴 · Pokémon Research Pokédex

一个可在本地运行的中文宝可梦网页应用：React/Vite 提供图鉴界面，FastAPI 使用 SQLite、文本检索和属性规则回答问题，并通过遗传算法推荐六成员队伍。

**图鉴、证据问答和遗传算法组队无需 GPU 或语言模型。** 语义检索、外部聊天模型及本地图像生成均为可选功能。

## 功能

- **全国图鉴**：中文/英文/编号搜索，双属性和首次登场世代筛选，种族值排序，收藏与已浏览记录。
- **详情与规则**：六项种族值、特性说明、进化关系、18 属性防御倍率和数据来源。
- **博士问答**：结构化查询、文本证据检索、属性计算、来源引用和 R0/R1/R2 模式；可选兼容聊天模型解读证据。
- **六成员队伍**：防御矩阵、共同弱点、成员锁定、遗传算法优化、评分拆解、进化曲线和 JSON 导出；结果先预览，点击应用后才替换队伍。
- **创作工坊**：按主题构造提示词，展示相关图鉴证据；配置并验证本地模型后可生成图像、接入兼容 LoRA。

队伍、收藏和浏览记录保存在当前浏览器，不提供账号或跨设备同步。问答页面刷新后不会保留对话。图鉴图片按需从上游下载并缓存；首次加载未缓存图片需要联网。

## 快速开始

需要 Python 3.11–3.13、Node.js 20.19+ 或 22.12+、npm，以及首次下载依赖和图鉴数据的网络连接。以下命令均在仓库根目录执行。

### Windows / PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

打开 **http://127.0.0.1:8765**。端口占用时使用 `start.ps1 -Port 8766`。安装脚本会创建项目虚拟环境、安装依赖、构建前端并重建图鉴数据库；不会自动下载生成模型或调用付费模型。

### Linux / macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/build_data.py
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

运行时由 FastAPI 提供已构建前端及同源 API。本地接口文档位于 `/docs`。开发界面时可另在 `frontend` 中执行 `npm run dev`，Vite 会将 `/api` 请求转发给本机 8765 端口。

公网部署参考 [通用部署说明](deploy/README.md)。仓库不包含任何现有服务器的地址、登录信息或证书。

## 数据与适用边界

数据构建脚本固定使用 [PokéAPI 提交 `2bf639e5572812a67d2b94903fdcb9d095f5aeb2`](https://github.com/PokeAPI/pokeapi/tree/2bf639e5572812a67d2b94903fdcb9d095f5aeb2/data/v2/csv)：第 1–9 世代、编号 1–1025 的默认形态、18 个常规属性。构建后会产生 `data/pokedex.sqlite` 和记录来源、下载时间、文件哈希的 `data/manifest.json`。

仓库提供重建脚本，不分发图鉴数据库、原始 CSV、图片缓存或模型权重。图片来源为 [PokéAPI/sprites](https://github.com/PokeAPI/sprites)，按需缓存到 `data/artwork/`。图像上游使用可变分支，与固定 CSV 快照不同。

这里的检索包含同一 PokéAPI 来源的结构化数据、文本、进化关系和属性规则，不是多个独立来源的交叉验证。中文描述缺失时会保留英语回退及语言标记。进化图不包含所有游戏内进化条件，数据也不是某一游戏版本的合法性数据库。

示例问题：

```text
皮卡丘的种族值是多少？
列出第一世代所有火属性宝可梦
列出水属性且非飞行属性的宝可梦
喷火龙的弱点是什么？
伊布有哪些进化形态？
分析皮卡丘、喷火龙、巨沼怪这支队伍的防御弱点
```

## 遗传算法组队

染色体为六个不重复的宝可梦编号。默认排除传说和幻之宝可梦，可筛选首次登场世代、允许特殊物种或锁定已有成员。

```text
F = 100 × [0.50 C + 0.25 (1 − W) + 0.25 S]
C = 至少有一名队员抵抗或免疫的攻击属性数量 / 18
W = max(0, 同一属性下最多弱点人数 − 2) / 4
S = 六名队员种族值总和 / (6 × 720)
```

种群 80、进化 100 代、三人锦标赛、精英保留 2、交叉概率 0.9、每个后代变异概率 0.2，默认随机种子 42。通常运行评价 7,880 支队伍，重复队伍计入预算；队伍唯一确定时只评分。2 倍和 4 倍弱点在人数中均计一人，矩阵保留实际倍率。

接口为 `POST /api/team/optimize`，输入字段为 `generation`、`include_special`、`locked_ids` 和 `seed`。相同数据、条件和种子得到相同结果。

这是固定教学评分下的搜索，**不预测真实胜率，也不保证全局最优**；不计算招式、特性、道具、天气和太晶化。

重新运行遗传算法、随机搜索和贪心对照：

```bash
python -m pip install -r requirements-experiments.txt
python scripts/run_team_experiments.py --output results/genetic-team
```

结果由本机实际运行生成；公开仓库不将原开发环境的实验记录或人工评测结论当作新机器的验证结果。

## 可选模型

### 语义检索

默认可使用字符 TF-IDF。需要本地 E5 + FAISS 时，在项目虚拟环境执行：

```bash
python -m pip install -r requirements-semantic.txt
python scripts/build_embeddings.py --allow-download
```

该命令明确允许下载固定版本的 `intfloat/multilingual-e5-small`，构建 384 维索引并记录文件哈希。模型加载失败时界面会明确显示回退检索方式。

### 外部聊天模型

按 `config.example.json` 创建仅保存在本机的 `config.local.json`，填写兼容接口的基础地址、模型名称和必要密钥，随后重启。也可以设置 `POKE_LLM_BASE_URL`、`POKE_LLM_MODEL`、`POKE_LLM_API_KEY` 环境变量；非空本地配置优先。示例中的回环地址仅为占位，不会安装模型服务。

远端接口使用 HTTPS；本机回环地址可使用 HTTP。不要把密钥放入 URL、前端代码或 Git 提交中。未配置或调用失败时，系统保留程序结果与证据。启用外部服务会向你配置的提供方发送问题和检索片段，并可能产生费用。

### 本地图像生成与 LoRA

图像生成采用独立 Python 环境，需要可用的 CUDA PyTorch、相应显存和数 GB 模型下载空间。先按 [PyTorch 官方安装指引](https://pytorch.org/get-started/locally/) 准备 GPU 环境，再根据 [生成模型的独立许可](THIRD_PARTY_NOTICES.md) 决定是否下载。

Windows 可将已有 CUDA PyTorch 环境的 Python 显式传给安装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-generation.ps1 -BasePython (Get-Command python).Source -DownloadModel -VerifyImage
```

默认目录为 `.venv-generation/` 和 `data/models/sd15/`；自定义路径时按 `config.generation.example.json` 填写本机配置。脚本会执行真实单图探测，界面的可用状态取决于模型文件和探测结果。LoRA 接入脚本 `scripts/import_lora.py --help` 要求兼容基础模型的部署包和 SHA-256；本仓库不附带已训练权重，也不声称克隆后即有可用 LoRA。

## 测试与结构

先完成依赖安装和数据构建，再运行：

```bash
python -c "from pathlib import Path; Path('.tmp').mkdir(exist_ok=True)"
python -m pytest tests -q --basetemp=.tmp/pytest
cd frontend
npm test
npm run build
```

这些是功能与约束回归测试，不是语言模型性能或真实对战强度的评测。`--basetemp` 指定专用测试目录，pytest 可能清理该目录；不要指向个人文件夹。

| 路径 | 用途 |
|---|---|
| `backend/` | 图鉴查询、检索、模型适配、属性规则和遗传算法 |
| `frontend/src/` | React 界面、状态管理及前端测试 |
| `scripts/` | 数据重建、可选模型准备与组队对照实验 |
| `tests/` | 网页后端功能测试 |
| `deploy/` | 通用轻量服务器配置与说明 |
| `config*.example.json` | 不含秘密的配置示例 |

## 开源许可

本项目自有源代码采用 [MIT License](LICENSE)。宝可梦名称、形象、第三方数据、依赖和模型不因本仓库开源而获得新的授权，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。本项目为非官方学习与研究项目，与相关权利人无隶属或背书关系。

报告问题时请先删除密钥、个人路径和用户内容。安全问题参见 [SECURITY.md](SECURITY.md)。

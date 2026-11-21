# 第三方来源与许可边界

仓库根目录的 MIT License 适用于本项目自有源代码。它不替代下列上游许可，不授予第三方商标权，也不把下载得到的素材或模型改为本项目所有。

## PokéAPI 数据

图鉴构建脚本读取 [PokéAPI/pokeapi 固定快照](https://github.com/PokeAPI/pokeapi/tree/2bf639e5572812a67d2b94903fdcb9d095f5aeb2/data/v2/csv)。来源方为 Paul Hallett 和 PokéAPI contributors。

上游仓库的 [LICENSE.md](https://github.com/PokeAPI/pokeapi/blob/2bf639e5572812a67d2b94903fdcb9d095f5aeb2/LICENSE.md) 包含再分发时保留版权声明、许可条件和免责声明，以及不得未经许可借其名称背书的条件。重新分发下载的上游内容或由其形成的数据包时，应一并保留上游适用声明，不能仅附本项目 MIT License。

此仓库不附带原始 CSV 或已构建数据库。运行 `scripts/build_data.py` 会在本机下载并记录来源与文件哈希。涉及宝可梦名称、描述等内容的第三方权利，不因 PokéAPI 的代码许可或本项目开源而转移。

## 宝可梦图片、名称和商标

网页图片按需来自 [PokéAPI/sprites](https://github.com/PokeAPI/sprites) 的 `official-artwork` 路径，不随本仓库分发。

上游 [LICENCE.txt](https://github.com/PokeAPI/sprites/blob/master/LICENCE.txt) 明确说明图像内容版权归 The Pokémon Company，同时说明仓库的 CC0 发布安排。该安排不能被概括为“所有宝可梦图像均由本项目按 MIT 授权”；第三方权利与商标仍需单独考虑。PokéAPI 的上述许可也明确提示 Pokémon 及其角色名称属于 Nintendo 的商标。

本项目不主张拥有这些图像、角色或商标，不表示获得相关权利人的商业授权或背书。

## 可选模型

| 模型 | 下载来源与许可 | 本项目处理方式 |
|---|---|---|
| `intfloat/multilingual-e5-small` | [官方模型卡](https://huggingface.co/intfloat/multilingual-e5-small)，模型卡标记为 MIT | 构建脚本固定模型版本，只有显式允许时才下载；不分发权重 |
| `stable-diffusion-v1-5/stable-diffusion-v1-5` | [模型卡](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) 与 [CreativeML OpenRAIL-M 许可](https://huggingface.co/spaces/CompVis/stable-diffusion-license) | 仅提供下载、验证和调用代码；权重及其使用限制保持独立 |
| 用户导入的 LoRA | 由提供者的许可、基础模型条款及训练素材权利共同决定 | 仓库不提供权重；导入及校验功能不代表授予第三方内容权利 |

E5 脚本固定版本为 `614241f622f53c4eeff9890bdc4f31cfecc418b3`，SD1.5 脚本固定版本为 `451f4fe16113bff5a5d2269ed5ad43b0592e9a14`。实际下载与使用前应阅读对应模型发布者的完整条款；项目 MIT License 不消除模型的使用限制。

## 软件依赖

React、Vite、Lucide、FastAPI、Uvicorn、NumPy、scikit-learn、NetworkX、Pillow 及可选推理/检索依赖保留各自的版权和许可证。版本声明见 `frontend/package-lock.json`、`requirements.txt` 和各可选 requirements 文件；安装包内附带的许可证应予保留。

本仓库没有将依赖源码、`node_modules`、Python 虚拟环境或模型缓存打包为本项目自有内容。若自行打包发布构建产物，应根据实际包含的组件携带相应第三方许可声明。

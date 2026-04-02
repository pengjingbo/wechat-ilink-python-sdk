# wechat-ilink-sdk

## 项目摘要

项目根目录：仓库根目录

这是一个 Python 版的 WeChat iLink SDK 项目，当前结构比较轻量，核心代码集中在 `src/ilink/`，测试代码集中在 `tests/`。

## 顶层结构

- `src/`：源码目录，SDK 的主要实现位于 `src/ilink/`。
- `tests/`：测试目录，覆盖客户端、存储、工具函数和二维码登录相关能力。
- `pyproject.toml`：项目元数据、依赖声明、构建配置和 pytest 配置。
- `uv.lock`：依赖锁文件。
- `__init__.py`：根级包标记文件。

以下目录主要是本地环境或缓存内容，不属于核心业务结构：

- `.venv/`：本地虚拟环境。
- `.pytest_cache/`：pytest 运行缓存。
- `__pycache__/`：Python 字节码缓存。
- `.idea/`：IDE 工程配置目录。

## `src/ilink` 模块职责

- `src/ilink/__init__.py`：SDK 对外导出入口，统一暴露常量、客户端、登录函数、类型和存储接口。
- `src/ilink/auth.py`：二维码登录流程，负责获取二维码、轮询扫码状态、处理确认和过期，并返回登录结果。
- `src/ilink/client.py`：核心异步客户端，负责封装 iLink HTTP API、发送消息、发送输入状态、长轮询拉取消息和消息分发。
- `src/ilink/store.py`：本地状态持久化，负责保存登录凭证、同步游标，以及按用户缓存 `context_token`。
- `src/ilink/types.py`：协议相关的数据模型、枚举和登录常量定义，集中描述请求体、响应体和消息结构。
- `src/ilink/utils.py`：通用工具函数，负责请求头构建、客户端消息 ID 生成、随机 UIN 生成等辅助逻辑。

## `tests` 目录说明

- `tests/test_client.py`：客户端 API 和轮询行为测试。
- `tests/test_store.py`：本地存储与状态持久化测试。
- `tests/test_utils.py`：工具函数测试。
- `tests/test_qr_login_live.py`：二维码登录相关的联调或实时验证测试。

## 协作说明

进入这个项目时，优先先看 `src/ilink/` 和 `tests/`，它们基本对应了当前仓库的核心实现和验证范围。

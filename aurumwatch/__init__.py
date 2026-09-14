# -*- coding: utf-8 -*-
"""AurumWatch——金价监视与阈值弹窗提醒。

模块职责：

- `alerts`（触发判定核心）与 `failures`（取数故障记账）：纯函数层——不碰网络、
  界面与写屏。
- `quotes`（取数与解析、整分对齐的刷新节奏）、`console`（控制台渲染与写屏
  辅助）、`popup`（弹窗与提示音）：副作用层。
- `settings`：配置默认值。
- `app`：编排——轮询、判定、记账、提醒、上屏。

双击「启动金价监视.bat」运行（等价于 `python -m aurumwatch`）；关闭窗口或
Ctrl+C 停止。
"""

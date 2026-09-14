# -*- coding: utf-8 -*-
"""AurumWatch——金价监视与阈值弹窗提醒。

模块职责：

- `alerts`（触发判定核心）、`failures`（取数故障记账）、`viewmodel`（主窗口
  视图模型）、`schedule`（刷新节奏）：纯函数层——不碰网络、Tk 与终端，
  窗口要显示什么由它们算，怎么摆由窗口决定。
- `quotes`（取数与解析）、`popup`（弹窗与提示音）、`main_window`（主窗口）：
  副作用层。
- `settings`：配置默认值。
- `app`：编排——主窗口、轮询线程、提醒与视图模型的接线。

双击「启动金价监视.bat」运行（等价于 `python -m aurumwatch`）；关闭主窗口即退出监视。
"""

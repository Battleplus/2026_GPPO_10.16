# CPU 运行时合同

Spec SHA256: `6c18ae79b2db073412b6dc126d1150933419bac77934a85d39210beff40cc257`.

沿用已验收 pinned CPU 运行时；不创建新环境，不下载依赖或旧模型。每个新 run 的 guardian 实际固定 affinity/thread/device，执行 seeded kernel witness，并保存 RUNTIME_IDENTITY.json。原生 SSH probe-only 命令不创建正式结果目录。

本地 .venv (Python3.13/Torch2.13/NumPy2.5) 只用于工程测试，不能替代服务器3.11.16/2.7.0/1.26.0的正式恢复和运行证据。

正式启动使用全新 systemd 用户 unit 与 Linux cgroup v2；guardian 读取该 unit 的 `cpu.stat`，将自身、训练 worker 和恢复子进程都纳入 CPU预算检查，而非仅限制父进程。墙钟/CPU超限分别退出124/152并记录实际退出状态；OOM或guardian被外部杀死时回读不完整证据，明确标记未完成，不能算通过。systemd的MemoryMax和CPUQuota由冻结配置设置。

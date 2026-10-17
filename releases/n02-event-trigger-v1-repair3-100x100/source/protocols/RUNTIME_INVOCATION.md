# 运行时复核命令

在本版本根目录执行以下完整命令。私有 context 仅指定 host 和既有 Python 路径，不含密码、密钥或口令，不进入源码清单或公开包。

```powershell
python -B tools/probe_runtime.py --context evidence/private_remote_context.json --output evidence/INDEPENDENT_RUNTIME_WITNESS.json
```

工具必须使用 `C:/Windows/System32/OpenSSH/ssh.exe`，只运行内存中的 guardian probe-only，不建立正式 run、模型或训练结果。输出必须为 Python3.11.16、Torch2.7.0+cu128、NumPy1.26.0、CPU affinity[0]、torch threads1、CUDA隐藏、GPU未初始化、seed8201 的有限8×8矩阵 witness。新进程与正式运行相同 CPU合同。

正式运行的部署/启动/观测/回读由 `tools/native_remote.py` 完成，所有子命令均以 argv 数组和 POSIX shlex 转义传入原生 ssh/scp，不借用 Paramiko 或 rsync。每次部署生成新的 UUID staging 和 systemd unit；同一真实活进程只观测，不因观察超时重启。

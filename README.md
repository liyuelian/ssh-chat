# ssh命令实现聊天室

[灵感来源](https://jyywiki.cn/OS/Chatroom.md)

这个项目的核心不在于 Python 编程，而在于对 OpenSSH Server (sshd) 机制的巧妙利用。
通常用 SSH 登录服务器时的流程是：
1. 认证：输入密码或验证公钥。
2. Shell 分配：系统启动用户的默认 Shell（如 /bin/bash）。
3. 交互：用户在 Shell 中输入 ls, cd 等命令，Shell 执行并返回结果。
要实现 SSH 聊天室，关键在于截断第 2 步。 我们不希望用户获得一个 Shell（既不安全，也不是我们要的功能），而是希望用户登录后直接运行聊天程序。

**关键步骤：ForceCommand**
OpenSSH 允许我们在 /etc/ssh/sshd_config 中使用 ForceCommand指令。它的作用是：无论用户试图执行什么命令，服务器都强制只执行这一条指定的命令。
配合 Match User 指令，我们可以锁定特定的聊天账号：
```bash
# 修改 服务器 /etc/ssh/sshd_config 文件
Match User chat
    # 允许空密码登录（配合 PAM 或许需要额外配置，或者使用 Key）
    PermitEmptyPasswords yes
    # 强制执行我们的 Python 脚本
    ForceCommand /home/chat/startup.py 
```

然后重启ssh服务：
```bash
sudo systemctl restart sshd
```

当配置生效后，无论用户在客户端输入什么：
ssh chat@host -> 服务器执行 startup.py
ssh chat@host "rm -rf /" -> 服务器依然执行 startup.py
这就形成了一个安全的沙箱环境。用户一旦退出 Python 脚本，SSH 连接也会随之断开。


前置操作：
```bash
# 服务器上提前创建记录文件 chat_history.log
touch /home/chat/chat_history.log
# 保证 chat 用户有 startup.py 脚本的执行权限和 chat_history.log 的读写权限
chmod +x /home/chat/startup.py
chmod 666 /home/chat/chat_history.log
```

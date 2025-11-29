#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses
import threading
import time
import os
import sys
import datetime
import locale
import fcntl  # Linux 文件锁模块

# --- 全局配置 ---
# 聊天记录保存路径
CHAT_FILE = '/home/chat/chat_history.log'
# 刷新频率 (秒)
REFRESH_RATE = 0.5
# 历史记录最大显示行数
MAX_HISTORY_LINES = 100

# --- 初始化本地语言环境 (解决中文乱码的关键) ---
try:
    locale.setlocale(locale.LC_ALL, '')
except:
    pass

class ChatRoom:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.nickname = ""
        # 线程锁，用于保护屏幕绘制 (curses 不是线程安全的)
        self.screen_lock = threading.Lock()
        self.running = True
        
        # 获取屏幕尺寸
        self.rows, self.cols = stdscr.getmaxyx()
        
        # 创建窗口: 上部显示区，下部输入区
        # curses.newwin(height, width, begin_y, begin_x)
        split_line = self.rows - 3
        self.win_history = curses.newwin(split_line, self.cols, 0, 0)
        self.win_input = curses.newwin(3, self.cols, split_line, 0)
        
        # 允许历史窗口滚动
        self.win_history.scrollok(True)
        self.win_history.idlok(True)

    def get_str_width(self, text):
        """简单估算字符串在屏幕上的显示宽度 (中文=2, 英文=1)"""
        width = 0
        for char in text:
            if ord(char) > 127:
                width += 2
            else:
                width += 1
        return width

    def get_nickname(self):
        """启动时询问用户昵称"""
        self.stdscr.clear()
        prompt = "请输入你的昵称 (支持中文): "
        
        # 1. 正确计算居中位置
        prompt_width = self.get_str_width(prompt)
        start_x = max(0, (self.cols - prompt_width) // 2)
        start_y = self.rows // 2
        
        # 2. 打印提示语
        self.stdscr.addstr(start_y, start_x, prompt)
        self.stdscr.refresh()
        
        curses.echo() # 开启回显
        try:
            # 昵称最长输入 60 字节,大约等于 20 个汉字
            nick_bytes = self.stdscr.getstr(60) 
            self.nickname = nick_bytes.decode('utf-8').strip()
            
            if not self.nickname:
                self.nickname = f"User-{os.getpid()}"
        except:
            self.nickname = "神秘人"
        curses.noecho() # 关闭回显

    def append_to_file(self, message):
        """
        将消息写入文件，使用 fcntl 文件锁保证并发安全
        """
        if not message.strip():
            return

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] <{self.nickname}> {message}\n"
        
        try:
            # 以追加模式打开文件
            with open(CHAT_FILE, 'a', encoding='utf-8') as f:
                # 1. 申请排他锁 (阻塞模式)
                # 如果此时有别人正在写，这里会等待，直到拿到锁为止
                fcntl.flock(f, fcntl.LOCK_EX)
                
                # 2. 写入数据
                f.write(line)
                f.flush() # 强制落盘
                
                # 3. 释放锁
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            # 生产环境可以把错误写到 stderr
            pass

    def draw_history(self):
        """
        后台线程：监控文件变化并刷新屏幕
        """
        last_mtime = 0
        
        while self.running:
            try:
                # 确保文件存在
                if not os.path.exists(CHAT_FILE):
                    open(CHAT_FILE, 'a').close()

                # 检查文件修改时间，减少不必要的 IO 读取
                current_mtime = os.path.getmtime(CHAT_FILE)
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    
                    # 读取文件最后 N 行
                    with open(CHAT_FILE, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                    
                    display_lines = lines[-MAX_HISTORY_LINES:]

                    # 加锁绘制，防止和主线程冲突
                    with self.screen_lock:
                        self.win_history.clear()
                        for line in display_lines:
                            try:
                                self.win_history.addstr(line)
                            except curses.error:
                                pass 
                        self.win_history.refresh()
                
                time.sleep(REFRESH_RATE)
            except Exception:
                pass

    def redraw_input_box(self, input_buffer):
        """
        重绘输入框
        """
        with self.screen_lock:
            self.win_input.clear()
            self.win_input.box() # 画边框
            self.win_input.addstr(1, 1, "Say: ")
            
            # 显示处理
            display_text = input_buffer
            display_width = self.get_str_width(display_text)
            max_width = self.cols - 8
            
            # 如果太长，简单倒着切片
            if display_width > max_width:
                 # 这里的切片只是粗略估算，防止报错
                display_text = display_text[-(max_width//2):] 
                
            try:
                self.win_input.addstr(1, 6, display_text)
            except curses.error:
                pass
                
            self.win_input.refresh()

    def run(self):
        # 1. 获取昵称
        self.get_nickname()
        
        # 2. 发送入场通知
        self.append_to_file("加入了聊天室")
        
        # 3. 清屏并初始化输入框
        self.stdscr.clear()
        self.redraw_input_box("")
        
        # 4. 启动后台刷新线程
        t = threading.Thread(target=self.draw_history, daemon=True)
        t.start()

        # 5. 主循环：处理输入
        input_buffer = ""
        while True:
            try:
                # 使用 get_wch() 支持宽字符 (中文)
                # 它会返回 int (特殊键) 或 str (字符)
                ch = self.win_input.get_wch()
            except curses.error:
                continue

            # --- 处理特殊键 (int) ---
            if isinstance(ch, int):
                # Backspace 键码处理 (不同终端可能不同)
                if ch == curses.KEY_BACKSPACE or ch == 127:
                    if len(input_buffer) > 0:
                        input_buffer = input_buffer[:-1]
                        self.redraw_input_box(input_buffer)
                
                # Enter 键码处理
                elif ch == curses.KEY_ENTER or ch == 10 or ch == 13:
                    if input_buffer.strip():
                        self.append_to_file(input_buffer)
                    input_buffer = ""
                    self.redraw_input_box(input_buffer)
                
                # Resize (终端大小改变)
                elif ch == curses.KEY_RESIZE:
                    self.rows, self.cols = self.stdscr.getmaxyx()
                    # 这里简化处理，直接清空重绘可能需要更复杂的逻辑
                    self.stdscr.clear()
                    self.stdscr.refresh()

            # --- 处理文本字符 (str) ---
            else:
                # 再次检查回车 (有些终端传回的是字符 '\n' 或 '\r')
                if ch == '\n' or ch == '\r':
                    if input_buffer.strip():
                        self.append_to_file(input_buffer)
                    input_buffer = ""
                    self.redraw_input_box(input_buffer)
                
                # 再次检查退格 (有些终端传回的是字符)
                elif ch == '\x7f' or ord(ch) == 127 or ord(ch) == 8:
                    if len(input_buffer) > 0:
                        input_buffer = input_buffer[:-1]
                        self.redraw_input_box(input_buffer)
                
                # 退出快捷键 (Ctrl+C = ASCII 3)
                elif len(ch) == 1 and ord(ch) == 3:
                    break
                
                # 普通字符输入
                else:
                    input_buffer += ch
                    self.redraw_input_box(input_buffer)

        # 退出循环
        self.running = False
        self.append_to_file("离开了聊天室")

def main(stdscr):
    # 初始化颜色 (如果终端支持)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
    
    # 隐藏光标 (我们自己控制输入显示，不需要物理光标闪烁)
    try:
        curses.curs_set(0)
    except:
        pass

    app = ChatRoom(stdscr)
    app.run()

if __name__ == "__main__":
    # 0. 权限检查与初始化文件
    if not os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE, 'w', encoding='utf-8') as f:
                f.write(f"[System] Chat room created at {datetime.datetime.now()}\n")
            # 赋予 666 权限，确保所有用户可读写
            os.chmod(CHAT_FILE, 0o666)
        except PermissionError:
            print(f"Error: Cannot create chat file at {CHAT_FILE}. Permission denied.")
            print("Please run: sudo touch " + CHAT_FILE + " && sudo chmod 666 " + CHAT_FILE)
            sys.exit(1)

    # 1. 设置环境变量防止延迟
    os.environ.setdefault('ESCDELAY', '25')

    # 2. 启动 Curses 应用
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # 如果崩溃，尝试打印错误
        print(f"System Error: {e}")

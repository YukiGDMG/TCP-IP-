import tkinter as tk
from tkinter import scrolledtext, messagebox
import socket
import threading
import json

HOST = '127.0.0.1'
PORT = 6000
COUNTDOWN_SECONDS = 60

class RPSClientGUI: # 客戶端 GUI 類別
    def __init__(self, master): # 初始化 GUI 元件與變數
        self.master = master
        master.title(" 線上猜拳遊戲")
        master.geometry("400x650")

        self.sock = None # TCP Socket
        self.is_connected = False # 是否連上 Server
        self.in_game = False      # 是否在遊戲中
        self.timer_task = None # 計時器任務

        # --- 介面佈局 ---
        # 1. 登入區塊
        self.frame_login = tk.Frame(master) # 登入區塊
        self.frame_login.pack(pady=10) # 上下間距
        tk.Label(self.frame_login, text="暱稱:").pack(side=tk.LEFT) # 標籤
        self.entry_nickname = tk.Entry(self.frame_login) # 輸入框
        self.entry_nickname.pack(side=tk.LEFT, padx=5) # 左右間距
        self.entry_nickname.insert(0, "Player1")  # 預設暱稱
        self.btn_connect = tk.Button(self.frame_login, text="登入伺服器", command=self.connect_server) # 連線按鈕
        self.btn_connect.pack(side=tk.LEFT) # 連線按鈕

        # 2. [核心功能] 配對控制區 (預設隱藏或無效)
        self.frame_match = tk.Frame(master, pady=5) # 配對區塊
        self.frame_match.pack()
        self.btn_match = tk.Button(self.frame_match, text="🔍 開始配對", font=("Arial", 14, "bold"), 
                                   bg="#4CAF50", fg="white", width=20, command=self.toggle_matchmaking) # 配對按鈕
        self.btn_match.pack()
        self.btn_match.config(state=tk.DISABLED) # 初始為無效

        # 3. 倒數計時與狀態
        self.lbl_timer = tk.Label(master, text="", font=("Arial", 20, "bold"), fg="red") # 計時器標籤
        self.lbl_timer.pack(pady=5) # 上下間距
        self.lbl_status = tk.Label(master, text="請先登入...", font=("Arial", 12), fg="blue") # 狀態標籤
        self.lbl_status.pack(pady=5)

        # 4. 出拳按鈕
        self.frame_actions = tk.Frame(master) # 出拳區塊
        self.frame_actions.pack(pady=10) # 上下間距
        
        self.btn_rock = tk.Button(self.frame_actions, text="✊", font=("Arial", 20), command=lambda: self.send_move('rock')) # 石頭按鈕
        self.btn_paper = tk.Button(self.frame_actions, text="✋", font=("Arial", 20), command=lambda: self.send_move('paper')) # 布按鈕
        self.btn_scissors = tk.Button(self.frame_actions, text="✌️", font=("Arial", 20), command=lambda: self.send_move('scissors')) # 剪刀按鈕
        self.btn_rock.pack(side=tk.LEFT, padx=10) # 左右間距
        self.btn_paper.pack(side=tk.LEFT, padx=10)
        self.btn_scissors.pack(side=tk.LEFT, padx=10)
        self.toggle_game_buttons(False) # 初始為無效

        # 5. 離開/斷線按鈕
        self.btn_leave = tk.Button(master, text="🚪 離開/斷線", font=("Arial", 10), command=self.disconnect_server)
        self.btn_leave.pack(pady=10)

        # 6. 紀錄
        self.log_area = scrolledtext.ScrolledText(master, height=10) # 紀錄區塊
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True) # 填滿並可擴展

    # --- 邏輯功能 ---
    def toggle_game_buttons(self, state): # 啟用/禁用出拳按鈕
        s = tk.NORMAL if state else tk.DISABLED # 狀態設定
        self.btn_rock.config(state=s) # 石頭按鈕
        self.btn_paper.config(state=s) # 布按鈕
        self.btn_scissors.config(state=s) # 剪刀按鈕
    
    def toggle_type2_bottons(self, state): # 啟用/禁用 收到type2後經過判斷的按鈕
        s = tk.NORMAL if state else tk.DISABLED # 狀態設定
        self.btn_match.config(state=s)
        self.btn_leave.config(state=s)

    def log(self, msg): # 紀錄訊息到文字區
        self.log_area.insert(tk.END, msg + "\n") # 插入訊息
        self.log_area.see(tk.END) # 自動捲動到底部

    def connect_server(self):
        """Step 1: 建立 TCP 連線 (還沒配對)"""
        nick = self.entry_nickname.get() # 取得暱稱
        if not nick: return # 空暱稱不處理
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # 建立 Socket
            self.sock.connect((HOST, PORT)) # 連線伺服器
            # 發送登入 (Type 1)
            self.sock.sendall((json.dumps({"type": 1, "nickname": nick}) + '\n').encode('utf-8')) # 握手訊息
            
            self.is_connected = True # 標記已連線
            self.btn_connect.config(state=tk.DISABLED) # 禁用連線按鈕
            self.btn_match.config(state=tk.NORMAL, text="🔍 開始配對", bg="#4CAF50") # 綠色
            self.lbl_status.config(text="已登入大廳，請按配對", fg="green") # 更新狀態
            
            threading.Thread(target=self.receive_loop, daemon=True).start() # 啟動接收執行緒
        except Exception as e:
            messagebox.showerror("錯誤", f"連線失敗: {e}")

    def toggle_matchmaking(self):
        """Step 2: 切換 [開始配對] / [取消配對]"""
        if not self.is_connected: return # 未連線不處理

        text = self.btn_match.cget("text") # 取得按鈕文字
        if "開始" in text:
            # 發送 Type 6: 請求配對
            self.send_json({"type": 6})
            self.btn_match.config(text="❌ 取消配對", bg="#FF9800") # 橘色
            self.lbl_status.config(text="排隊中...", fg="orange")
        else:
            # 發送 Type 7: 取消配對 (Server 需支援，若無則只改 UI)
            self.send_json({"type": 7})
            self.btn_match.config(text="🔍 開始配對", bg="#4CAF50") # 藍色
            self.lbl_status.config(text="已取消，回到大廳", fg="blue")

    def send_move(self, move):
        """Step 3: 遊戲中出拳"""
        self.send_json({"type": 3, "message": move}) # 發送出拳訊息
        self.toggle_game_buttons(False) # 禁用按鈕
        self.lbl_status.config(text="已出拳，等待對手...", fg="orange") # 更新狀態

    def disconnect_server(self):
        """完全斷開 / 離開遊戲"""
        if self.in_game:
            self.send_json({"type": 5}) # 遊戲中離開
        try:
            self.sock.close()
        except: pass
        self.reset_ui() # 重設 UI 狀態

    def send_json(self, data):
        if self.sock:
            try: self.sock.sendall((json.dumps(data) + '\n').encode('utf-8')) # 發送 JSON 訊息
            except: self.reset_ui() # 發送失敗則重設 UI

    # --- 接收迴圈 (核心狀態處理) ---
    def receive_loop(self):
        f = self.sock.makefile(mode='r', encoding='utf-8') # 文字檔包裝
        while self.is_connected:
            try:
                line = f.readline() # 讀取一行
                if not line: break
                msg = json.loads(line) # 解析 JSON 訊息
                msg_type = msg.get('type') # 取得訊息類型

                if msg_type == 2: # 系統訊息
                    content = msg.get('message') # 內容
                    self.log(f"[系統] {content}") # 紀錄系統訊息
                    
                    if "配對成功" in content: # 開始遊戲
                        self.master.after(0, self.game_start_ui) # 切換 UI 狀態
                    elif "回到大廳" in content or "對手離開房間，您獲勝！" in content: # 遊戲結束回大廳
                        self.master.after(0, self.game_over_ui_reset) # 重設遊戲 UI

                    
                elif msg_type == 4: # 結果
                    res = msg.get('result') # 勝負結果
                    opp = msg.get('opponent_move') # 對手出拳
                    self.log(f"★ 判決: {res} (對手: {opp})") # 紀錄結果
                    self.lbl_status.config(text=f"{res}", fg="orange")
                    self.lbl_timer.config(text="") # 清除計時器顯示
                    self.master.after(0, self.stop_countdown)
                    # 結果顯示後，Server 會自動送 "回到大廳" 的訊息，這裡只需顯示

            except:
                break
        self.master.after(0, self.reset_ui) # 斷線後重設 UI

    # --- UI 狀態切換 helper ---
    def game_start_ui(self):
        self.in_game = True      # 標記遊戲中
        self.btn_match.config(text="⚔️ 對戰中", state=tk.DISABLED, bg="gray") # 灰色
        self.toggle_game_buttons(True) # 啟用出拳按鈕
        self.start_countdown(60) # 開始 60 秒倒數

    def game_over_ui_reset(self):
        self.in_game = False     # 標記非遊戲中
        self.stop_countdown() # 停止計時器
        self.toggle_game_buttons(False) # 禁用出拳按鈕
        self.toggle_type2_bottons(True) # 啟用 type2 後的按鈕
        self.btn_match.config(text="🔍 開始配對", state=tk.NORMAL, bg="#4CAF50")
        self.lbl_status.config(text="遊戲結束，請重新配對", fg="blue")
        self.lbl_timer.config(text="") # 清除計時器顯示

    def reset_ui(self):
        self.is_connected = False # 標記未連線
        self.in_game = False    # 標記非遊戲中
        self.stop_countdown() # 停止計時器
        self.btn_connect.config(state=tk.NORMAL) # 啟用連線按鈕
        self.btn_match.config(text="🔍 開始配對", state=tk.DISABLED, bg="gray")
        self.toggle_game_buttons(False) # 禁用出拳按鈕
        self.log("--- 已斷線 ---")

    # --- 計時器 (同前) ---
    def start_countdown(self, sec):
        self.stop_countdown() # 先停止舊的計時器
        def count():
            nonlocal sec # 使用外層變數
            if sec > 0:
                self.lbl_timer.config(text=f"{sec}") # 更新顯示
                sec -= 1
                self.timer_task = self.master.after(1000, count) # 1 秒後呼叫自己
            else:
                self.lbl_timer.config(text="逾時") # 顯示逾時
                self.toggle_game_buttons(False) # 禁用按鈕
        count()

    def stop_countdown(self):
        if self.timer_task:
            self.master.after_cancel(self.timer_task) # 取消計時器
            self.timer_task = None

if __name__ == '__main__':
    root = tk.Tk()
    RPSClientGUI(root) # 建立 GUI 物件
    root.mainloop()
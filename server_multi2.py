import socket
import threading
import json
import time

HOST = '0.0.0.0'
PORT = 6000
MAX_BYTES = 1024

# --- 全域變數 ---
waiting_queue = []
queue_lock = threading.Lock()

# --- 裁判邏輯 ---
def get_winner(move1, move2): # 判定勝負
    if move1 == move2: return 'draw'
    rules = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
    if move1 not in rules or move2 not in rules: return 'error'
    return 'p1' if rules.get(move1) == move2 else 'p2'

# --- 遊戲房間 ---
class GameRoom: # 管理兩個玩家的遊戲邏輯
    def __init__(self, player1, player2):
        self.p1 = player1
        self.p2 = player2
        self.moves = {}
        self.lock = threading.Lock()
        self.event = threading.Event() # 用來通知遊戲結束
        self.game_active = True
        print(f"[配對成功] {self.p1['nickname']} vs {self.p2['nickname']}")

    def start(self):
        # 通知雙方遊戲開始 (Type 2)
        # 使用輔助函式傳送 JSON
        self.send_json(self.p1['sock'], {"type": 2, "message": f"配對成功！對手是 {self.p2['nickname']}。請出拳！"})
        self.send_json(self.p2['sock'], {"type": 2, "message": f"配對成功！對手是 {self.p1['nickname']}。請出拳！"})

        # 注意：這裡不再開啟新執行緒，而是讓原本的 client_handler 進入遊戲迴圈
        # 我們只需要設定狀態，讓外部的迴圈知道「現在是遊戲時間」
        self.p1['room'] = self # 房間參考
        self.p2['room'] = self
        self.p1['state'] = 'GAME' # 狀態改為遊戲中
        self.p2['state'] = 'GAME'

    def send_json(self, sock, msg_dict): # 傳送 JSON 訊息
        try:
            sock.sendall((json.dumps(msg_dict) + '\n').encode('utf-8')) # 換行符號作為結尾
        except:
            pass

    def handle_move(self, player_obj, move):
        """處理出拳邏輯"""
        with self.lock: # 確保線程安全
            if not self.game_active: return # 遊戲已結束
            
            print(f"[房間] {player_obj['nickname']} 出拳: {move}")
            self.moves[player_obj['addr']] = move # 記錄出拳
            
            if len(self.moves) == 2: # 雙方皆已出拳
                self.judge_and_respond() # 判決並回應結果

    def judge_and_respond(self):
        """判決與結算"""
        # 取得雙方出拳
        m1 = self.moves[self.p1['addr']]
        m2 = self.moves[self.p2['addr']]
        winner = get_winner(m1, m2) # 判定勝負，回傳到第15行的函式
        # 準備結果訊息
        p1_res = "You Win!" if winner == 'p1' else ("Draw" if winner == 'draw' else "You Lose!")
        p2_res = "You Win!" if winner == 'p2' else ("Draw" if winner == 'draw' else "You Lose!")
        
        # 傳送 Type 4 結果
        self.send_json(self.p1['sock'], {"type": 4, "result": p1_res, "opponent_move": m2})
        self.send_json(self.p2['sock'], {"type": 4, "result": p2_res, "opponent_move": m1})
        
        # 結束這一局，但不斷線
        self.end_game(reason="正常結算")

    def handle_quit(self, leaver):
        """處理有人中途離開"""
        winner = self.p2 if leaver == self.p1 else self.p1 # 另一方獲勝
        # 輔助函式傳送訊息
        self.send_json(winner['sock'], {"type": 2, "message": "對手離開房間，您獲勝！"})
        self.end_game(reason="對手離開") # 結束遊戲

    def end_game(self, reason):
        """遊戲結束清理"""
        with self.lock:
            if not self.game_active: return
            self.game_active = False # 標記遊戲結束

        print(f"[結束] 房間關閉: {reason}")
        
        # 將雙方狀態設回 IDLE (發呆)，這樣他們的迴圈就會回到大廳
        self.p1['state'] = 'IDLE' # 狀態回大廳
        self.p2['state'] = 'IDLE'
        self.p1['room'] = None # 清除房間參考
        self.p2['room'] = None
        
        # 通知回到大廳 (Type 2 包含 '大廳' 關鍵字)
        reset_msg = {"type": 2, "message": "遊戲結束，回到大廳。"}
        self.send_json(self.p1['sock'], reset_msg) # 通知回大廳
        self.send_json(self.p2['sock'], reset_msg)

# --- Client 生命週期管理 ---
def client_handler(sock, addr):
    print(f"[連線] {addr}") # 新連線進來
    player = {
        'sock': sock, 
        'addr': addr, 
        'nickname': 'Unknown', 
        'state': 'IDLE', # 狀態: IDLE (大廳), QUEUE (排隊中), GAME (遊戲中)
        'room': None
    }

    try:
        # 1. 讀取暱稱
        sock.settimeout(None) # 沒有輸入名稱的時間上限
        f = sock.makefile(mode='r', encoding='utf-8') # 轉成檔案物件方便讀取行
        login_data = f.readline() # 等待 Client 傳送登入訊息
        if not login_data: return
        player['nickname'] = json.loads(login_data).get('nickname', 'Unknown') # 取得暱稱
        print(f"[登入] {player['nickname']} 進入大廳")
        # 歡迎訊息
        sock.sendall((json.dumps({"type": 2, "message": f"歡迎 {player['nickname']}，請按 [開始配對]"}) + '\n').encode('utf-8'))

        # 2. 進入主迴圈 (無限復活)
        while True:
            # 等待 Client 傳送指令
            data = f.readline()
            if not data: break # 斷線
            
            msg = json.loads(data)
            msg_type = msg.get('type')

            # --- 狀態機邏輯 ---
            if player['state'] == 'IDLE':
                # 在大廳，只接受 Type 6 (開始配對)
                if msg_type == 6:
                    print(f"[排隊] {player['nickname']} 加入隊列")
                    player['state'] = 'QUEUE'
                    with queue_lock: # 加入排隊隊列
                        waiting_queue.append(player) # 加入等待隊列
                    sock.sendall((json.dumps({"type": 2, "message": "正在搜尋對手..."}) + '\n').encode('utf-8')) # 回應訊息

            elif player['state'] == 'QUEUE':
                # 排隊中，如果收到 Type 7 (取消配對)
                if msg_type == 7: # 取消配對
                    print(f"[取消] {player['nickname']} 取消排隊") # 取消排隊
                    player['state'] = 'IDLE'
                    with queue_lock: # 從排隊隊列移除
                        if player in waiting_queue: waiting_queue.remove(player) # 移除
                    sock.sendall((json.dumps({"type": 2, "message": "已取消配對，回到大廳。"}) + '\n').encode('utf-8'))

            elif player['state'] == 'GAME':
                # 遊戲中，接受 Type 3 (出拳) 或 Type 5 (離開)
                room = player['room']
                if room: # 確保房間存在
                    if msg_type == 3: # 出拳
                        room.handle_move(player, msg.get('message').strip().lower())
                    elif msg_type == 5: # 離開遊戲
                        room.handle_quit(player)

    except Exception as e: # 捕捉所有異常，避免程式崩潰
        print(f"[異常] {player['nickname']} 斷線: {e}")
    finally:
        # 清理殘留狀態
        if player in waiting_queue: waiting_queue.remove(player) # 從排隊隊列移除
        if player['room']: player['room'].handle_quit(player) # 通知房間有人離開
        try: sock.close() # 關閉連線
        except: pass # 忽略錯誤
        print(f"[斷線] {player['nickname']} 離開伺服器") # 完成斷線清理

# --- 配對迴圈 ---
def matchmaking_loop():
    while True:
        with queue_lock: # 配對鎖定
            if len(waiting_queue) >= 2: # 至少兩人可配對
                p1 = waiting_queue.pop(0) # 取出第一位玩家
                p2 = waiting_queue.pop(0) # 取出第二位玩家
                # 建立房間並啟動 (這會改變 p1, p2 的 state 為 GAME)
                room = GameRoom(p1, p2)
                room.start()
        time.sleep(0.5)

if __name__ == '__main__': # 主程式入口
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP Socket
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # 允許重複使用位址
    server.bind((HOST, PORT)) # 綁定位址與埠號
    server.listen(20) # 最大佇列數量
    print(f"=== 猜拳 Server (持久連線版) 啟動 ===") # 啟動訊息
    
    threading.Thread(target=matchmaking_loop, daemon=True).start() # 啟動配對執行緒

    while True:
        sock, addr = server.accept() # 等待新連線
        threading.Thread(target=client_handler, args=(sock, addr), daemon=True).start() # 啟動客戶端處理執行緒
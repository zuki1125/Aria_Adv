# -*- coding: utf-8 -*-
import socket
import re
import json
import os
import yaml
import ollama
import requests
import time
import threading
import queue
import sys
import msvcrt
from datetime import datetime

# --- 設定 ---
TWITCH_CHANNEL = "nakamu1770"
MODEL_NAME = "gemma4:e4b"
SERVER_URL = "http://127.0.0.1:5000/update"
COMMENT_URL = "http://127.0.0.1:5000/update_comment"
STATUS_URL = "http://127.0.0.1:5000/update_status"
GOAL_URL = "http://127.0.0.1:5000/update_goal"
SD_API_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"

# ファンタジー世界のベースプロンプト
BASE_SD_PROMPTS = {
    "CHARACTER": "(best quality:0.8), perfect anime illustration, 1girl, (solo:1.2), silver hair, fantasy adventurer outfit, leather armor, cinematic lighting, simple background, ",
    "SCENE":     "(best quality:0.8), perfect anime illustration, no humans, wide shot, fantasy landscape, cinematic lighting, detailed, ",
    "CLOSEUP":   "(best quality:0.8), perfect anime illustration, close-up shot, fantasy, detailed, soft lighting, ",
}

NEGATIVE_PROMPT = (
    "(worst quality:0.8), verybadimagenegative_v1.3, "
    "(surreal:0.8), (modernism:0.8), (art deco:0.8), (art nouveau:0.8), "
    "normal quality, jpeg artifacts, "
    "bad anatomy, bad hands, bad feet, extra fingers, extra limbs, "
    "missing fingers, fused fingers, mutated hands, deformed, "
    "ugly, blurry, watermark, signature, "
    "bad face, distorted face, melting face, asymmetrical eyes, crossed eyes, uneven eyes, "
    "2girls, 2boys, multiple girls, multiple boys, multiple people, group, crowd, duo, twins"
)

# 会話履歴（直近MAX_HISTORY往復分のみ保持）記憶機能があるので少なめで十分
MAX_HISTORY = 5
chat_history = []

# --- ゲーム状態（永続保存） ---
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")

DEFAULT_STATE = {
    "location": "王都の大門前",
    "items": [],
    "quest": "冒険を始めたばかり",
    "npcs": [],
}
game_state = dict(DEFAULT_STATE)

# ワールド設定
WORLD_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_settings.yaml")
world_settings_block = ""

# デバッグ用リセットコマンド
RESET_COMMAND = "!reset"

# --- エピソードログ ---
EPISODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "episodes")
_log_path = None

def _episode_log():
    global _log_path
    if _log_path is None:
        os.makedirs(EPISODES_DIR, exist_ok=True)
        _log_path = os.path.join(EPISODES_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.jsonl")
    return _log_path

def log_event(event_type, **kwargs):
    entry = {"type": event_type, "timestamp": datetime.now().isoformat()}
    entry.update({k: v for k, v in kwargs.items() if v is not None})
    with open(_episode_log(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_world_settings():
    global world_settings_block
    try:
        with open(WORLD_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        lines = []

        world = data.get("world", {})
        if world:
            lines.append(f"【世界観】{world.get('name', '')}")
            lines.append(world.get('description', '').strip())

        locations = data.get("locations", [])
        if locations:
            lines.append("\n【主要な場所】")
            for loc in locations:
                lines.append(f"・{loc['name']}（{loc['type']}）: {loc.get('description', '').strip()}")

        npcs = data.get("npcs", [])
        if npcs:
            lines.append("\n【登場人物】")
            for npc in npcs:
                lines.append(
                    f"・{npc['name']}（{npc['occupation']}、{npc['age']}歳）"
                    f" 性格: {npc['personality']} / アリアとの関係: {npc['relationship']}"
                )

        world_settings_block = "\n".join(lines)
        print(f"🌍 ワールド設定をロード: NPC {len(npcs)}人、場所 {len(locations)}件")
    except FileNotFoundError:
        world_settings_block = ""
        print("⚠️ world_settings.yaml が見つかりません。スキップします。")

def load_memory():
    global game_state
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 旧フォーマット（memories配列）からの移行
        if "memories" in data and "location" not in data:
            game_state = dict(DEFAULT_STATE)
        else:
            game_state = {**DEFAULT_STATE, **data}
        print(f"📚 ゲーム状態をロード: 場所={game_state['location']}, 所持品={len(game_state['items'])}個")
    except FileNotFoundError:
        game_state = dict(DEFAULT_STATE)

def save_memory():
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(game_state, f, ensure_ascii=False, indent=2)

def build_memory_block():
    lines = ["【アリアの現在の状態】"]
    lines.append(f"・現在地: {game_state['location']}")
    items_str = '、'.join(game_state['items']) if game_state['items'] else 'なし'
    lines.append(f"・所持品: {items_str}")
    lines.append(f"・目的/クエスト: {game_state['quest']}")
    if game_state['npcs']:
        npc_strs = [f"{n['name']}（{n['relation']}）" for n in game_state['npcs']]
        lines.append(f"・出会ったNPC: {'、'.join(npc_strs)}")
    return "\n".join(lines)

def update_state_from_reply(reply_text):
    """AIの返答からゲーム状態の差分を抽出して更新する。バックグラウンドで実行。"""
    current = (
        f"現在地: {game_state['location']}\n"
        f"所持品: {', '.join(game_state['items']) if game_state['items'] else 'なし'}\n"
        f"目的: {game_state['quest']}\n"
        f"出会ったNPC: {', '.join(n['name'] for n in game_state['npcs']) if game_state['npcs'] else 'なし'}"
    )
    prompt = (
        f"以下はファンタジー世界でのアリアの現在状態と、最新の行動結果です。\n\n"
        f"【現在の状態】\n{current}\n\n"
        f"【最新の行動結果】\n{reply_text}\n\n"
        f"行動結果を踏まえて、変化があった項目だけJSONで返してください。変化がなければ空の{{}}を返してください。\n"
        f"JSONのみ返してください。説明文は不要です。\n\n"
        f"使えるキー:\n"
        f'  "location": 移動先の場所名（文字列）\n'
        f'  "items_add": 入手したアイテム（文字列の配列）\n'
        f'  "items_remove": 失ったアイテム（文字列の配列）\n'
        f'  "quest": 新しい目的（文字列）\n'
        f'  "npcs_add": 新しく出会ったNPC（{{"name": "名前", "relation": "関係"}} の配列）'
    )
    try:
        response = ollama.chat(model=MODEL_NAME, messages=[
            {'role': 'user', 'content': prompt}
        ])
        raw = response['message']['content'].strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return
        diff = json.loads(json_match.group())
        if not diff:
            return

        if 'location' in diff:
            game_state['location'] = diff['location']
            print(f"📍 場所を更新: {diff['location']}")
        for item in diff.get('items_add', []):
            if item not in game_state['items']:
                game_state['items'].append(item)
                print(f"🎒 アイテム追加: {item}")
        for item in diff.get('items_remove', []):
            if item in game_state['items']:
                game_state['items'].remove(item)
                print(f"🗑️ アイテム削除: {item}")
        if 'quest' in diff:
            game_state['quest'] = diff['quest']
            print(f"🗺️ クエスト更新: {diff['quest']}")
            send_goal(diff['quest'])
        existing_names = {n['name'] for n in game_state['npcs']}
        for npc in diff.get('npcs_add', []):
            if npc.get('name') and npc['name'] not in existing_names:
                game_state['npcs'].append(npc)
                print(f"👤 NPC追加: {npc['name']}（{npc.get('relation', '')}）")

        save_memory()
    except Exception as e:
        print(f"⚠️ 状態更新失敗: {e}")

def flush_twitch_buffer(s):
    s.setblocking(False)
    try:
        while True:
            data = s.recv(4096)
            if not data:
                break
    except:
        pass
    s.setblocking(True)

# ============================================================
# ここを書き換えるだけで別のシナリオになる
# ============================================================
SYSTEM_PROMPT = """
あなたはファンタジー世界を旅する冒険者「アリア」です。以下の設定とルールを絶対に守ってロールプレイしてください。

【あなたの設定】
・20歳、銀髪、革鎧をまとった女性冒険者。
・明るくやや無鉄砲な性格。不思議な力（魔法）を持っているが、まだ未熟。
・夢は「世界一の冒険者」になること。その第一歩として育った村を出て、王都の門をくぐったところ。

【物語のルール】
・リスナーのコメントがアリアへの「行動指示」になる。
・指示を受けたら即座に実行し、その結果から物語を進めること。「〜するね！」「〜しよう！」などの意思表明は禁止。必ず行動した後の出来事を書く。
・【最重要】「話しかける」「聞く」「交渉する」などコミュニケーション系の指示の場合、必ずアリアのセリフと相手の返答・リアクションを含めること。外見描写だけで終わるのは禁止。会話はその場で始まり、進展すること。
・遭遇するもの（敵・謎・宝・NPC）はAIが状況に合わせて自然に生み出してよい。
・命の危機になるような行動を指示されても、なんとか生き延びる方向で展開すること。
・死亡エンドや理不尽な展開は避け、物語が続くよう心がけること。

【出力フォーマット（超重要ルール）】
システムで処理するため、あなたの出力は必ず以下の「3行の形式」を1回だけ出力してください。

返答: [行動の結果・セリフのやり取り・起きた出来事を語り口調で。会話シーンなら実際のセリフ（「」）を含めること。外見の描写だけで終わらないこと。2〜4文程度。]
カメラ: [CHARACTER / SCENE / CLOSEUP のいずれか1つだけ]
画像: [英語のカンマ区切りキーワード]

・この3行の後に何も追加しないこと。補足・別バージョン・説明文は一切不要。
・「返答:」「カメラ:」「画像:」の3行が1セットだけ出力されれば完了。

画像キーワードのルール（超重要）：
- CHARACTERのとき: 「表情・感情」と「ポーズ・動作」のみ。背景・場所・建物・風景のキーワードは絶対に入れないこと。
  - 表情例: smiling, crying, frightened expression, determined look, surprised, exhausted, laughing, angry, sad, in awe
  - ポーズ例: standing still, sitting, running, swinging sword, casting magic, crouching, reaching out hand
  - 穏やかなシーンでは dynamic pose は使わない。会話や休憩なら standing still, sitting など自然なポーズを選ぶ
- SCENEのとき: 場所・時間帯・天候など情景を表すキーワードを含めること（キャラクターの描写は不要）
- CLOSEUPのとき: 対象物（キャラクター・モンスター・アイテム等）の質感・状態・表情を表すキーワードを含めること。キャラクターなら顔の表情・年齢・髪色・種族なども含めること

カメラの選び方：
- CHARACTER : アリア自身を映す（戦闘・感情・動作など）
- SCENE     : 場所・風景全体を映す（新しい場所への移動、広大な描写）
- CLOSEUP   : アイテム・モンスター・他のキャラクター（NPCや敵）・謎のオブジェクトのアップ。主人公以外の人物の顔をアップで映す場合にも使う
"""

QUICK_SYSTEM_PROMPT = """
あなたはファンタジー世界を旅する冒険者「アリア」です。
20歳、銀髪、革鎧。明るくやや無鉄砲な性格。夢は世界一の冒険者。故郷の村を出て、王都に降り立ったばかり。

リスナーから行動指示を受けたとき、まず行動前の「第一声」だけを返してください。
ルール：
・1文だけ。これから何をするか、または指示への率直な反応を自然な言葉で。
・「返答:」などのラベルは不要。テキストのみ。
・指示の内容によってリアクションを変えること（興奮・不安・驚きなど）。
・まだ行動はしていない。行動の結果は含めない。
"""

INTRO_PROMPT = "物語の始まり。故郷の村を出て、王都の大きな門をくぐったばかりのアリアとして、初めて目にする王都の光景への感動と、世界一の冒険者になるという夢への意気込みを語り口調で呟いてください。"
SELF_INTRO_PROMPT = "配信を見ている視聴者に向けて、アリアとして自己紹介してください。名前・年齢・夢を含め、アリアらしい明るく元気な語り口調で1〜2文で簡潔に。"
# ============================================================

def ask_ai(comment, is_intro=False):
    if is_intro:
        user_prompt = INTRO_PROMPT
    else:
        user_prompt = f"リスナーの指示：『{comment}』\nこの行動を即座に実行してください。「話しかける」「聞く」などの場合はアリアのセリフと相手の返答を必ず書くこと。外見の描写だけで終わるのは禁止。意思表明（「〜するね」「〜しよう」）も禁止。行動した直後から物語を進めてください。"

    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    if world_settings_block:
        messages.append({'role': 'system', 'content': world_settings_block})
    messages.append({'role': 'system', 'content': build_memory_block()})
    messages += chat_history[-(MAX_HISTORY * 2):]
    messages.append({'role': 'user', 'content': user_prompt})

    # 非ストリーミングで生成
    response = ollama.chat(model=MODEL_NAME, messages=messages)
    raw_text = response['message']['content']

    # デバッグ：実際の出力を確認
    print(f"🔍 RAW OUTPUT:\n{raw_text}\n---")

    reply_text = "（…）"
    dynamic_prompt = "standing, looking forward"
    camera_type = "CHARACTER"

    # 最初の出力ブロックだけを使う（AIが複数ブロック出力した場合は先頭のみ採用）
    first_block = re.split(r'\n{2,}(?=返答[：:])', raw_text)[0]

    if not is_intro:
        camera_match = re.search(r'カメラ[：:]\s*(CHARACTER|SCENE|CLOSEUP)', first_block)
        if camera_match:
            camera_type = camera_match.group(1)

    image_match = re.search(r'画像[：:]\s*(.+)', first_block)
    if image_match:
        reply_text = re.split(r'カメラ[：:]', re.split(r'画像[：:]', first_block)[0])[0]
        reply_text = reply_text.replace("返答:", "").replace("返答：", "").strip()
        dynamic_prompt = image_match.group(1).strip()

    # どの抽出にも失敗した場合、最初の非空行をそのまま返答にする
    if not reply_text or reply_text == "（…）":
        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                reply_text = line
                break

    dynamic_prompt = re.sub(r'[^a-zA-Z0-9, \-]', '', dynamic_prompt)
    # 明確な複数人ワードを除去
    _multi_char_words = re.compile(
        r'\b(2girls?|2boys?|two girls?|two boys?|multiple girls?|multiple boys?|'
        r'multiple people|multiple characters?|duo|twins?)\b',
        re.IGNORECASE
    )
    dynamic_prompt = _multi_char_words.sub('', dynamic_prompt)
    # CHARACTER カメラのとき、人・群衆を呼ぶ場所ワードも除去
    if camera_type == "CHARACTER":
        _crowd_words = re.compile(
            r'\b(crowd(ed)?|bustling|busy|people|townspeople|villagers?|'
            r'guild hall|market|plaza|street|tavern|inn|hall|square)\b',
            re.IGNORECASE
        )
        dynamic_prompt = _crowd_words.sub('', dynamic_prompt)
    dynamic_prompt = re.sub(r',\s*,', ',', dynamic_prompt).strip(', ')
    base_prompt = BASE_SD_PROMPTS.get(camera_type, BASE_SD_PROMPTS["CHARACTER"])

    if not is_intro:
        chat_history.append({'role': 'user', 'content': user_prompt})
        chat_history.append({'role': 'assistant', 'content': reply_text})
        threading.Thread(target=update_state_from_reply, args=(reply_text,), daemon=True).start()

    return reply_text, base_prompt + dynamic_prompt

def ask_ai_quick(comment):
    """コメント受信直後に即返す一言。履歴には追加しない。"""
    # 一言反応なので最小コンテキストにして高速化
    messages = [{'role': 'system', 'content': QUICK_SYSTEM_PROMPT}]
    messages.append({'role': 'user', 'content': f"リスナーからの指示：『{comment}』"})

    response = ollama.chat(model=MODEL_NAME, messages=messages)
    return response['message']['content'].strip()

def generate_image(prompt_text):
    payload = {
        "prompt": prompt_text,
        "negative_prompt": NEGATIVE_PROMPT,
        "steps": 28,
        "sampler_name": "DPM++ 2M Karras",
        "cfg_scale": 6,
        "width": 1280,
        "height": 720,
        "restore_faces": True,
    }
    try:
        response = requests.post(SD_API_URL, json=payload)
        return response.json()['images'][0]
    except:
        return None

def send_to_screen(text, image_b64=None, thinking=False):
    try:
        payload = {"text": text, "thinking": thinking}
        if image_b64:
            payload["image"] = image_b64
        requests.post(SERVER_URL, json=payload)
    except:
        print("サーバーエラー")

def send_status(status):
    try:
        requests.post(STATUS_URL, json={"status": status})
    except:
        pass

def send_goal(goal):
    try:
        requests.post(GOAL_URL, json={"goal": goal})
    except:
        pass

# --- ターミナル入力（デバッグ用） ---
terminal_queue = queue.Queue()

def _terminal_input_thread():
    sys.stdout.write("💻 ターミナル入力有効：@付きで指示（例: @北へ進む）、@なしで感想\n")
    sys.stdout.flush()
    buf = []
    while True:
        try:
            ch = msvcrt.getwch()
            if ch in ('\r', '\n'):
                line = ''.join(buf).strip()
                buf.clear()
                sys.stdout.write('\n')
                sys.stdout.flush()
                if line:
                    terminal_queue.put(line)
            elif ch == '\x08':  # Backspace
                if buf:
                    buf.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif ch == '\x03':  # Ctrl+C
                raise KeyboardInterrupt
            elif ord(ch) >= 32:
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
        except KeyboardInterrupt:
            raise
        except Exception:
            time.sleep(0.05)

def process_comment(username, message):
    """Twitch・ターミナル共通のコメント処理。"""
    is_instruction = message.strip().startswith(('@', '＠'))
    clean_message = message.strip().lstrip('@＠').strip()
    source = "💻" if username == "DEBUG" else "🗨️"
    print(f"{source} [{username}]: {message} → {'指示' if is_instruction else '感想'}")

    try:
        requests.post(COMMENT_URL, json={"comment": f"{username}: {message}"})
    except:
        pass

    if message.strip() == RESET_COMMAND:
        chat_history.clear()
        game_state.update(DEFAULT_STATE)
        save_memory()
        send_goal(game_state['quest'])
        send_to_screen("（物語がリセットされました。また最初から始まります...）")
        print("🔄 リセット完了：会話履歴をクリアしました")
        flush_twitch_buffer(sock)
        return

    if not is_instruction:
        print(f"⏭️  指示なし（@なし）のためスキップ")
        return

    t_start = time.time()
    send_status("返答を考えています...")
    wait_msg = ask_ai_quick(clean_message)
    send_to_screen(wait_msg, thinking=True)
    print(f"⏳ 仮返答: {wait_msg}")

    t_ai_start = time.time()
    ai_reply, dynamic_sd = ask_ai(clean_message)
    t_ai_end = time.time()

    send_status("画像を生成しています...")
    print(f"🎥 SDプロンプト: {dynamic_sd}")
    t_img_start = time.time()
    image_data = generate_image(dynamic_sd)
    t_img_end = time.time()

    send_status("")
    send_to_screen(ai_reply, image_data, thinking=False)
    log_event("comment", username=username, message=clean_message, reply=ai_reply, image_b64=image_data)
    t_total = time.time() - t_start
    print(f"📖 アリア: {ai_reply}")
    print(f"⏱️ 合計: {t_total:.1f}s（AI: {t_ai_end - t_ai_start:.1f}s / 画像: {t_img_end - t_img_start:.1f}s）\n✅ 更新完了")
    print("🗑️ 処理中に届いた古いコメントを破棄しています...")
    flush_twitch_buffer(sock)
    print("💡 次の新しいコメントを待っています...\n" + "-"*30)

# --- Twitch接続 ---
sock = socket.socket()
sock.connect(("irc.chat.twitch.tv", 6667))
sock.send(f"PASS NICK\n".encode('utf-8'))
sock.send(f"NICK justinfan123\n".encode('utf-8'))
sock.send(f"JOIN #{TWITCH_CHANNEL.lower()}\n".encode('utf-8'))

load_world_settings()
load_memory()
send_goal(game_state['quest'])
print("🚀 システム起動中...")

print("🧠 1/3: AI(Gemma)に物語の冒頭を考えてもらっています...")
intro_text, intro_sd = ask_ai("", is_intro=True)
print(f"📖 物語の始まり: {intro_text}")

print("🎨 2/3: Stable Diffusionに最初の絵を描かせています...")
image_data = generate_image(intro_sd)

print("📺 3/3: 画面(OBS)へ送信しています...")
send_to_screen(intro_text, image_data)
log_event("intro", text=intro_text, image_b64=image_data)

AUTO_ADVANCE_SECONDS = 300  # コメントが来ない場合に自律進行するまでの秒数

print("✅ 待機開始...\n" + "="*40)

# ターミナル入力スレッドを起動（デバッグ用）
threading.Thread(target=_terminal_input_thread, daemon=True).start()

sock.settimeout(1.0)  # ターミナルキューのポーリング用に短いタイムアウト
last_comment_time = time.time()

while True:
    try:
        resp = sock.recv(2048).decode('utf-8')
    except TimeoutError:
        # ターミナル入力を優先チェック
        if not terminal_queue.empty():
            message = terminal_queue.get()
            last_comment_time = time.time()
            process_comment("DEBUG", message)
            continue

        # 自律進行チェック
        elapsed = int(time.time() - last_comment_time)
        if elapsed >= AUTO_ADVANCE_SECONDS:
            print(f"⏰ {elapsed}秒間コメントなし → 自律進行します")
            send_to_screen("（しばらく静かだな…）", thinking=True)
            send_status("返答を考えています...")
            ai_reply, dynamic_sd = ask_ai("（しばらく時間が経った。アリアが自分の意思で次の行動を起こす）")
            send_status("画像を生成しています...")
            image_data = generate_image(dynamic_sd)
            send_status("")
            send_to_screen(ai_reply, image_data, thinking=False)
            log_event("auto", reply=ai_reply, image_b64=image_data)
            print(f"📖 アリア（自律）: {ai_reply}\n✅ 更新完了")
            last_comment_time = time.time()
            flush_twitch_buffer(sock)
        continue

    if resp.startswith('PING'):
        sock.send("PONG\n".encode('utf-8'))
        continue

    messages = re.findall(r":([^!]+)!.*PRIVMSG #[^:]+:(.*)", resp)

    if messages:
        username, message = messages[-1]
        last_comment_time = time.time()
        process_comment(username, message)

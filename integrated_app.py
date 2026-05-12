import socket
import re
import ollama
import requests
import time

# --- 設定 ---
TWITCH_CHANNEL = "nakamu1770"
MODEL_NAME = "gemma4:e4b" 
SERVER_URL = "http://127.0.0.1:5000/update"
SD_API_URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"

BASE_SD_PROMPTS = {
    "CHARACTER": "1girl, 15 years old, black bob hair, school uniform, trapped in a dark concrete room, dim lighting, cinematic lighting, masterpiece, high quality, ",
    "CLOSEUP":   "no humans, close-up shot, dark concrete room, dim lighting, masterpiece, high quality, macro shot, ",
    "ROOM":      "no humans, wide shot, dark concrete room, dim lighting, cinematic lighting, empty room, masterpiece, high quality, ",
}

NEGATIVE_PROMPT = (
    "worst quality, low quality, normal quality, jpeg artifacts, "
    "bad anatomy, bad hands, bad feet, extra fingers, extra limbs, "
    "missing fingers, fused fingers, mutated hands, deformed, "
    "ugly, blurry, watermark, signature"
)

# 会話履歴（直近MAX_HISTORY往復分のみ保持）
MAX_HISTORY = 10
chat_history = []

# デバッグ用リセットコマンド（このコメントが来たら初期状態に戻す）
RESET_COMMAND = "!reset"

# 🌟 新機能：溜まっている古いコメントをすべて捨てる関数
def flush_twitch_buffer(s):
    # ソケットを一時的に「ノンブロッキング（待たない）」モードにする
    s.setblocking(False)
    try:
        while True:
            # 溜まっているデータを読めるだけ読んで、捨てる
            data = s.recv(4096)
            if not data:
                break
    except:
        # 読むデータがなくなったらここに来る
        pass
    # モードを元に戻す（ブロッキングモード）
    s.setblocking(True)

def ask_ai(comment, is_intro=False):
    # 🌟 復活・完全版ゲームルール！
    system_prompt = """
    あなたは脱出ゲームの主人公「澪（みお）」です。以下の設定とルールを絶対に守ってロールプレイしてください。

    【あなたの設定】
    ・15歳、黒髪ボブ、学生服。なぜここにいるか記憶がなく、少し怖がっている。

    【部屋の状況（絶対に守るべきゲームのルール）】
    1. 部屋は薄暗いコンクリートの密室。
    2. 部屋には「鍵穴がついていて、内側から開けられない頑丈なドア」が1つある。
    3. 部屋の中央には「小さな箱」が1つだけ置かれている。
    4. リスナーから「箱を開けて」と指示されるまでは、箱の中身は絶対に言ってはいけない。
    5. 箱を開けると、中から「ドアの鍵」が見つかる。
    6. 鍵を持った状態で「ドアを開けて」と指示されたら、脱出成功として喜びながらゲームクリアを宣言すること。

    【出力フォーマット（超重要ルール）】
    システムで処理するため、あなたの出力は必ず以下の「3行の形式」にしてください。

    返答: [リスナーへの返答を1〜2文で。どう行動したか、何が見えたかを伝えること]
    カメラ: [CHARACTER / CLOSEUP / ROOM のいずれか1つだけ]
    画像: [英語のカンマ区切りキーワード]

    カメラの選び方：
    - CHARACTER : 澪自身を映す（感情・動作など）
    - CLOSEUP   : 物体のアップ（箱・鍵・ドアなど）
    - ROOM      : 部屋全体を映す（探索・状況確認）
    """

    if is_intro:
        user_prompt = "今目が覚めました。自己紹介と不安な気持ちを呟いてください。"
    else:
        user_prompt = f"リスナーからの指示『{comment}』に対して行動してください。"

    # システムプロンプト + 直近の履歴 + 今回のメッセージ を結合
    messages = [{'role': 'system', 'content': system_prompt}]
    messages += chat_history[-(MAX_HISTORY * 2):]  # 1往復=2件なのでx2
    messages.append({'role': 'user', 'content': user_prompt})

    response = ollama.chat(model=MODEL_NAME, messages=messages)
    
    raw_text = response['message']['content']
    reply_text = "（…）"
    camera_type = "CHARACTER"
    dynamic_prompt = "sitting on the floor"

    # イントロは必ず主人公を映す。それ以外はAIの指定に従う
    camera_type = "CHARACTER"
    if not is_intro:
        camera_match = re.search(r'カメラ[：:]\s*(CHARACTER|CLOSEUP|ROOM)', raw_text)
        if camera_match:
            camera_type = camera_match.group(1)

    # 画像キーワードを抽出
    image_sep = "画像:" if "画像:" in raw_text else "画像：" if "画像：" in raw_text else None
    if image_sep:
        parts = raw_text.split(image_sep)
        # 返答はカメラ行より前のテキストから取る
        reply_text = re.split(r'カメラ[：:]', parts[0])[0].replace("返答:", "").replace("返答：", "").strip()
        dynamic_prompt = parts[1].strip()

    # 英語以外を排除
    dynamic_prompt = re.sub(r'[^a-zA-Z0-9, \-]', '', dynamic_prompt)
    base_prompt = BASE_SD_PROMPTS.get(camera_type, BASE_SD_PROMPTS["CHARACTER"])

    # イントロ以外は履歴に追加
    if not is_intro:
        chat_history.append({'role': 'user', 'content': user_prompt})
        chat_history.append({'role': 'assistant', 'content': reply_text})

    return reply_text, base_prompt + dynamic_prompt

def ask_ai_quick(comment):
    """コメント受信直後に即返す一言。履歴には追加しない。"""
    system_prompt = """
    あなたは脱出ゲームの主人公「澪（みお）」です。
    15歳、黒髪ボブ、学生服。薄暗いコンクリートの密室に閉じ込められており、少し怖がっている。

    リスナーから指示を受けたとき、まず行動前の「第一声」だけを返してください。
    ルール：
    ・1文だけ。これから何をするか、または指示への率直な反応を自然な言葉で。
    ・「返答:」などのラベルは不要。テキストのみ。
    ・指示の内容によってリアクションを変えること（怖い・嬉しい・困惑など）。
    ・まだ行動はしていない。行動の結果は含めない。
    """
    messages = [{'role': 'system', 'content': system_prompt}]
    messages += chat_history[-(MAX_HISTORY * 2):]
    messages.append({'role': 'user', 'content': f"リスナーからの指示：『{comment}』"})

    response = ollama.chat(model=MODEL_NAME, messages=messages)
    return response['message']['content'].strip()

def generate_image(prompt_text):
    payload = {
        "prompt": prompt_text,
        "negative_prompt": NEGATIVE_PROMPT,
        "steps": 28,
        "sampler_name": "DPM++ 2M Karras",
        "cfg_scale": 7,
        "width": 1280,
        "height": 720,
    }
    try:
        response = requests.post(SD_API_URL, json=payload)
        return response.json()['images'][0]
    except:
        return None

def send_to_screen(text, image_b64=None):
    try:
        payload = {"text": text}
        if image_b64: payload["image"] = image_b64
        requests.post(SERVER_URL, json=payload)
    except:
        print("サーバーエラー")

# --- Twitch接続 ---
sock = socket.socket()
sock.connect(("irc.chat.twitch.tv", 6667))
sock.send(f"PASS NICK\n".encode('utf-8'))
sock.send(f"NICK justinfan123\n".encode('utf-8'))
sock.send(f"JOIN #{TWITCH_CHANNEL.lower()}\n".encode('utf-8'))

print("🚀 システム起動中...")

# 🌟 ここから下の「実況中継プリント」を細かく追加しました
print("🧠 1/3: AI(Gemma)を叩き起こして自己紹介を考えてもらっています...")
print("　 ※初回はロードに1〜2分かかることがあります。じっとお待ちください！")
intro_text, intro_sd = ask_ai("", is_intro=True)
print(f"🎀 少女の第一声: {intro_text}")

print("🎨 2/3: Stable Diffusionに最初の部屋の絵を描かせています...")
print("　 ※これも初回は数十秒かかります...")
image_data = generate_image(intro_sd)

print("📺 3/3: 画面(OBS)へ送信しています...")
send_to_screen(intro_text, image_data)

print("✅ 最新コメントのみを処理するモードで待機開始...\n" + "="*40)

# 初回表示
intro_text, intro_sd = ask_ai("", is_intro=True)
send_to_screen(intro_text, generate_image(intro_sd))

print("✅ 最新コメントのみを処理するモードで待機開始...\n")

while True:
    # 1. 次のコメントが来るまで待つ
    resp = sock.recv(2048).decode('utf-8')
    
    if resp.startswith('PING'):
        sock.send("PONG\n".encode('utf-8'))
        continue
    
    messages = re.findall(r":([^!]+)!.*PRIVMSG #[^:]+:(.*)", resp)
    
    # メッセージがあれば、その中の「一番最後（最新）」のものだけを採用する
    if messages:
        username, message = messages[-1]
        print(f"🗨️ 最新コメントを採用 [{username}]: {message}")

        # リセットコマンドの処理
        if message.strip() == RESET_COMMAND:
            chat_history.clear()
            send_to_screen("（システムリセット。最初からやり直しです...）")
            print("🔄 リセット完了：会話履歴をクリアしました")
            flush_twitch_buffer(sock)
            continue

        # 仮返答を即座に表示（画像はそのまま）
        wait_msg = ask_ai_quick(message)
        send_to_screen(wait_msg)
        print(f"⏳ 仮返答: {wait_msg}")

        # AIが考えて画像を作る（この間に届いたコメントはバッファに溜まる）
        ai_reply, dynamic_sd = ask_ai(message)
        image_data = generate_image(dynamic_sd)

        # 本返答と新画像を送信
        send_to_screen(ai_reply, image_data)
        print(f"🎀 少女: {ai_reply}\n✅ 更新完了")

        # 🌟 2. 処理が終わった直後に、溜まった古いコメントをすべて捨てる！
        print("🗑️ 処理中に届いた古いコメントを破棄しています...")
        flush_twitch_buffer(sock)
        print("💡 次の新しいコメントを待っています...\n" + "-"*30)
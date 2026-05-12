# 配信企画テスト — プロジェクト仕様概要

## プロジェクト概要

TwitchまたはYouTubeのライブチャットと連動するインタラクティブAI配信コンテンツ。
視聴者のコメントがAIキャラクターへの行動指示となり、ローカルLLM + Stable Diffusionで
テキスト返答と背景画像をリアルタイム生成してOBSに表示する。

---

## シナリオ構成（2種類）

### 1. 脱出ゲームシナリオ（`integrated_app.py` 旧版 / `fantasy_story.py`）
- キャラクター：澪（みお）、15歳、黒髪ボブ、学生服
- 設定：薄暗いコンクリートの密室に閉じ込められている
- ゴール：「箱を開ける」→ 鍵入手 →「ドアを開ける」→ 脱出成功でクリア

### 2. ファンタジー冒険シナリオ（`fantasy_story.py` 現行メイン / `world_settings.yaml`）
- キャラクター：アリア、20歳、銀髪、革鎧の女性冒険者
- 世界観：エルドリア大陸（魔法と剣の中世ファンタジー）
- ゴール：オープンエンド。リスナーの指示で物語が進む

---

## システム構成

```
[Twitch チャット (IRC)]
        │
        ▼
[fantasy_story.py]  ← メイン制御
        │
        ├─ ollama (Gemma4:e4b) ── 返答テキスト + 画像プロンプト生成
        │
        └─ Stable Diffusion WebUI API ── 画像生成
                │
                ▼
        [server.py / Flask :5000]
                │
                ▼
        [OBS ブラウザソース]
        templates/index.html（背景画像 + セリフ + コメント表示）
```

---

## ファイル構成

| ファイル | 役割 |
|---------|------|
| `fantasy_story.py` | **現行メイン**。ファンタジーシナリオ版Twitch統合スクリプト |
| `integrated_app.py` | 旧メイン（脱出ゲームシナリオ版）。参考用に残置 |
| `server.py` | Flask表示サーバー（OBSへデータ提供） |
| `world_settings.yaml` | ファンタジー世界観・NPC設定（外部YAMLで管理） |
| `templates/index.html` | OBSブラウザソース用表示画面 |
| `memory.json` | ゲーム記憶の永続保存ファイル（現在無効化中） |
| `introduction.html` | 配信導入用HTMLページ |

---

## 主要設定値（`fantasy_story.py`）

| 変数 | 値 |
|------|----|
| `TWITCH_CHANNEL` | `nakamu1770` |
| `MODEL_NAME` | `gemma4:e4b` |
| `SERVER_URL` | `http://127.0.0.1:5000/update` |
| `SD_API_URL` | `http://127.0.0.1:7860/sdapi/v1/txt2img` |
| `MAX_HISTORY` | 5往復 |
| `AUTO_ADVANCE_SECONDS` | 300秒（5分コメントなしで自律進行） |

---

## AIへの出力フォーマット

```
返答: [行動の結果・状況を1〜2文で語り口調]
カメラ: [CHARACTER / SCENE / CLOSEUP のいずれか]
画像: [英語のカンマ区切りキーワード]
```

- `CHARACTER`：アリア自身を映す（表情・ポーズ必須）
- `SCENE`：場所・風景全体（場所・時間帯・天候）
- `CLOSEUP`：アイテム・NPC・モンスターのアップ

---

## 処理フロー（`fantasy_story.py`）

1. 起動時にワールド設定（`world_settings.yaml`）をロード
2. AIに物語冒頭を生成させ、初期画像を生成・OBSに送信
3. コメント受信ループ：
   - コメント受信 → `ask_ai_quick()` で即座に一言仮返答を表示
   - `ask_ai()` で本格的な返答＋画像プロンプトを生成
   - Stable Diffusionで画像生成
   - Flask経由でOBSへ送信
   - 処理後に古いコメントバッファを全破棄
4. 5分間コメントがない場合、アリアが自律的に行動

---

## Flaskサーバー エンドポイント（`server.py`）

| エンドポイント | メソッド | 内容 |
|-------------|---------|------|
| `/` | GET | `index.html` を返す |
| `/update` | POST | テキスト・画像(base64)・thinking フラグを更新 |
| `/update_comment` | POST | 採用コメントを更新 |
| `/update_status` | POST | ステータス文字列を更新 |
| `/get_data` | GET | 全データをJSON返却 |

---

## OBS表示画面（`templates/index.html`）

- 背景：SD生成画像をbase64で全画面表示、0.5秒でフェード切り替え
- セリフ：画面下部、半透明ブラック・メイリオ32px・ピンクボーダー
- 採用コメント表示：左上に小ボックスで表示
- 思考中アイコン（🔮）：右上に点滅表示（thinking=true 時）
- ステータス文字列：右上に表示（「返答を考えています...」など）
- 1秒ごとにポーリングして自動更新

---

## Stable Diffusionベースプロンプト（ファンタジー版）

```
CHARACTER: 1girl, 20 years old, silver hair, fantasy adventurer outfit, leather armor,
           fantasy world, detailed background, cinematic lighting, masterpiece, high quality, [動的]
SCENE:     no humans, wide shot, fantasy landscape, cinematic lighting, detailed, masterpiece, high quality, [動的]
CLOSEUP:   close-up shot, fantasy, detailed, soft lighting, masterpiece, high quality, [動的]
```

- ネガティブプロンプト：身体崩れ・低品質・透かし等を排除
- 解像度：640×360 / ステップ数：28 / サンプラー：DPM++ 2M Karras / CFG：7

---

## 起動手順

```bash
# 1. Stable Diffusion WebUI を --api オプション付きで起動
# 2. Ollama で Gemma4 モデルをロード
ollama run gemma4:e4b

# 3. Flask サーバー起動（別ターミナル）
python server.py

# 4. OBS のブラウザソースに http://127.0.0.1:5000 を設定

# 5. メインスクリプト起動
python fantasy_story.py
```

---

## 既知の課題・TODO

| 優先度 | 内容 |
|--------|------|
| 高 | Twitch PASS トークンがダミー文字列（匿名接続 `justinfan123` で動作中） |
| 中 | ゲーム状態管理（アイテム所持等）をコード側で明示的に管理する |
| 中 | 脱出成功後のリセット・再プレイ機能（ファンタジー版では未実装） |
| 中 | 記憶機能（`memory.json` + `extract_memory_from_reply`）が一時無効化中 |
| 低 | YouTube版との統合 |
| 低 | コメントモデレーション |

---

## 特記事項

- `!reset` コメントで会話履歴をクリアして最初からやり直せる（デバッグ用）
- `world_settings.yaml` を編集するだけでシナリオの世界観・NPCを変更可能
- `SYSTEM_PROMPT` 定数を書き換えるだけで別シナリオに切り替わる設計
- 記憶機能（重要な出来事の永続保存）は実装済みだがコメントアウトで無効化中

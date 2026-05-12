# export_episode.py 使用方法

配信後にエピソードをWebページとして出力し、GitHub Pagesにpushするスクリプト。

---

## 前提条件

- `fantasy_story.py` を使った配信が完了していること（`episodes/YYYY-MM-DD.jsonl` が生成される）
- Ollama が起動中で `gemma4:e4b` モデルが使えること
- このフォルダが git リポジトリで、GitHub Pages が `docs/` フォルダをソースに設定済みであること

---

## ディレクトリ構成

```
配信企画テスト/
├── episodes/          ← fantasy_story.py が配信中に自動生成するログ
│   └── 2026-05-12.jsonl
├── docs/              ← GitHub Pages のソース
│   ├── index.html     ← スクリプトが自動更新
│   ├── assets/
│   │   └── style.css  ← スクリプトが自動生成
│   └── episodes/
│       └── 2026-05-12/
│           ├── index.html
│           ├── meta.json
│           └── img_000.jpg ...
└── export_episode.py
```

---

## 使い方

```powershell
# 当日分を処理してGitHub Pagesにpush
python export_episode.py

# 日付を指定して処理
python export_episode.py 2026-05-12

# HTMLだけ生成してpushしない（確認用）
python export_episode.py --no-push
```

---

## 初回セットアップ（Gitリポジトリ未設定の場合）

```powershell
git init
git remote add origin https://github.com/ユーザー名/リポジトリ名.git
git add .
git commit -m "initial commit"
git push -u origin main
```

GitHub リポジトリの Settings → Pages → Source を `docs/` フォルダに設定。

---

## スクリプトの処理内容

1. `episodes/YYYY-MM-DD.jsonl` からイベントデータを読み込む
2. Ollama（gemma4:e4b）でノベルとタイトルを自動生成
3. 画像をJPGとして `docs/episodes/日付/` に保存
4. エピソードページ（`docs/episodes/日付/index.html`）を生成
5. トップページ（`docs/index.html`）をエピソード一覧で更新
6. `git add → commit → push` でGitHub Pagesに反映

---

## 設定値（変更不要）

| 定数 | 値 |
|------|----|
| `MODEL_NAME` | `gemma4:e4b` |
| `EPISODES_DIR` | `./episodes/` |
| `DOCS_DIR` | `./docs/` |

---

## よくあるエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `エラー: episodes/YYYY-MM-DD.jsonl が見つかりません` | 配信ログが存在しない | 先に `fantasy_story.py` で配信を実施する |
| `git操作に失敗` | git 未設定またはリモート未設定 | 初回セットアップを実施する |
| Ollama 接続エラー | Ollama が起動していない | `ollama run gemma4:e4b` を実行してから再試行 |

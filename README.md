# gpu-undead-skill

讓 AI agent 在需要 GPU 時,自動確認 AI-Stack 上的容器還活著;被清掉了就自己重生一個。

AI-Stack 在容器閒置一段時間後會清空 GPU 容器,下次要用得重新點一遍建立容器。這個 skill 把那個流程自動化:

1. 登入 AI-Stack
2. 檢查專案裡有沒有容器
3. 沒有的話,走完「建立容器」精靈(選鏡像、GPU、SSH 密碼)
4. 印出 SSH 指令與 Jupyter 連結

## 安裝

需求:Python 3、`playwright`(`pip install playwright`),以及 Windows 內建的 Edge(也可用 Chrome)。腳本使用系統瀏覽器,不需要另外下載 Playwright 的瀏覽器。

作為 Claude Code skill 使用,clone 到 skills 資料夾:

```
git clone https://github.com/112703028/gpu-undead-skill ~/.claude/skills/gpu-undead-skill
```

接著複製 `.env.example` 為 `.env`,填入你的設定:

```
AI_STACK_URL=https://<主機IP>:<埠>/ai-stack/root
AI_STACK_PROJECT=<專案名稱>
AI_STACK_USER=<你的帳號>
AI_STACK_PASS=<你的密碼>
```

選填項目(容器名稱、GPU 型號、鏡像等)見 `.env.example`。`.env` 已被 `.gitignore` 排除,**不要提交它**。

## 單獨使用

```
python ai_stack_ensure.py              # 檢查,不存在就建立
python ai_stack_ensure.py --check-only # 只檢查,不建立
python ai_stack_ensure.py --dry-run    # 走到建立精靈最後一步但不送出
```

| 結束碼 | 意義 |
|--------|------|
| 0  | 容器已存在 |
| 10 | 容器不存在,已建立 |
| 11 | 容器不存在(`--check-only` / `--dry-run`) |
| 1  | 失敗,截圖在 `logs/` |

## 注意

- 這是針對特定版本 AI-Stack 介面寫的瀏覽器自動化,網站改版後選擇器可能失效。
- 建立容器會消耗你的 GPU 額度。
- 新容器是全新的,舊容器裡沒存到持久儲存的資料不會回來。
- 腳本會把 Jupyter 網址(內含 token)印在輸出裡,別把輸出貼到公開的地方。
- 使用前請確認你的使用方式符合所屬單位對該平台的規範。

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

### 掛載儲存裝置(建議)

容器被清掉時,沒掛載的檔案會一起消失。在 `.env` 加上掛載路徑,重建容器時會自動掛上你的儲存裝置,資料就不會跟著不見:

```
AI_STACK_MOUNT_PATH=/mnt/data
# AI_STACK_MOUNT_STORAGE=<儲存名稱>    # 有多個儲存時指定,沒填就用清單第一個
# AI_STACK_MOUNT_JUPYTER_WORKSPACE=0   # 1 = 設為 Jupyter 工作目錄
```

路徑必須以 `/mnt/` 開頭。沒設 `AI_STACK_MOUNT_PATH` 就不會掛載。

### 重建後自動還原 SSH 金鑰(選用)

容器每次重建都是全新環境,你電腦的公鑰不在登入名單裡,金鑰登入會失效(只能用密碼)。如果你有掛載儲存,可以把公鑰備份放在裡面,重建後讓腳本自動還原:

1. 在容器裡把你的公鑰備份到掛載路徑(只需做一次),例如:`cat ~/.ssh/authorized_keys > /mnt/data/authorized_keys_backup`
2. `pip install paramiko`
3. 在 `.env` 設定:

```
AI_STACK_RESTORE_SSH_KEYS=/mnt/data/authorized_keys_backup
```

之後腳本每次**剛建立新容器**時,會用密碼 SSH 進去把備份併入 `~/.ssh/authorized_keys`,並用你本機的金鑰實際登入一次來驗證。已存在的容器想手動補還原,加上 `--restore-keys`。這個動作是冪等的,重複執行不會出現重複金鑰。

注意:這會用 `.env` 裡的密碼做 SSH 登入,且接受容器的主機金鑰(新容器的主機金鑰每次都不同,無法預先信任)。只在你信任的網路使用。

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

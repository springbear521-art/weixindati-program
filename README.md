# 微信读书电脑答题助手

这个程序在电脑微信打开答题小程序后，截取整个小程序窗口，用 DeepSeek 识别题目、搜索并显示建议答案。答案以**选项文字**显示，例如“橘子”；请在小程序中自行核对和点选。

每题限时 12 秒。程序给识别、搜索和判断约 8.5 秒，网络或接口慢时可能来不及显示答案。

## 一、准备工作（首次使用）

1. 确认电脑是 Windows，已安装 Python 3.10 或更新版本。按 `Win` 键，输入 **PowerShell**，打开“Windows PowerShell”或“终端”中的 PowerShell。窗口提示符通常以 `PS` 开头。不要在“命令提示符 / CMD”中输入下面的 `Set-Location` 命令。
2. 在 PowerShell 中输入 `python --version`，确认能显示 Python 版本。如果提示找不到 `python`，可试 `py --version`；后面的 `python app.py` 相应改为 `py app.py`。
3. 在 PowerShell 中进入本项目文件夹。复制整行命令，按回车：

   ```powershell
   Set-Location -LiteralPath 'C:\Users\zhangxiaopeng\Documents\ChatGPT\答题程序运行 2'
   ```

4. 输入 `Get-ChildItem app.py`。若显示 `app.py`，说明已经进入正确文件夹。
5. 准备 DeepSeek **API 密钥**。这与 DeepSeek 聊天网页的登录账号不同。程序使用 `deepseek-flash` 识别与判断、DeepSeek Search API 搜索。接口调用可能产生费用。
6. 在同一个 PowerShell 窗口输入 `python app.py`（第 2 步使用 `py` 的话输入 `py app.py`），按回车。出现“微信读书答题助手”窗口后，在“API 密钥”输入框粘贴密钥，点击“保存密钥”。字符会以星号隐藏；保存后输入框清空，状态会显示“已保存在 Windows 凭据管理器”。

密钥只需保存一次。它保存在当前 Windows 用户的凭据管理器中，不写入项目文件、运行日志或 Git 仓库。以后换密钥时，在同一输入框输入新密钥并再次点击“保存密钥”。已有的 `DEEPSEEK_API_KEY` 环境变量也可作为备用。

## 二、每次打开程序

1. 打开 PowerShell，并运行上面的 `Set-Location -LiteralPath 'C:\Users\zhangxiaopeng\Documents\ChatGPT\答题程序运行 2'`。
2. 输入 `python app.py`，按回车。如果你的电脑只识别 `py`，输入 `py app.py`。**保持这个 PowerShell 窗口打开**，答题结束后的汇总会显示在这里。
3. 在电脑微信里通过分享链接打开答题小程序，保持小程序窗口可见。先停留在“开始答题”之前的页面。
4. 在助手的“答题窗口”下拉列表中选择小程序窗口。刚打开小程序而列表中没有时，点“刷新窗口”再选择。

## 三、自动答题

1. 先在助手中点击“开始自动监测”。助手会缩成浮动答案窗，开始观察小程序窗口。
2. 再回到小程序点击“开始答题”。程序会自动截取**整个小程序窗口**，无需手动框选截图范围。最好让浮动答案窗位于小程序窗口旁边，不要挡住题目。
3. 新题出现后，浮动窗会先显示“搜索中…”，完成后直接显示答案文字。核对题目与选项，再在小程序中点选。相同题目再次被识别时，程序会跳过重复搜索。
4. 如果启动监测时第一题已经出现，点击浮动窗的“立即识别当前题”。之后继续自动监测下一题。
5. 识别满 12 题后，最后一题答案会保留约 12 秒，程序随后自动停止，并在 PowerShell 中打印本次题目和答案。如果答题提前结束或漏题，点浮动窗的“停止并返回”，也会打印已识别的记录。

程序不会自动点击小程序选项。识别不清或搜索证据不足时会显示“无法判断”。

## 四、查看结果、日志和关闭程序

- **题目答案汇总**：切回启动程序的 PowerShell 窗口。每行显示题干、答案文字及选项序号，例如 `功亏___篑 → 一（第2项）`。
- **运行日志**：新版本开始记录画面触发、重复题跳过、接口阶段耗时和错误类型，文件为 `logs/quiz.log`。在项目文件夹的 PowerShell 中运行以下命令查看最近 50 行：

  ```powershell
  Get-Content -LiteralPath '.\logs\quiz.log' -Tail 50
  ```

  第一次运行前可能还没有日志文件。旧版本没有持久日志，所以无法回看此前的重复搜索。
- **结束程序**：点击助手窗口右上角的 `×`。PowerShell 回到 `PS ...>` 提示符后，可关闭 PowerShell。下次仍按“二、每次打开程序”的步骤启动。

主窗口默认约 820×700；手动调整后，关闭程序时会记住大小和位置。日志最多保留约 3 MB（含轮换文件），不会记录 API 密钥。

## 五、备用操作和常见问题

| 情况 | 操作 |
| --- | --- |
| 想确认截到什么画面 | 先在“答题窗口”选择小程序，点击“截取窗口”。截图范围是整个窗口。 |
| 想分析已有截图 | 点击“选图片”，选择图片，然后点击“识别并搜索所选图片”。 |
| 自动监测暂时没识别到当前题 | 点击浮动窗的“立即识别当前题”；也可停止监测后按 `F8`，或点击“截图答题 (F8)”。 |
| 找不到小程序窗口 | 确保电脑微信的小程序窗口已经打开，再点击“刷新窗口”。程序必须在当前登录的 Windows 桌面会话中运行。 |
| 截图空白或识别到别的内容 | 确保小程序窗口可见、未被其他窗口遮挡；把浮动窗移到小程序旁边，再试“截取窗口”检查画面。 |
| 程序提示超时 | 每题只有 12 秒，识图、搜索和判断需要串行网络请求；可查看 `logs/quiz.log` 中各阶段耗时。 |

## 工作原理和测试

`desktop_capture.py` 使用 Windows API 截取窗口，并比较题干区域的画面变化，尽量忽略倒计时与选项动画。`quiz_helper.py` 依次调用 DeepSeek 识图、搜索和判断，并按题干及选项去重。截图会发送给 DeepSeek API，请确认窗口里没有不想上传的内容。画面布局变化或模型识别错误仍可能导致漏题、误判。

开发时可在项目文件夹运行测试：

```powershell
python -m unittest discover -s tests -v
```

接口参考：[DeepSeek 图像输入](https://api-docs.deepseek.com/guides/vision/)、[Responses API](https://api-docs.deepseek.com/guides/responses_api/)、[搜索 API](https://api-docs.deepseek.com/guides/search/)；凭据存储参考微软的 [CREDENTIALW 说明](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)。

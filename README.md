# 微信读书电脑答题助手

电脑微信打开答题小程序后，本程序持续截取**整个小程序窗口**，用 DeepSeek 识别题目、搜索网页并在浮动窗口中直接显示选项文字，例如“一”。你仍需自己核对并在小程序中点选。

每题只有 **12 秒**。程序发现新题后给识别、搜索和判断约 8.5 秒的预算；网络或接口慢时可能来不及返回。

## 运行条件

- Windows、Python 3.10 或更新版本；仅使用 Python 标准库。
- DeepSeek API 密钥。识图和最终判断使用 `deepseek-flash`，搜索使用 DeepSeek Search API。
- 电脑微信的小程序窗口可见，题目与选项完整显示。尽量让浮动答案窗位于小程序窗口外面。

## 每次启动

在 PowerShell 中进入项目文件夹，运行：

```powershell
python app.py
```

第一次启动时，在程序内的“API 密钥”框粘贴密钥，点击“保存密钥”。输入框会隐藏字符，保存后清空。密钥保存在**当前 Windows 用户的凭据管理器**，目标名称为 `WeReadQuizHelper/DeepSeekApiKey`；项目文件、运行日志、Git 仓库中都不会保存密钥。以后启动无需重输，换密钥时直接覆盖保存。已有的 `DEEPSEEK_API_KEY` 环境变量仍可作为备用。

## 自动答题

1. 在电脑微信中打开小程序，停在“开始答题”之前的画面。
2. 从“答题窗口”列表选择小程序窗口；找不到时点“刷新窗口”。
3. 点击“开始自动监测”，再回到小程序开始答题。程序会先记下开始页画面，新题出现后自动截图，无需框选，也不必每题按 F8。
4. 浮动窗直接显示答案文字。若启动监测时第一题已经出现，点“立即识别当前题”。
5. 识别满 12 题后，最后一题答案会保留 12 秒，再自动停止并在启动程序的 PowerShell 窗口打印题目答案汇总。如果有漏题或提前结束，点“停止并返回”也会打印已有记录。

“电脑截屏”可检查程序截到的整个窗口；“识别并搜索所选图片”可分析已有图片；**F8** 可在非监测模式下快速截取当前窗口并搜索。

主窗口默认约 820×700，关闭时会记住你调整后的尺寸和位置。日志保存在项目的 `logs/quiz.log`，最多约 3 MB（含轮换文件）。日志记录触发、去重、耗时和错误类型，不记录密钥。旧版本没有持久运行日志，因此无法回看旧运行过程。

## 工作原理与限制

`desktop_capture.py` 用 Windows API 截取完整窗口，并比较题干所在区域的画面特征，忽略顶部倒计时和下部选项动画。`quiz_helper.py` 依次用 DeepSeek 识图、搜索、根据搜索摘要判断选项；识别出相同题目和选项时会跳过重复搜索。识别不清、没有搜索结果或证据不足时显示“无法判断”。

截图会发送给 DeepSeek API，请确认画面中没有不想上传的内容。小程序窗口被遮挡、缩放或画面布局改变时，自动检测可能漏题或误触发。模型也可能识别错笔画或答案；本程序不会自动点击选项。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

接口格式依据 [DeepSeek 图像输入文档](https://api-docs.deepseek.com/guides/vision/)、[Responses API 文档](https://api-docs.deepseek.com/guides/responses_api/)和[搜索 API 文档](https://api-docs.deepseek.com/guides/search/)。Windows 凭据使用微软的 [CREDENTIALW 说明](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)。

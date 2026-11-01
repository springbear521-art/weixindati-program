"""Desktop capture, search and answer interface for the WeRead quiz."""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from desktop_capture import (
    activate_window, capture_window, f8_pressed, list_windows, read_window_frame,
    save_frame, set_dpi_awareness, signature_difference, window_rect,
)
from quiz_helper import DEFAULT_MODEL, analyze_image


QUICK_BUDGET_SECONDS = 8.5
MONITOR_INTERVAL_SECONDS = 0.25
STABLE_DIFFERENCE = 0.003
NEW_QUESTION_DIFFERENCE = 0.006


class QuizApp(tk.Tk):
    def __init__(self) -> None:
        set_dpi_awareness()
        super().__init__()
        self.title("微信读书电脑答题助手")
        self.geometry("710x510")
        self.minsize(610, 430)
        self.image_path = tk.StringVar()
        self.window_name = tk.StringVar()
        self.window_handles: dict[str, int] = {}
        self.region: tuple[int, int, int, int] | None = None
        self.region_window: int | None = None
        self.model = tk.StringVar(value=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
        self.status = tk.StringVar(value="选择电脑微信窗口，框选一次题目与选项，再启动自动监测。")
        self.captures: list[Path] = []
        self.running = False
        self.run_id = 0
        self.closing = False
        self.last_f8_down = False
        self.monitoring = False
        self.monitor_id = 0
        self.monitor_stop = threading.Event()
        self.monitor_events: queue.Queue = queue.Queue()
        self.monitor_status = tk.StringVar(value="等待题目变化")
        self.monitor_answer = tk.StringVar(value="等待题目")
        self.events: queue.Queue = queue.Queue()
        self._build_ui()
        self.refresh_windows()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(20, self._poll_events)
        self.after(50, self._poll_hotkey)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        self.main_frame = frame
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="微信读书答题助手", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="选择答题窗口并框选题目与选项。启动后自动监测新题，无需每题按键。", wraplength=670).pack(anchor="w", pady=(4, 14))

        window_row = ttk.Frame(frame)
        window_row.pack(fill="x", pady=(0, 10))
        ttk.Label(window_row, text="答题窗口").pack(side="left")
        self.window_box = ttk.Combobox(window_row, textvariable=self.window_name, state="readonly")
        self.window_box.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.window_box.bind("<<ComboboxSelected>>", lambda _event: self._update_region_label())
        self.refresh_button = ttk.Button(window_row, text="刷新窗口", command=self.refresh_windows)
        self.refresh_button.pack(side="left")

        region_row = ttk.Frame(frame)
        region_row.pack(fill="x", pady=(0, 10))
        self.region_button = ttk.Button(region_row, text="框选题目区域", command=self.select_region)
        self.region_button.pack(side="left")
        self.region_label = tk.StringVar(value="尚未框选")
        ttk.Label(region_row, textvariable=self.region_label).pack(side="left", padx=(10, 0))
        self.monitor_button = ttk.Button(region_row, text="开始自动监测", command=self.toggle_monitor)
        self.monitor_button.pack(side="right")

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.image_path).pack(side="left", fill="x", expand=True)
        self.pick_button = ttk.Button(row, text="选择截图", command=self.pick_image)
        self.pick_button.pack(side="left", padx=(8, 0))
        self.capture_button = ttk.Button(row, text="电脑截屏", command=self.capture)
        self.capture_button.pack(side="left", padx=(8, 0))
        self.quick_button = ttk.Button(row, text="截图→搜索→答案 (F8)", command=self.capture_and_analyze)
        self.quick_button.pack(side="left", padx=(8, 0))

        model_row = ttk.Frame(frame)
        model_row.pack(fill="x", pady=(12, 0))
        ttk.Label(model_row, text="模型").pack(side="left")
        ttk.Entry(model_row, textvariable=self.model, width=25).pack(side="left", padx=(8, 0))
        ttk.Label(model_row, text="密钥从 OPENAI_API_KEY 环境变量读取").pack(side="left", padx=(12, 0))

        self.analyze_button = ttk.Button(frame, text="识别并搜索所选图片", command=self.analyze)
        self.analyze_button.pack(anchor="w", pady=(16, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=570).pack(anchor="w", pady=(0, 8))
        self.output = tk.Text(frame, font=("Microsoft YaHei UI", 12), wrap="word", height=12)
        self.output.pack(fill="both", expand=True)
        self.output.insert("1.0", "结果将在这里显示。\n答案需要你自己核对后在小程序中点选。")
        self.output.tag_configure("quick", font=("Microsoft YaHei UI", 28, "bold"))
        self.output.configure(state="disabled")

        self.monitor_frame = ttk.Frame(self, padding=12)
        ttk.Label(self.monitor_frame, text="自动答题监测", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(self.monitor_frame, textvariable=self.monitor_answer,
                  font=("Microsoft YaHei UI", 28, "bold")).pack(anchor="center", pady=(3, 1))
        ttk.Label(self.monitor_frame, textvariable=self.monitor_status, wraplength=240).pack(anchor="center")
        ttk.Button(self.monitor_frame, text="停止并返回", command=self.stop_monitor).pack(anchor="center", pady=(5, 0))

    def pick_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.gif")])
        if path:
            self.image_path.set(path)
            self.status.set("已选择截图，点击“分析当前题目”。")

    def refresh_windows(self) -> None:
        previous = self.window_name.get()
        windows = [window for window in list_windows()
                   if window.hwnd != self.winfo_id() and window.title != self.title()]
        labels = [f"{window.title}  [HWND {window.hwnd}]" for window in windows]
        self.window_handles = dict(zip(labels, (window.hwnd for window in windows)))
        self.window_box["values"] = labels
        if previous in self.window_handles:
            self.window_name.set(previous)
        else:
            matches = [label for label in labels if any(word in label.lower() for word in ("微信读书", "weread", "小程序"))]
            self.window_name.set(matches[0] if matches else "")
        self._update_region_label()

    def _update_region_label(self) -> None:
        if self.region and self.region_window == self.window_handles.get(self.window_name.get()):
            self.region_label.set(f"已框选 {self.region[2]}×{self.region[3]} 像素")
        else:
            self.region_label.set("尚未框选当前窗口")

    def _selected_hwnd(self) -> int | None:
        hwnd = self.window_handles.get(self.window_name.get())
        if hwnd is None:
            messagebox.showinfo("答题助手", "请先选择电脑微信中的答题窗口；若未显示，请点“刷新窗口”。")
        return hwnd

    def select_region(self) -> None:
        if self.running or self.monitoring:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        self.withdraw()
        self.after(100, lambda: self._show_region_overlay(hwnd))

    def _show_region_overlay(self, hwnd: int) -> None:
        try:
            activate_window(hwnd)
            left, top, width, height = window_rect(hwnd)
            overlay = tk.Toplevel(self)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", 0.35)
            overlay.geometry(f"{width}x{height}+{left}+{top}")
            canvas = tk.Canvas(overlay, bg="#101820", cursor="crosshair", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            canvas.create_text(width // 2, 30, text="拖动鼠标框住题干和所有选项；排除倒计时。Esc 取消",
                               fill="white", font=("Microsoft YaHei UI", 12, "bold"))
            drag = {"start": None, "rectangle": None}

            def cancel(_event=None) -> None:
                overlay.destroy()
                self._restore()

            def press(event) -> None:
                drag["start"] = (event.x, event.y)
                if drag["rectangle"] is not None:
                    canvas.delete(drag["rectangle"])
                drag["rectangle"] = canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                              outline="#00ffff", width=4)

            def move(event) -> None:
                if drag["start"] is not None:
                    x, y = drag["start"]
                    canvas.coords(drag["rectangle"], x, y, event.x, event.y)

            def release(event) -> None:
                if drag["start"] is None:
                    return
                x0, y0 = drag["start"]
                x1, y1 = event.x, event.y
                x, y = max(0, min(x0, x1)), max(0, min(y0, y1))
                right, bottom = min(width, max(x0, x1)), min(height, max(y0, y1))
                if right - x < 80 or bottom - y < 80:
                    self.status.set("框选范围太小，请重新框选。")
                    cancel()
                    return
                self.region = (x, y, right - x, bottom - y)
                self.region_window = hwnd
                self._update_region_label()
                self.status.set("已保存框选区域。点击“开始自动监测”，之后每题自动识别。")
                cancel()

            canvas.bind("<ButtonPress-1>", press)
            canvas.bind("<B1-Motion>", move)
            canvas.bind("<ButtonRelease-1>", release)
            overlay.bind("<Escape>", cancel)
            overlay.focus_force()
        except Exception as exc:
            self._restore()
            messagebox.showerror("答题助手", str(exc))

    def _poll_hotkey(self) -> None:
        down = f8_pressed()
        if down and not self.last_f8_down and not self.running and not self.monitoring:
            self.capture_and_analyze()
        self.last_f8_down = down
        if not self.closing:
            self.after(50, self._poll_hotkey)

    def _restore(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()

    def _busy(self, enabled: bool) -> None:
        self.running = enabled
        state = "disabled" if enabled or self.monitoring else "normal"
        self.pick_button.configure(state=state)
        self.capture_button.configure(state=state)
        self.quick_button.configure(state=state)
        self.analyze_button.configure(state=state)
        self.refresh_button.configure(state=state)
        self.region_button.configure(state=state)
        self.monitor_button.configure(state="disabled" if enabled else "normal")

    def _result(self, value: str, *, quick: bool = False) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)
        if quick:
            self.output.tag_add("quick", "1.0", "end")
        self.output.configure(state="disabled")

    def _run(self, task, done, *, deadline_seconds: float | None = None, discard=None) -> None:
        if self.running:
            return
        self.run_id += 1
        run_id = self.run_id
        self._busy(True)

        if deadline_seconds is not None:
            deadline = time.monotonic() + deadline_seconds

            def countdown() -> None:
                if run_id != self.run_id:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.run_id += 1
                    self._busy(False)
                    self._restore()
                    self._result("本题分析超时\n请直接看电脑题目或使用道具。", quick=True)
                    self.status.set(f"已超过 {deadline_seconds:g} 秒的程序预算，迟到的答案不会显示。")
                    return
                self.status.set(f"正在分析，程序预算剩余 {remaining:.1f} 秒（题目总限时 12 秒）")
                self.after(100, countdown)

            countdown()

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                if not self.closing:
                    self.events.put((run_id, "error", str(exc), None, None))
            else:
                if self.closing:
                    if discard is not None:
                        discard(result)
                else:
                    self.events.put((run_id, "result", result, done, discard))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        self._poll_monitor_events()
        while True:
            try:
                run_id, kind, value, done, discard = self.events.get_nowait()
            except queue.Empty:
                break
            if run_id == self.run_id:
                if kind == "error":
                    self._finish_error(value)
                else:
                    self.run_id += 1
                    done(value)
            elif kind == "result" and discard is not None:
                discard(value)
        if not self.closing:
            self.after(20, self._poll_events)

    def _finish_error(self, error: str) -> None:
        self.run_id += 1
        self._busy(False)
        self._restore()
        self.status.set("操作失败。")
        messagebox.showerror("答题助手", error)

    def capture(self) -> None:
        if self.running or self.monitoring:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        self.status.set("正在截取电脑答题窗口……")

        def done(path: Path) -> None:
            self._busy(False)
            self._restore()
            self.captures.append(path)
            self.image_path.set(str(path))
            self.status.set("已截取画面。可点击“识别并搜索所选图片”。")

        self.withdraw()
        region = self.region if self.region_window == hwnd else None
        self._run(lambda: self._capture(hwnd, region), done, discard=lambda path: path.unlink(missing_ok=True))

    @staticmethod
    def _capture(hwnd: int, region: tuple[int, int, int, int] | None = None) -> Path:
        activate_window(hwnd)
        return capture_window(hwnd, region)

    def analyze(self) -> None:
        if self.monitoring:
            return
        path = self.image_path.get().strip()
        if not path:
            messagebox.showinfo("答题助手", "请先选择截图或用“电脑截屏”。")
            return
        key = os.environ.get("OPENAI_API_KEY", "")
        model = self.model.get().strip()
        self.status.set("正在识别题目、网页搜索并生成建议……")

        def done(answer: str) -> None:
            self._busy(False)
            self._result(answer)
            self.status.set("分析完成，请核对题目和选项后再点选。")
            self.bell()

        self._run(lambda: analyze_image(path, api_key=key, model=model), done)

    def capture_and_analyze(self) -> None:
        if self.running or self.monitoring:
            return
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            messagebox.showinfo("答题助手", "请先设置 OPENAI_API_KEY 环境变量。")
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        if self.region_window != hwnd or self.region is None:
            messagebox.showinfo("答题助手", "请先点击“框选题目区域”，框住题干和所有选项。")
            return
        region = self.region
        model = self.model.get().strip()
        started = time.monotonic()
        self._result("正在截屏、搜索……", quick=True)

        def task() -> tuple[Path, str, float, float]:
            path = self._capture(hwnd, region)
            captured = time.monotonic()
            try:
                remaining = QUICK_BUDGET_SECONDS - (captured - started) - 0.5
                if remaining <= 1:
                    raise TimeoutError("截屏耗时过长，本题已无法在时限内分析。")
                answer = analyze_image(path, api_key=key, model=model, timeout=remaining, quick=True)
                finished = time.monotonic()
                return path, answer, captured - started, finished - captured
            except Exception:
                path.unlink(missing_ok=True)
                raise

        def done(result: tuple[Path, str, float, float]) -> None:
            path, answer, capture_time, model_time = result
            self._restore()
            self.captures.append(path)
            self.image_path.set(str(path))
            self._busy(False)
            self._result(answer, quick=True)
            self.status.set(f"取图 {capture_time:.1f} 秒，识图与搜索 {model_time:.1f} 秒；请立即在电脑上核对并点选。")
            self.bell()

        self.withdraw()
        self._run(task, done, deadline_seconds=QUICK_BUDGET_SECONDS, discard=lambda result: result[0].unlink(missing_ok=True))

    def toggle_monitor(self) -> None:
        if self.monitoring:
            self.stop_monitor()
            return
        if self.running:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        if self.region_window != hwnd or self.region is None:
            messagebox.showinfo("答题助手", "请先框选题干和全部选项；框选时尽量排除倒计时和动画。")
            return
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            messagebox.showinfo("答题助手", "请先设置 OPENAI_API_KEY 环境变量。")
            return
        region, model = self.region, self.model.get().strip()
        try:
            activate_window(hwnd)
            self._show_monitor_view(hwnd, region)
        except Exception as exc:
            messagebox.showerror("答题助手", str(exc))
            return
        self.monitor_id += 1
        monitor_id = self.monitor_id
        self.monitor_stop = threading.Event()
        self.monitoring = True
        self._busy(False)
        self.monitor_answer.set("等待题目")
        self.monitor_status.set("画面稳定后自动识别、搜索")
        self.status.set("自动监测中；题目变化后会自动分析。")
        threading.Thread(target=self._monitor_loop,
                         args=(monitor_id, self.monitor_stop, hwnd, region, key, model), daemon=True).start()

    def _show_monitor_view(self, hwnd: int, region: tuple[int, int, int, int]) -> None:
        left, top, width, height = window_rect(hwnd)
        self.saved_geometry = self.geometry()
        self.main_frame.pack_forget()
        self.monitor_frame.pack(fill="both", expand=True)
        self.minsize(250, 145)
        rx, ry, rw, rh = region
        crop = (left + rx, top + ry, left + rx + rw, top + ry + rh)
        popup_width, popup_height = 260, 155
        candidates = [
            (left + width + 10, top),
            (left - popup_width - 10, top),
            (left + max(0, width - popup_width), top + max(0, ry - popup_height - 10)),
            (left + max(0, width - popup_width), top + ry + rh + 10),
        ]
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        position = None
        for x, y in candidates:
            on_screen = x >= 0 and y >= 0 and x + popup_width <= screen_width and y + popup_height <= screen_height
            overlaps_crop = x < crop[2] and x + popup_width > crop[0] and y < crop[3] and y + popup_height > crop[1]
            if on_screen and not overlaps_crop:
                position = (x, y)
                break
        if position is None:
            position = (max(0, screen_width - popup_width - 10), 10)
        self.geometry(f"{popup_width}x{popup_height}+{position[0]}+{position[1]}")
        self.attributes("-topmost", True)

    def _monitor_loop(self, monitor_id: int, stop: threading.Event, hwnd: int,
                      region: tuple[int, int, int, int], key: str, model: str) -> None:
        previous: bytes | None = None
        submitted: bytes | None = None
        stable_frames = 0
        blank_frames = 0
        try:
            while not stop.is_set():
                frame = read_window_frame(hwnd, region)
                signature = frame.signature
                if max(signature) - min(signature) < 20:
                    blank_frames += 1
                    if blank_frames == 8:
                        self.monitor_events.put((monitor_id, "blank", None))
                    stable_frames = 0
                    previous = signature
                    stop.wait(MONITOR_INTERVAL_SECONDS)
                    continue
                blank_frames = 0
                if previous is not None and signature_difference(previous, signature) <= STABLE_DIFFERENCE:
                    stable_frames += 1
                else:
                    stable_frames = 0
                previous = signature
                new_question = submitted is None or signature_difference(submitted, signature) >= NEW_QUESTION_DIFFERENCE
                if stable_frames >= 1 and new_question:
                    submitted = signature
                    stable_frames = 0
                    path = save_frame(frame)
                    self.monitor_events.put((monitor_id, "analyzing", None))
                    started = time.monotonic()
                    try:
                        answer = analyze_image(path, api_key=key, model=model,
                                               timeout=QUICK_BUDGET_SECONDS - 0.3, quick=True)
                    except Exception as exc:
                        path.unlink(missing_ok=True)
                        if "timed out" in str(exc).lower() or isinstance(exc, TimeoutError):
                            self.monitor_events.put((monitor_id, "timeout", None))
                            continue
                        raise
                    elapsed = time.monotonic() - started
                    if elapsed > QUICK_BUDGET_SECONDS or stop.is_set():
                        path.unlink(missing_ok=True)
                        if not stop.is_set():
                            self.monitor_events.put((monitor_id, "timeout", None))
                    else:
                        self.monitor_events.put((monitor_id, "answer", (path, answer, elapsed)))
                stop.wait(MONITOR_INTERVAL_SECONDS)
        except Exception as exc:
            if not stop.is_set():
                self.monitor_events.put((monitor_id, "error", str(exc)))

    def _poll_monitor_events(self) -> None:
        while True:
            try:
                monitor_id, kind, value = self.monitor_events.get_nowait()
            except queue.Empty:
                break
            if monitor_id != self.monitor_id or not self.monitoring:
                if kind == "answer":
                    value[0].unlink(missing_ok=True)
                continue
            if kind == "analyzing":
                self.monitor_answer.set("搜索中…")
                self.monitor_status.set("已发现新题，正在识别和搜索")
            elif kind == "answer":
                path, answer, elapsed = value
                self.captures.append(path)
                self.image_path.set(str(path))
                self.monitor_answer.set(answer)
                self.monitor_status.set(f"识图与搜索 {elapsed:.1f} 秒；请立即核对并点选")
                self._result(answer, quick=True)
                self.status.set(f"自动识别完成，用时 {elapsed:.1f} 秒。")
                self.bell()
            elif kind == "timeout":
                self.monitor_answer.set("已超时")
                self.monitor_status.set("本题未及时返回；继续监测下一题")
            elif kind == "blank":
                self.monitor_answer.set("未看到题目")
                self.monitor_status.set("截图似乎空白；请停止后检查窗口与框选区域")
            elif kind == "error":
                self.stop_monitor()
                self.status.set(f"自动监测停止：{value}")
                messagebox.showerror("自动监测停止", value)

    def stop_monitor(self) -> None:
        if not self.monitoring:
            return
        self.monitoring = False
        self.monitor_id += 1
        self.monitor_stop.set()
        self.attributes("-topmost", False)
        self.monitor_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)
        self.minsize(610, 430)
        self.geometry(self.saved_geometry)
        self._busy(False)
        self.status.set("已停止自动监测。可重新框选或再次启动。")

    def close(self) -> None:
        self.closing = True
        if self.monitoring:
            self.stop_monitor()
        while not self.monitor_events.empty():
            _monitor_id, kind, value = self.monitor_events.get_nowait()
            if kind == "answer":
                value[0].unlink(missing_ok=True)
        self.run_id += 1
        while not self.events.empty():
            run_id, kind, value, done, discard = self.events.get_nowait()
            if kind == "result" and discard is not None:
                discard(value)
        for capture in self.captures:
            try:
                capture.unlink(missing_ok=True)
            except OSError:
                pass
        self.destroy()


if __name__ == "__main__":
    QuizApp().mainloop()

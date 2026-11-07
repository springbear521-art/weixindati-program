"""Desktop capture, search and answer interface for the WeRead quiz."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from desktop_capture import (
    activate_window, capture_window, f8_pressed, list_windows, read_window_frame,
    save_frame, set_dpi_awareness, signature_difference,
)
from credential_store import load_key, save_key
from quiz_helper import DEFAULT_MODEL, QuizResult, analyze_image


QUICK_BUDGET_SECONDS = 8.5
EXPECTED_QUESTION_COUNT = 12
MONITOR_INTERVAL_SECONDS = 0.25
STABLE_DIFFERENCE = 0.003
NEW_QUESTION_DIFFERENCE = 0.03
WINDOW_STATE = Path(__file__).with_name(".window_state.json")
LOG_PATH = Path(__file__).with_name("logs") / "quiz.log"


def _logger() -> logging.Logger:
    LOG_PATH.parent.mkdir(exist_ok=True)
    logger = logging.getLogger("weread_quiz")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = _logger()


class QuizApp(tk.Tk):
    def __init__(self) -> None:
        set_dpi_awareness()
        super().__init__()
        self.title("微信读书电脑答题助手")
        self.geometry(self._load_geometry())
        self.minsize(810, 660)
        self.image_path = tk.StringVar()
        self.window_name = tk.StringVar()
        self.window_handles: dict[str, int] = {}
        self.model = tk.StringVar(value=DEFAULT_MODEL)
        self.status = tk.StringVar(value="选择电脑微信小程序窗口，保存密钥后，在开始答题前启动自动监测。")
        self.key_input = tk.StringVar()
        self.key_status = tk.StringVar(value="密钥状态：检查中")
        self.session_results: list[QuizResult] = []
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
        self._refresh_key_status()
        self.refresh_windows()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(20, self._poll_events)
        self.after(50, self._poll_hotkey)

    def _load_geometry(self) -> str:
        try:
            saved = json.loads(WINDOW_STATE.read_text(encoding="utf-8"))["geometry"]
            match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", saved)
            if match:
                width, height, x, y = map(int, match.groups())
                if 810 <= width <= self.winfo_screenwidth() and 660 <= height <= self.winfo_screenheight() \
                        and 0 <= x < self.winfo_screenwidth() - 150 and 0 <= y < self.winfo_screenheight() - 100:
                    return saved
        except (OSError, KeyError, ValueError, TypeError):
            pass
        return "820x700"

    def _refresh_key_status(self) -> None:
        try:
            saved = bool(load_key())
        except OSError:
            saved = False
        self.key_status.set("密钥状态：已保存在 Windows 凭据管理器" if saved else
                            "密钥状态：尚未保存；也可使用 DEEPSEEK_API_KEY 环境变量")

    def _api_key(self) -> str:
        return (load_key() or os.environ.get("DEEPSEEK_API_KEY", "")).strip()

    def _save_key(self) -> None:
        try:
            save_key(self.key_input.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror("保存密钥失败", str(exc))
            return
        self.key_input.set("")
        self._refresh_key_status()
        LOGGER.info("DeepSeek key saved to Windows Credential Manager")
        self.status.set("密钥已保存。以后启动程序无需再次输入。")

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        self.main_frame = frame
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="微信读书答题助手", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="选择小程序窗口，开始答题前启动监测。程序自动截取整个窗口并识别新题。", wraplength=780).pack(anchor="w", pady=(4, 14))

        window_row = ttk.Frame(frame)
        window_row.pack(fill="x", pady=(0, 10))
        ttk.Label(window_row, text="答题窗口").pack(side="left")
        self.window_box = ttk.Combobox(window_row, textvariable=self.window_name, state="readonly")
        self.window_box.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.refresh_button = ttk.Button(window_row, text="刷新窗口", command=self.refresh_windows)
        self.refresh_button.pack(side="left")

        monitor_row = ttk.Frame(frame)
        monitor_row.pack(fill="x", pady=(0, 10))
        ttk.Label(monitor_row, text="截图范围：整个小程序窗口（无需框选）").pack(side="left")
        self.monitor_button = ttk.Button(monitor_row, text="开始自动监测", command=self.toggle_monitor)
        self.monitor_button.pack(side="right")

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.image_path, width=12).pack(side="left", fill="x", expand=True)
        self.pick_button = ttk.Button(row, text="选图片", command=self.pick_image)
        self.pick_button.pack(side="left", padx=(8, 0))
        self.capture_button = ttk.Button(row, text="截取窗口", command=self.capture)
        self.capture_button.pack(side="left", padx=(8, 0))
        self.quick_button = ttk.Button(row, text="截图答题 (F8)", command=self.capture_and_analyze)
        self.quick_button.pack(side="left", padx=(8, 0))

        model_row = ttk.Frame(frame)
        model_row.pack(fill="x", pady=(12, 0))
        ttk.Label(model_row, text="模型").pack(side="left")
        ttk.Entry(model_row, textvariable=self.model, width=25, state="readonly").pack(side="left", padx=(8, 0))
        key_row = ttk.Frame(frame)
        key_row.pack(fill="x", pady=(8, 0))
        ttk.Label(key_row, text="API 密钥").pack(side="left")
        ttk.Entry(key_row, textvariable=self.key_input, show="*", width=22).pack(side="left", padx=(6, 0))
        ttk.Button(key_row, text="保存密钥", command=self._save_key).pack(side="left", padx=(8, 0))
        ttk.Label(frame, textvariable=self.key_status).pack(anchor="w", pady=(5, 0))

        self.analyze_button = ttk.Button(frame, text="识别并搜索所选图片", command=self.analyze)
        self.analyze_button.pack(anchor="w", pady=(16, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=570).pack(anchor="w", pady=(0, 8))
        self.output = tk.Text(frame, font=("Microsoft YaHei UI", 12), wrap="word", width=1, height=1)
        self.output.pack(fill="both", expand=True)
        self.output.insert("1.0", "答案将在这里显示。\n请在小程序中核对后点选。")
        self.output.tag_configure("quick", font=("Microsoft YaHei UI", 28, "bold"))
        self.output.configure(state="disabled")

        self.monitor_frame = ttk.Frame(self, padding=12)
        ttk.Label(self.monitor_frame, text="自动答题监测", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        controls = ttk.Frame(self.monitor_frame)
        controls.pack(side="bottom", anchor="center", pady=(8, 16))
        ttk.Button(controls, text="立即识别当前题", command=self.force_current_question).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="停止并返回", command=self.stop_monitor).pack(side="left")
        ttk.Label(self.monitor_frame, textvariable=self.monitor_status, wraplength=740).pack(side="bottom", anchor="center")
        ttk.Label(self.monitor_frame, textvariable=self.monitor_answer,
                  font=("Microsoft YaHei UI", 38, "bold"), wraplength=740,
                  anchor="center", justify="center").pack(fill="both", expand=True)

    def pick_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.gif")])
        if path:
            self.image_path.set(path)
            self.status.set("已选择截图，点击“识别并搜索所选图片”。")

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

    def _selected_hwnd(self) -> int | None:
        hwnd = self.window_handles.get(self.window_name.get())
        if hwnd is None:
            messagebox.showinfo("答题助手", "请先选择电脑微信中的答题窗口；若未显示，请点“刷新窗口”。")
        return hwnd

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
        self._run(lambda: self._capture(hwnd), done, discard=lambda path: path.unlink(missing_ok=True))

    @staticmethod
    def _capture(hwnd: int) -> Path:
        activate_window(hwnd)
        return capture_window(hwnd)

    def analyze(self) -> None:
        if self.monitoring:
            return
        path = self.image_path.get().strip()
        if not path:
            messagebox.showinfo("答题助手", "请先选择截图或用“电脑截屏”。")
            return
        key = self._api_key()
        model = self.model.get().strip()
        self.status.set("正在识别题目、网页搜索并生成建议……")

        def done(answer: QuizResult) -> None:
            self._busy(False)
            self._result(answer.answer_text + ("\n\n" + answer.details if answer.details else ""))
            self.status.set("分析完成，请核对题目和选项后再点选。")
            self._record_answer(answer)
            self.bell()

        self._run(lambda: analyze_image(path, api_key=key, model=model), done)

    def capture_and_analyze(self) -> None:
        if self.running or self.monitoring:
            return
        key = self._api_key()
        if not key:
            messagebox.showinfo("答题助手", "请先输入并保存 DeepSeek API 密钥。")
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        model = self.model.get().strip()
        started = time.monotonic()
        self._result("正在截屏、搜索……", quick=True)

        def task() -> tuple[Path, QuizResult, float, float]:
            path = self._capture(hwnd)
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

        def done(result: tuple[Path, QuizResult, float, float]) -> None:
            path, answer, capture_time, model_time = result
            self._restore()
            self.captures.append(path)
            self.image_path.set(str(path))
            self._busy(False)
            self._result(answer.answer_text, quick=True)
            self.status.set(f"取图 {capture_time:.1f} 秒，识图与搜索 {model_time:.1f} 秒；请立即在电脑上核对并点选。")
            self._record_answer(answer)
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
        key = self._api_key()
        if not key:
            messagebox.showinfo("答题助手", "请先输入并保存 DeepSeek API 密钥。")
            return
        model = self.model.get().strip()
        try:
            activate_window(hwnd)
            self._show_monitor_view()
        except Exception as exc:
            messagebox.showerror("答题助手", str(exc))
            return
        self.monitor_id += 1
        monitor_id = self.monitor_id
        self.monitor_stop = threading.Event()
        self.force_capture = threading.Event()
        self.session_results.clear()
        self.monitoring = True
        self._busy(False)
        self.monitor_answer.set("等待题目")
        self.monitor_status.set("等待题目画面变化；已有题目可点立即识别")
        self.status.set("自动监测中；请在小程序中开始答题。")
        LOGGER.info("Monitor started hwnd=%s", hwnd)
        threading.Thread(target=self._monitor_loop,
                         args=(monitor_id, self.monitor_stop, hwnd, key, model), daemon=True).start()

    def _show_monitor_view(self) -> None:
        self.saved_geometry = self.geometry()
        self.main_frame.pack_forget()
        self.monitor_frame.pack(fill="both", expand=True)
        self.attributes("-topmost", True)

    def force_current_question(self) -> None:
        if self.monitoring:
            self.force_capture.set()
            self.monitor_status.set("正在读取当前画面")

    def _monitor_loop(self, monitor_id: int, stop: threading.Event, hwnd: int,
                      key: str, model: str) -> None:
        previous: bytes | None = None
        submitted: bytes | None = None
        change_started: float | None = None
        seen_questions: set[str] = set()
        stable_frames = 0
        blank_frames = 0
        try:
            while not stop.is_set():
                frame = read_window_frame(hwnd)
                signature = frame.signature
                if submitted is None:
                    # Establish a baseline before the quiz starts; do not analyze the start screen.
                    submitted = signature
                if max(signature) - min(signature) < 20:
                    blank_frames += 1
                    if blank_frames == 8:
                        self.monitor_events.put((monitor_id, "blank", None))
                    stable_frames = 0
                    previous = signature
                    change_started = None
                    stop.wait(MONITOR_INTERVAL_SECONDS)
                    continue
                blank_frames = 0
                if previous is not None and signature_difference(previous, signature) <= STABLE_DIFFERENCE:
                    stable_frames += 1
                else:
                    stable_frames = 0
                previous = signature
                change = signature_difference(submitted, signature)
                if change >= NEW_QUESTION_DIFFERENCE:
                    if change_started is None:
                        change_started = time.monotonic()
                else:
                    change_started = None
                forced = self.force_capture.is_set()
                if forced or (stable_frames >= 1 and change >= NEW_QUESTION_DIFFERENCE):
                    detection_delay = time.monotonic() - change_started if change_started is not None else 0.0
                    self.force_capture.clear()
                    submitted = signature
                    stable_frames = 0
                    change_started = None
                    path = save_frame(frame)
                    self.monitor_events.put((monitor_id, "analyzing", None))
                    LOGGER.info("Question trigger forced=%s visual_change=%.4f detection_delay=%.2fs",
                                forced, change, detection_delay)
                    started = time.monotonic()
                    try:
                        answer = analyze_image(path, api_key=key, model=model,
                                               timeout=QUICK_BUDGET_SECONDS - 0.3, quick=True,
                                               seen_questions=seen_questions)
                    except Exception as exc:
                        path.unlink(missing_ok=True)
                        LOGGER.warning("Question analysis failed type=%s elapsed=%.2fs", type(exc).__name__, time.monotonic() - started)
                        if "timed out" in str(exc).lower() or isinstance(exc, TimeoutError):
                            self.monitor_events.put((monitor_id, "timeout", None))
                            continue
                        raise
                    elapsed = time.monotonic() - started
                    if answer.duplicate:
                        path.unlink(missing_ok=True)
                        LOGGER.info("Duplicate question skipped question=%r elapsed=%.2fs", answer.question, elapsed)
                        self.monitor_events.put((monitor_id, "duplicate", None))
                        continue
                    LOGGER.info("Question analyzed question=%r answer=%r index=%s elapsed=%.2fs",
                                answer.question, answer.answer_text, answer.answer_index, elapsed)
                    if elapsed > QUICK_BUDGET_SECONDS or stop.is_set():
                        path.unlink(missing_ok=True)
                        if not stop.is_set():
                            self.monitor_events.put((monitor_id, "timeout", None))
                    else:
                        self.monitor_events.put((monitor_id, "answer", (path, answer, elapsed)))
                stop.wait(MONITOR_INTERVAL_SECONDS)
        except Exception as exc:
            if not stop.is_set():
                LOGGER.error("Monitor stopped unexpectedly type=%s", type(exc).__name__)
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
                self.monitor_answer.set(answer.answer_text)
                self.monitor_status.set(f"识图与搜索 {elapsed:.1f} 秒；请立即核对并点选")
                self._result(answer.answer_text, quick=True)
                self.status.set(f"自动识别完成，用时 {elapsed:.1f} 秒。")
                self._record_answer(answer)
                self.bell()
                if len(self.session_results) >= EXPECTED_QUESTION_COUNT:
                    session_id = self.monitor_id
                    self.monitor_status.set("第 12 题答案已显示；12 秒后自动汇总")
                    self.after(12000, lambda: self._finish_completed_session(session_id))
            elif kind == "duplicate":
                self.monitor_status.set("同一题已识别，继续等待新题")
            elif kind == "timeout":
                self.monitor_answer.set("已超时")
                self.monitor_status.set("本题未及时返回；继续监测下一题")
            elif kind == "blank":
                self.monitor_answer.set("未看到题目")
                self.monitor_status.set("截图似乎空白；请检查小程序窗口是否可见")
            elif kind == "error":
                self.stop_monitor()
                self.status.set(f"自动监测停止：{value}")
                messagebox.showerror("自动监测停止", value)

    def _finish_completed_session(self, session_id: int) -> None:
        if self.monitoring and self.monitor_id == session_id and len(self.session_results) >= EXPECTED_QUESTION_COUNT:
            self.stop_monitor()

    def stop_monitor(self) -> None:
        if not self.monitoring:
            return
        self.monitoring = False
        self.monitor_id += 1
        self.monitor_stop.set()
        self.attributes("-topmost", False)
        self.monitor_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True)
        self.minsize(810, 660)
        self.geometry(self.saved_geometry)
        self._busy(False)
        self.status.set("已停止自动监测。题目与答案汇总已输出到启动程序的命令窗口。")
        LOGGER.info("Monitor stopped answers=%d", len(self.session_results))
        self._print_session_summary()

    def _record_answer(self, answer: QuizResult) -> None:
        if not answer.question or answer.duplicate:
            return
        if not any(item.question == answer.question and item.options == answer.options
                   for item in self.session_results):
            self.session_results.append(answer)

    def _print_session_summary(self) -> None:
        print("\n=== 本次答题：题目与答案 ===", flush=True)
        if not self.session_results:
            print("没有记录到已识别题目。", flush=True)
        for number, item in enumerate(self.session_results, 1):
            suffix = f"（第{item.answer_index}项）" if item.answer_index else ""
            print(f"{number}. {item.question} → {item.answer_text}{suffix}", flush=True)
        print(f"共 {len(self.session_results)} 题。\n", flush=True)
        self.session_results.clear()

    def close(self) -> None:
        self.closing = True
        geometry_to_save = self.saved_geometry if self.monitoring else self.geometry()
        if self.monitoring:
            self.stop_monitor()
        elif self.session_results:
            self._print_session_summary()
        try:
            WINDOW_STATE.write_text(json.dumps({"geometry": geometry_to_save}), encoding="utf-8")
        except OSError:
            LOGGER.warning("Could not save main window geometry")
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

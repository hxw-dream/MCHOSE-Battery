"""浮窗真机诊断：12 秒内核对四档实际尺寸，记录到应用日志后正常关闭。"""
import float_window
import log

log_ = log.get_logger("widget.diag")


def main():
    demo = {"mouse": {"percent": 91, "charging": False, "connect": "2.4G"},
            "keyboard": {"percent": 15, "charging": False, "connect": "蓝牙"}}
    flags = {"visible": True, "size_factor": 0.5}
    widget = float_window.Widget(lambda: demo, flags)
    failures = []

    def record(factor):
        expected = float_window.card_size(widget.dpi_scale * factor)
        actual = (widget.tk.winfo_width(), widget.tk.winfo_height())
        log_.info("档位=%s dpi_scale=%.2f viewable=%s geom=%s expected=%s actual=%s",
                  factor, widget.dpi_scale, widget.tk.winfo_viewable(), widget.tk.geometry(), expected, actual)
        if actual != expected or not widget.tk.winfo_viewable():
            failures.append((factor, expected, actual))

    for index, factor in enumerate((0.5, 0.65, 1.0, 1.25)):
        widget.tk.after(index * 3000, lambda factor=factor: flags.update(size_factor=factor))
        widget.tk.after(index * 3000 + 2000, lambda factor=factor: record(factor))
    widget.tk.after(12000, lambda: flags.update(stop=True))
    log_.info("开始四档浮窗诊断，不保存演示位置和档位")
    widget.run()
    if failures:
        log_.error("浮窗诊断失败: %s", failures)
        return 1
    log_.info("四档浮窗诊断通过，已正常关闭")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
